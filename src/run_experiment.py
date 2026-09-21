"""run_experiment.py — LLMO効果測定実験の観測(2026-09-18 改訂).

順序:
  日付から観測計画 -> collect_llm(Gemini分 -> Claude分) -> 判定(experiment)
  -> data/raw/experiment/ -> llm_experiment タブ -> 欠測を実験日誌へ

- **割当は settings に1箇所だけ置く**(EXPERIMENT_CYCLE_START ほか)。
  47本を輪にして、開始日から1日ずつその日の本数だけ進める。曜日ごとの
  ID範囲を手で書かないので、本数を変えても割り振り直す作業が出ない。
- 収集は collect_llm を共有する(リトライ・掃き直し・欠測の数え方を書き写さない)。
- **日次・月次のタブ(llm_observations / monthly_observations / lk_*)には書かない。**
  実験の47本が混ざると、ダッシュボードの言及率の母数が曜日によって跳ねる。
- Gemini を先に回す。Claude の47本は時間がかかるので、後ろに置いても
  Gemini の枠の日付(太平洋時間)には影響しない。

日次との順序と枠(2026-09-21):
  - 日次のある日(火・木・土)は、日次の Gemini の raw が揃うまで待ってから走る
    (cron の遅れで順序が入れ替わることがある)。待っても揃わなければ、その日の
    実験の Gemini は投げずに reason=skipped の欠測として記録する。
  - 本数は「20 − 日次の実消費(attempts。再試行込み)− 月次 − 予備2」。
    名目の割当より少なければ末尾から削り、削った分も skipped として残す。
  - 429 の欠測が1日3件以上、または日次待ちで Gemini を飛ばした日は、
    exit 0 のまま Slack に1行出す(9/19 は10件落ちて通知ゼロだった)。

欠測の扱い(2026-09-18):
  - 503(一時的な混雑)は初回リトライ3回(5/10/20秒)+ 掃き直し2回
    (60秒後・180秒後)。投げる回数はその日の枠の余り(RetryBudget)で
    上から抑える。20回/日を超えない。余りは毎日空けておくのではなく、
    20 − その日の計画本数を 503 が出た日にだけ使う。使い切ったぶんは
    取り直しきれず欠測になる。
  - 429(枠切れ)は取り直さず、その場で欠測にする。翌日には枠が戻る。
  - **終了コードは欠測の理由で分ける。** 429 だけの欠測は exit 0(警告)。
    1件の一時的な混雑で毎回失敗通知が飛ぶと、本当の異常が埋もれるため。
    503 の欠測が残った場合・認証エラー・コード例外は exit 1。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_llm
import experiment
import notify_slack
import sheets_writer
from settings import (DATA_RAW_DIR, DATA_RAW_EXPERIMENT_DIR, EXPERIMENT_JOURNAL_FILE,
                      EXPERIMENT_WEEKLY_TARGET, GEMINI_DAILY_REQUEST_LIMIT, ROOT_DIR,
                      WEEKDAY_LABELS, experiment_gemini_allowance, experiment_plan,
                      gemini_requests_on, is_daily_llm_day, load_prompts,
                      monthly_requests_on)

MODEL_ORDER = ("gemini", "claude")

# 掃き直しの待ち時間。1回目で戻らない障害窓は90秒近いことがあるので、
# 2回目を3分後に置く(collect_llm の既定は60秒後に1回だけ)。
EXPERIMENT_SWEEP_DELAYS = (60.0, 180.0)

# 欠測のうち、ワークフローを失敗にしない理由。枠切れは翌日に戻るので、
# 通知を出しても人ができることが無い。
WARN_ONLY_REASONS = (collect_llm.REASON_QUOTA, collect_llm.REASON_SKIPPED)

# 429 の欠測がこの件数以上の日は、exit 0 のまま Slack に警告を出す。
QUOTA_ALERT_COUNT = 3

# 日次(火・木・土)の Gemini が揃うのを待つ時間と間隔。cron は2時間近く遅れる
# ことがあり、実験(08:00)が日次(07:00)より先に始まる日がありうる。
DAILY_WAIT_MINUTES = float(os.getenv("EXPERIMENT_DAILY_WAIT_MINUTES", "90"))
DAILY_POLL_SECONDS = float(os.getenv("EXPERIMENT_DAILY_POLL_SECONDS", "300"))

JOURNAL_HEADERS = ["date", "experiment_id", "model", "reason", "detail", "attempts"]

# 503由来の欠測の監視(2026-09-18)。火・木・土は日次7本と合わせて枠が
# ちょうど20になり、取り直しの余りが0になる。1週だけなら provider 側の
# 一過性だが、2週続けて週5件を超えるなら枠の配分そのものが足りていない。
UNAVAILABLE_WEEKLY_THRESHOLD = 5
UNAVAILABLE_ALERT_WEEKS = 2


def _job_summary(lines: List[str]) -> None:
    print("\n".join(lines))
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def observe(date: str, plan: Dict[str, List[Dict[str, Any]]], out_dir,
            failures: List[str],
            resolver: Optional[experiment.Resolver] = None,
            budget: Optional[collect_llm.RetryBudget] = None,
            delays=EXPERIMENT_SWEEP_DELAYS) -> List[Dict[str, Any]]:
    """計画どおりに観測し、判定列を足したレコードを返す(raw にも書き直す)。

    Gemini は日次・月次と20回/日の枠を分け合うので、再試行も掃き直しも
    ``budget``(その日の余り)から引く。Claude は別枠なので従来どおり。
    """
    if budget is None:
        budget = collect_llm.RetryBudget(gemini_requests_on(date)["retry_budget"])
    records: List[Dict[str, Any]] = []
    for model in MODEL_ORDER:
        prompts = plan.get(model) or []
        if not prompts:
            continue
        if model == "gemini":
            got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir,
                                      models=[model], sweep=False, budget=budget)
            collect_llm._sweep(got, prompts, out_dir, delays=delays, budget=budget)
        else:
            got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir,
                                      models=[model])
        if len(got) < len(prompts):
            # 無効・鍵なしのモデルは collect が黙って飛ばす。実験では計画した
            # 観測が丸ごと消えるので、ここで失敗として積む。
            failures.append(f"{model}: 計画{len(prompts)}本に対して観測{len(got)}件"
                            "(モデルが無効か API キーが無い)")
        by_id = {p["id"]: p for p in prompts}
        for record in got:
            record.update(experiment.evaluate(record, by_id[record["prompt_id"]], resolver))
            collect_llm._save(record, out_dir)
        records += got
    return records


# --------------------------------------------------------------------------
# 日次との順序と、日次の実消費
# --------------------------------------------------------------------------
def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT_DIR, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def _daily_gemini_from_origin(date: str) -> List[Dict[str, Any]]:
    """origin/main にある、その日の日次の Gemini raw。

    実験のワークフローは始まった時点の main を checkout している。日次がその
    あとに commit した raw は手元に無いので、取り直して読む。作業ツリーと
    index には触らない(このあとの commit に日次の raw を混ぜないため)。
    """
    try:
        _git("fetch", "--quiet", "origin", "main")
        listed = _git("ls-tree", "--name-only", "origin/main", f"data/raw/{date}/")
    except (OSError, subprocess.SubprocessError):
        return []
    if listed.returncode != 0:
        return []
    out = []
    for name in listed.stdout.split():
        if name.endswith("_gemini.json"):
            shown = _git("show", f"origin/main:{name}")
            if shown.returncode == 0:
                out.append(json.loads(shown.stdout))
    return out


def _daily_gemini_local(date: str) -> List[Dict[str, Any]]:
    folder = DATA_RAW_DIR / date
    return [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(folder.glob("*_gemini.json"))] if folder.exists() else []


def daily_gemini_records(date: str) -> List[Dict[str, Any]]:
    """その日の日次の Gemini raw。origin と手元で多いほうを使う。"""
    remote, local = _daily_gemini_from_origin(date), _daily_gemini_local(date)
    return remote if len(remote) >= len(local) else local


def daily_gemini_used(records: List[Dict[str, Any]]) -> int:
    """日次が Gemini に投げた回数(再試行・掃き直し込み)。

    attempts が無い古い raw は1回と数える(2026-09-18 より前の形式)。
    """
    return sum(int(r.get("attempts") or 1) for r in records)


def daily_is_done(records: List[Dict[str, Any]], expected: Optional[int] = None) -> bool:
    """日次の Gemini が全プロンプトぶん揃ったか(成否は問わない)。"""
    expected = len(load_prompts()) if expected is None else expected
    return len({r.get("prompt_id") for r in records}) >= expected


def wait_for_daily(date: str,
                   fetch: Callable[[str], List[Dict[str, Any]]] = daily_gemini_records,
                   sleep: Callable[[float], None] = time.sleep,
                   timeout_minutes: float = DAILY_WAIT_MINUTES,
                   poll_seconds: float = DAILY_POLL_SECONDS) -> Optional[int]:
    """日次の Gemini が揃うまで待ち、日次の実消費(回数)を返す。揃わなければ None。"""
    waited = 0.0
    while True:
        records = fetch(date)
        if daily_is_done(records):
            used = daily_gemini_used(records)
            print(f"[info] 日次の Gemini は完了済み(実消費 {used}回)")
            return used
        if waited >= timeout_minutes * 60:
            print(f"[warn] 日次の Gemini が {timeout_minutes:.0f}分待っても揃わない"
                  f"({len(records)}件)")
            return None
        print(f"[info] 日次の Gemini を待っています({len(records)}件。"
              f"{poll_seconds:.0f}秒後に再確認)")
        sleep(poll_seconds)
        waited += poll_seconds


def _skipped_record(date: str, prompt: Dict[str, Any], detail: str) -> Dict[str, Any]:
    """投げなかった観測の欠測行。collect_llm の record と同じ形にする。"""
    record = {
        "date": date, "prompt_id": prompt["id"], "pillar": prompt.get("pillar", ""),
        "category": prompt.get("category", ""), "target_brand": prompt.get("target_brand", ""),
        "model": "gemini", "model_name": collect_llm.MODEL_CONFIG["gemini"]["model"],
        "question": prompt["text"], "cep": prompt.get("cep"),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "answer": None, "cited_urls": [], "error": f"skipped: {detail}",
        "miss_reason": collect_llm.REASON_SKIPPED, "attempts": 0,
    }
    record.update(experiment.evaluate(record, prompt))
    return record


def size_gemini_plan(date: str, plan: Dict[str, List[Dict[str, Any]]],
                     daily_used: Optional[int],
                     wait_note: str = "") -> Tuple[Dict[str, List[Dict[str, Any]]],
                                                   List[Dict[str, Any]], int, List[str]]:
    """日次の実消費から、その日に実際に投げる Gemini の本数を決める。

    返り値は (実行する計画, 投げなかった欠測行, 取り直しの枠, 警告)。
    ``daily_used`` が None は「日次が終わらなかった」— Gemini は投げない。
    """
    gemini = list(plan.get("gemini") or [])
    rest = {k: v for k, v in plan.items() if k != "gemini"}
    if not gemini:
        return plan, [], 0, []
    warnings: List[str] = []
    if daily_used is None:
        detail = f"日次の観測が終わらないため実行せず{wait_note}"
        warnings.append(f"日次(火・木・土)の Gemini が揃わなかったため、実験の Gemini "
                        f"{len(gemini)}本を投げずに欠測として記録しました{wait_note}")
        return rest, [_skipped_record(date, p, detail) for p in gemini], 0, warnings
    allowance = experiment_gemini_allowance(date, daily_used)
    keep, cut = gemini[:allowance], gemini[allowance:]
    skipped = [_skipped_record(date, p, f"日次の実消費{daily_used}回で枠が足りず実行せず")
               for p in cut]
    budget = max(0, GEMINI_DAILY_REQUEST_LIMIT - daily_used - monthly_requests_on(date)
                 - len(keep))
    sized = dict(rest, gemini=keep) if keep else rest
    return sized, skipped, budget, warnings


def quota_alert_line(records: List[Dict[str, Any]],
                     threshold: int = QUOTA_ALERT_COUNT) -> Optional[str]:
    """429 の欠測が ``threshold`` 件以上なら Slack に出す1行。"""
    labels = missing_by_reason(records).get(collect_llm.REASON_QUOTA, [])
    if len(labels) < threshold:
        return None
    return (f"実験の Gemini が 429(枠切れ)で {len(labels)}件 欠測しました"
            f"(しきい値 {threshold}件): {', '.join(labels)}")


def missing_by_reason(records: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """欠測を理由コードごとにまとめる。終了コードの分岐がこれを読む。"""
    out: Dict[str, List[str]] = {}
    for rec in records:
        if not rec.get("error"):
            continue
        reason = rec.get("miss_reason") or collect_llm.miss_reason(rec["error"])
        out.setdefault(reason, []).append(f"{rec['prompt_id']}/{rec['model']}")
    return out


def _one_line(text: Any, limit: int = 300) -> str:
    """エラー文面を日誌の1セルに収める。改行と連続する空白をつぶす。"""
    return " ".join(str(text or "").split())[:limit]


def journal_rows(date: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """その日の欠測を実験日誌の行にする。観測できた行は残さない。"""
    rows = []
    for rec in records:
        if not rec.get("error"):
            continue
        rows.append({
            "date": rec.get("date") or date,
            "experiment_id": rec.get("experiment_id") or rec.get("prompt_id"),
            "model": rec.get("model"),
            "reason": rec.get("miss_reason") or collect_llm.miss_reason(rec["error"]),
            "detail": _one_line(rec["error"]),
            "attempts": rec.get("attempts") or 0,
        })
    return rows


def write_journal(date: str, records: List[Dict[str, Any]],
                  path: Optional[Path] = None) -> int:
    """欠測を実験日誌(CSV)に残す。

    **その日の行は毎回入れ替える。** 同じ日を取り直したときに、古い欠測が
    残っていると「観測できなかった件数」が二重に数えられる。
    書いた件数(その日の欠測数)を返す。
    """
    rows = journal_rows(date, records)
    kept: List[Dict[str, Any]] = []
    path = Path(path if path is not None else EXPERIMENT_JOURNAL_FILE)
    if path.exists():
        with open(path, "r", encoding="utf-8", newline="") as fh:
            kept = [r for r in csv.DictReader(fh) if (r.get("date") or "") != date]
    path.parent.mkdir(parents=True, exist_ok=True)
    everything = sorted(kept + rows,
                        key=lambda r: (str(r.get("date")), str(r.get("experiment_id")),
                                       str(r.get("model"))))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=JOURNAL_HEADERS)
        writer.writeheader()
        for row in everything:
            writer.writerow({k: row.get(k, "") for k in JOURNAL_HEADERS})
    print(f"[ok] 実験日誌: {date} の欠測 {len(rows)}件(累計 {len(everything)}件)")
    return len(rows)


def read_journal(path: Optional[Path] = None) -> List[Dict[str, str]]:
    """実験日誌を読む。まだ無ければ空(初回実行の前)。"""
    path = Path(path if path is not None else EXPERIMENT_JOURNAL_FILE)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def unavailable_by_week(date: str, weeks: int = UNAVAILABLE_ALERT_WEEKS,
                        path: Optional[Path] = None) -> List[int]:
    """``date`` で終わる直近 ``weeks`` 週の、503由来の欠測件数。古い週から並べる。

    週は「``date`` を最終日とする7日」で切る。ISO週に合わせないのは、週次が
    走る曜日が変わっても数え方が変わらないようにするため。
    """
    rows = [r for r in read_journal(path)
            if (r.get("reason") or "") == collect_llm.REASON_UNAVAILABLE]
    end = dt.date.fromisoformat(str(date)[:10])
    counts = []
    for index in range(weeks):
        last = end - dt.timedelta(days=7 * index)
        first = last - dt.timedelta(days=6)
        counts.append(sum(1 for r in rows
                          if first.isoformat() <= (r.get("date") or "") <= last.isoformat()))
    return list(reversed(counts))


def unavailable_watch_line(date: str, path: Optional[Path] = None,
                           threshold: int = UNAVAILABLE_WEEKLY_THRESHOLD,
                           weeks: int = UNAVAILABLE_ALERT_WEEKS) -> str:
    """週次サマリに出す1行。件数は毎週出し、しきい値を超え続けたときだけ警告にする。

    「今週だけ多い」は provider 側の波なので警告にしない。``weeks`` 週続けて
    ``threshold`` 件を超えたら、取り直しの枠が足りていないと読む。
    """
    counts = unavailable_by_week(date, weeks, path)
    shown = " / ".join(f"{c}件" for c in counts)
    if all(c > threshold for c in counts):
        return (f"- ⚠️ 実験の503欠測が{weeks}週続けて週{threshold}件を超えました"
                f"(古い週から {shown})。火・木・土は Gemini の枠の余りが0で"
                f"取り直せません。日次の観測日か1日の本数を見直してください")
    return (f"- 実験の503欠測(直近{weeks}週・古い週から): {shown}"
            f"(警告は週{threshold}件超が{weeks}週続いたとき)")


def weekly_observation_count(date: str, raw_dir: Optional[Path] = None) -> int:
    """``date`` を最終日とする7日に取れた実験の Gemini 観測の本数(欠測を除く)。"""
    raw_dir = Path(raw_dir if raw_dir is not None else DATA_RAW_EXPERIMENT_DIR)
    end = dt.date.fromisoformat(str(date)[:10])
    total = 0
    for offset in range(7):
        folder = raw_dir / (end - dt.timedelta(days=offset)).isoformat()
        for f in folder.glob("*_gemini.json") if folder.exists() else []:
            if not json.loads(f.read_text(encoding="utf-8")).get("error"):
                total += 1
    return total


def weekly_count_line(date: str, raw_dir: Optional[Path] = None,
                      target: int = EXPERIMENT_WEEKLY_TARGET) -> str:
    """週次サマリの1行。47本×週2回(94本)を下回った週は警告にする。"""
    count = weekly_observation_count(date, raw_dir)
    if count < target:
        return (f"- ⚠️ 実験の Gemini 観測が週{count}本で、目標{target}本"
                f"(47本×週2回)を下回りました")
    return f"- 実験の Gemini 観測: 週{count}本(目標{target}本)"


def summary_lines(date: str, plan: Dict[str, List[Dict[str, Any]]],
                  records: List[Dict[str, Any]],
                  budget: Optional[collect_llm.RetryBudget] = None) -> List[str]:
    quota = gemini_requests_on(date)
    weekday = WEEKDAY_LABELS[dt.date.fromisoformat(date).weekday()]
    lines = [
        f"## LLMO experiment — {date}({weekday})", "",
        "- 計画: " + (" / ".join(f"{m} {len(plan[m])}本" for m in MODEL_ORDER if m in plan)
                     or "観測なし"),
        f"- Gemini リクエスト見積もり: 日次{quota['daily']} + 月次{quota['monthly']}"
        f" + 実験{quota['experiment']} = {quota['total']} / 上限{quota['limit']}"
        f"(取り直しに使える余り{quota['retry_budget']}本"
        + (f"・うち{budget.used}本を使用)" if budget is not None else ")"),
    ]
    if quota["over"]:
        lines.append("- ⚠️ 1日の枠を超える見込み。settings の巡回設定を見直すこと")
    for model in MODEL_ORDER:
        rows = [r for r in records if r.get("model") == model]
        if not rows:
            continue
        ok = [r for r in rows if not r.get("error")]
        lines.append(
            f"- {model}: 観測 {len(ok)}/{len(rows)}"
            f" | cited_domain {sum(r['cited_domain'] for r in ok)}"
            f" | cited_article {sum(r['cited_article'] for r in ok)}"
            f" | mentioned {sum(r['mentioned'] for r in ok)}"
            f" | 未解決リダイレクト {sum(r['unresolved_redirects'] for r in ok)}件"
        )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="LLMO effect-measurement experiment")
    ap.add_argument("--date", help="観測日 YYYY-MM-DD(既定: 当日JST)。日付で計画が決まる")
    ap.add_argument("--no-sheets", action="store_true", help="シートに書かない")
    ap.add_argument("--dry-run", action="store_true",
                    help="観測せず、その日の計画と Gemini の見積もりだけ表示する")
    ap.add_argument("--no-wait", action="store_true",
                    help="日次の完了を待たない(手元の data/raw だけで実消費を数える)")
    args = ap.parse_args()

    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    plan = experiment_plan(date)
    # failures は exit 1、warnings は exit 0(警告だけ出して正常終了)。
    failures: List[str] = []
    warnings: List[str] = []
    slack: List[str] = []      # exit 0 のまま Slack に出す行

    if args.dry_run or not plan:
        lines = summary_lines(date, plan, [])
        if not plan:
            lines.append("- この日は実験の観測日ではありません")
        _job_summary(lines)
        return

    out_dir = DATA_RAW_EXPERIMENT_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)

    # 日次のある日は、日次の Gemini が揃ってから本数を決める。
    daily_used: Optional[int] = 0
    wait_note = ""
    if plan.get("gemini") and is_daily_llm_day(date):
        if args.no_wait:
            local = _daily_gemini_local(date)
            daily_used = daily_gemini_used(local) if daily_is_done(local) else None
            wait_note = "(--no-wait)"
        else:
            daily_used = wait_for_daily(date)
            wait_note = f"({DAILY_WAIT_MINUTES:.0f}分待機)"
    sized, skipped, retry_budget, sizing_warnings = size_gemini_plan(
        date, plan, daily_used, wait_note)
    slack += sizing_warnings
    for record in skipped:
        collect_llm._save(record, out_dir)

    budget = collect_llm.RetryBudget(retry_budget)
    records: List[Dict[str, Any]] = []
    try:
        records = observe(date, sized, out_dir, failures, budget=budget)
    except Exception as exc:  # noqa: BLE001 - 取れた分はこのあと保存する
        failures.append(f"observe: {exc}")
    records += skipped

    for reason, labels in sorted(missing_by_reason(records).items()):
        line = f"欠測 {len(labels)}件({reason}): {', '.join(labels)}"
        (warnings if reason in WARN_ONLY_REASONS else failures).append(line)
    quota_line = quota_alert_line(records)
    if quota_line:
        slack.append(quota_line)

    try:
        write_journal(date, records)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"write_journal: {exc}")

    lines = summary_lines(date, plan, records, budget)
    if plan.get("gemini"):
        lines.append(
            f"- 日次の Gemini 実消費: {'未完了' if daily_used is None else f'{daily_used}回'}"
            f" / 実験の Gemini: 名目{len(plan['gemini'])}本 → 実行"
            f"{len(sized.get('gemini') or [])}本(投げずに欠測 {len(skipped)}本)"
            f" / 取り直しの枠 {retry_budget}本")
    if args.no_sheets:
        lines.append("- Sheets: skipped (--no-sheets)")
    elif records:
        try:
            sheets_writer.write_experiment(records)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"write_experiment: {exc}")

    if slack:
        try:
            notify_slack.notify_experiment_warnings(date, slack)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"notify_experiment_warnings: {exc}")
        lines += ["", "### ⚠️ Slack に出した警告"] + [f"- {s}" for s in slack]
    if warnings:
        lines += ["", "### ⚠️ Warnings (枠切れ・未実行。失敗にはしない)"]
        lines += [f"- {w}" for w in warnings]
    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    elif not warnings:
        lines += ["", "All phases completed ✅"]
    _job_summary(lines)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
