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
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_llm
import experiment
import sheets_writer
from settings import (DATA_RAW_EXPERIMENT_DIR, EXPERIMENT_JOURNAL_FILE, WEEKDAY_LABELS,
                      experiment_plan, gemini_requests_on)

MODEL_ORDER = ("gemini", "claude")

# 掃き直しの待ち時間。1回目で戻らない障害窓は90秒近いことがあるので、
# 2回目を3分後に置く(collect_llm の既定は60秒後に1回だけ)。
EXPERIMENT_SWEEP_DELAYS = (60.0, 180.0)

# 欠測のうち、ワークフローを失敗にしない理由。枠切れは翌日に戻るので、
# 通知を出しても人ができることが無い。
WARN_ONLY_REASONS = (collect_llm.REASON_QUOTA,)

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
    args = ap.parse_args()

    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    plan = experiment_plan(date)
    # failures は exit 1、warnings は exit 0(警告だけ出して正常終了)。
    failures: List[str] = []
    warnings: List[str] = []

    if args.dry_run or not plan:
        lines = summary_lines(date, plan, [])
        if not plan:
            lines.append("- この日は実験の観測日ではありません")
        _job_summary(lines)
        return

    out_dir = DATA_RAW_EXPERIMENT_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = collect_llm.RetryBudget(gemini_requests_on(date)["retry_budget"])
    records: List[Dict[str, Any]] = []
    try:
        records = observe(date, plan, out_dir, failures, budget=budget)
    except Exception as exc:  # noqa: BLE001 - 取れた分はこのあと保存する
        failures.append(f"observe: {exc}")

    for reason, labels in sorted(missing_by_reason(records).items()):
        line = f"欠測 {len(labels)}件({reason}): {', '.join(labels)}"
        (warnings if reason in WARN_ONLY_REASONS else failures).append(line)

    try:
        write_journal(date, records)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"write_journal: {exc}")

    lines = summary_lines(date, plan, records, budget)
    if args.no_sheets:
        lines.append("- Sheets: skipped (--no-sheets)")
    elif records:
        try:
            sheets_writer.write_experiment(records)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"write_experiment: {exc}")

    if warnings:
        lines += ["", "### ⚠️ Warnings (枠切れ。翌日に枠が戻るので失敗にはしない)"]
        lines += [f"- {w}" for w in warnings]
    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    elif not warnings:
        lines += ["", "All phases completed ✅"]
    _job_summary(lines)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
