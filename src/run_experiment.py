"""run_experiment.py — LLMO効果測定実験の観測(2026-09-14).

順序:
  曜日から観測計画 -> collect_llm(Gemini分 -> Claude分) -> 判定(experiment)
  -> data/raw/experiment/ -> llm_experiment タブ

- **曜日割りは settings に1箇所だけ置く**(EXPERIMENT_GEMINI_GROUPS ほか)。
  ワークフローは観測のある曜日に毎回これを呼び、何を回すかはここで決める。
- 収集は collect_llm を共有する(リトライ・掃き直し・欠測の数え方を書き写さない)。
- **日次・月次のタブ(llm_observations / monthly_observations / lk_*)には書かない。**
  実験の47本が混ざると、ダッシュボードの言及率の母数が曜日によって跳ねる。
- Gemini を先に回す。Claude の47本は時間がかかるので、後ろに置いても
  Gemini の枠の日付(太平洋時間)には影響しない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_llm
import experiment
import sheets_writer
from settings import (DATA_RAW_EXPERIMENT_DIR, SWEEP_COOLDOWN_SECONDS, WEEKDAY_LABELS,
                      experiment_plan, gemini_requests_on)

MODEL_ORDER = ("gemini", "claude")


def _job_summary(lines: List[str]) -> None:
    print("\n".join(lines))
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def retry_within_budget(records: List[Dict[str, Any]], by_id: Dict[str, Dict[str, Any]],
                        out_dir, budget: int,
                        cooldown: float = SWEEP_COOLDOWN_SECONDS) -> int:
    """失敗した観測を、その日の Gemini 枠の余り(``budget``)の範囲でだけ取り直す。

    週2回の配分では毎日の余りが1〜2本しかなく、collect_llm 既定のリトライ
    (1観測で最大3回追加 + 掃き直し)をそのまま使うと実験が枠を超えさせる。
    ここでは1本につき1回、余りが尽きたら止める。使った回数を返す。
    """
    targets = [r for r in records if r.get("error")
               and not collect_llm.is_permanent(Exception(r["error"]))
               and not collect_llm.is_daily_quota(Exception(r["error"]))]
    if not targets:
        return 0
    if budget <= 0:
        print(f"[info] 実験Gemini: 失敗{len(targets)}件。枠の余りが無いため取り直さない")
        return 0
    print(f"[info] 実験Gemini: 失敗{len(targets)}件のうち最大{budget}件を"
          f"{cooldown:.0f}秒後に1回ずつ取り直します")
    time.sleep(cooldown)
    used = 0
    for record in targets:
        if used >= budget:
            break
        used += 1
        collect_llm._attempt(record, by_id[record["prompt_id"]]["text"], attempts=1)
        collect_llm._save(record, out_dir)
        if record.get("error") and collect_llm.is_daily_quota(Exception(record["error"])):
            break
    return used


def observe(date: str, plan: Dict[str, List[Dict[str, Any]]], out_dir,
            failures: List[str],
            resolver: Optional[experiment.Resolver] = None,
            cooldown: float = SWEEP_COOLDOWN_SECONDS) -> List[Dict[str, Any]]:
    """計画どおりに観測し、判定列を足したレコードを返す(raw にも書き直す)。"""
    records: List[Dict[str, Any]] = []
    for model in MODEL_ORDER:
        prompts = plan.get(model) or []
        if not prompts:
            continue
        by_id = {p["id"]: p for p in prompts}
        if model == "gemini":
            # まず1本1回ずつ。リトライはその日の余りの範囲だけ。
            got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir,
                                      models=[model], attempts=1, sweep=False)
            retry_within_budget(got, by_id, out_dir,
                                gemini_requests_on(date)["spare"], cooldown)
        else:
            got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir, models=[model])
        if len(got) < len(prompts):
            # 無効・鍵なしのモデルは collect が黙って飛ばす。実験では計画した
            # 観測が丸ごと消えるので、ここで失敗として積む。
            failures.append(f"{model}: 計画{len(prompts)}本に対して観測{len(got)}件"
                            "(モデルが無効か API キーが無い)")
        for record in got:
            record.update(experiment.evaluate(record, by_id[record["prompt_id"]], resolver))
            collect_llm._save(record, out_dir)
        records += got
    return records


def summary_lines(date: str, plan: Dict[str, List[Dict[str, Any]]],
                  records: List[Dict[str, Any]]) -> List[str]:
    budget = gemini_requests_on(date)
    weekday = WEEKDAY_LABELS[dt.date.fromisoformat(date).weekday()]
    lines = [
        f"## LLMO experiment — {date}({weekday})", "",
        "- 計画: " + (" / ".join(f"{m} {len(plan[m])}本" for m in MODEL_ORDER if m in plan)
                     or "観測なし"),
        f"- Gemini リクエスト見積もり: 日次{budget['daily']} + 月次{budget['monthly']}"
        f" + 実験{budget['experiment']} = {budget['total']} / 上限{budget['limit']}"
        f"(余り{budget['spare']}本。実験 Gemini の取り直しはこの範囲だけ)",
    ]
    if budget["over"]:
        lines.append("- ⚠️ 1日の枠を超える見込み。曜日割り(settings)を見直すこと")
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
    ap.add_argument("--date", help="観測日 YYYY-MM-DD(既定: 当日JST)。曜日で計画が決まる")
    ap.add_argument("--no-sheets", action="store_true", help="シートに書かない")
    ap.add_argument("--dry-run", action="store_true",
                    help="観測せず、その日の計画と Gemini の見積もりだけ表示する")
    args = ap.parse_args()

    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    plan = experiment_plan(date)
    failures: List[str] = []

    if args.dry_run or not plan:
        lines = summary_lines(date, plan, [])
        if not plan:
            lines.append("- この曜日は実験の観測日ではありません")
        _job_summary(lines)
        return

    out_dir = DATA_RAW_EXPERIMENT_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    try:
        records = observe(date, plan, out_dir, failures)
    except Exception as exc:  # noqa: BLE001 - 取れた分はこのあと保存する
        failures.append(f"observe: {exc}")

    missing = collect_llm.missing_observations(records)
    if missing:
        failures.append(f"collect_llm(欠測 {len(missing)}件): {', '.join(missing)}")

    lines = summary_lines(date, plan, records)
    if args.no_sheets:
        lines.append("- Sheets: skipped (--no-sheets)")
    elif records:
        try:
            sheets_writer.write_experiment(records)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"write_experiment: {exc}")

    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    else:
        lines += ["", "All phases completed ✅"]
    _job_summary(lines)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
