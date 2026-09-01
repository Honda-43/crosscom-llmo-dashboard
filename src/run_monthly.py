"""run_monthly.py — 月次観測のオーケストレータ(Phase 3 §2).

順序:
  collect_llm(月次プロンプト) -> extract -> monthly_observations -> Slack

日次(run_daily)との関係:

- **収集・抽出のコードは共有する。** collect_llm はリトライ・掃き直し・
  欠測の数え方を持っており、月次のためにそれを書き写すと片方だけ直る
  バグの温床になる。プロンプト集合と保存先だけを引数で差し替える。
- **保存先は分ける。** monthly_observations は llm_observations とは別タブで、
  回答全文も data/raw/monthly/ に置く。混ぜると言及率・言及シェアの母数が
  月に一度だけ跳ね、日次指標の時系列が読めなくなる(§2)。
- **daily_summary にも書かない。** 月次は日次指標の入力ではない。

実行数の制約(§冒頭):
Gemini 無料枠は1日20リクエスト/モデル。月次実行日は日次7本 + 月次12本 = 19本。
active な月次プロンプトを13本以上にすると枠を超えるため、
tests/test_monthly.py がその上限を検査している。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any, Callable, Dict, List

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_llm
import extract
import kbf_compare
import retired_urls
import notify_slack
import sheets_writer
from settings import DATA_RAW_MONTHLY_DIR, load_monthly_prompts

# 日次観測の本数。月次と足して Gemini の1日の枠に収まるかを見るのに使う。
DAILY_PROMPT_COUNT = 7
# Gemini 無料枠(GenerateRequestsPerDayPerProjectPerModel-FreeTier)
GEMINI_DAILY_REQUEST_LIMIT = 20


def _job_summary(lines: List[str]) -> None:
    print("\n".join(lines))
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def _run(name: str, fn: Callable[[], Any], failures: List[str]) -> Any:
    try:
        result = fn()
        print(f"[phase-ok] {name}")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[phase-fail] {name}: {exc}")
        failures.append(f"{name}: {exc}")
        return None


def request_budget(active_count: int) -> Dict[str, int]:
    """月次実行日の Gemini リクエスト数の見積もり。"""
    total = DAILY_PROMPT_COUNT + active_count
    return {
        "daily": DAILY_PROMPT_COUNT,
        "monthly": active_count,
        "total": total,
        "limit": GEMINI_DAILY_REQUEST_LIMIT,
        "over": total > GEMINI_DAILY_REQUEST_LIMIT,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Monthly LLMO observation (Phase 3)")
    ap.add_argument("--date", help="観測日 YYYY-MM-DD(既定: 当日JST)")
    ap.add_argument("--no-slack", action="store_true", help="投稿せず本文を表示する")
    ap.add_argument("--no-sheets", action="store_true",
                    help="シートに書かない(手元での確認用)")
    args = ap.parse_args()

    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    month = date[:7]

    prompts = load_monthly_prompts()
    budget = request_budget(len(prompts))
    failures: List[str] = []
    lines: List[str] = [f"## LLMO monthly observation — {month}", ""]
    lines.append(
        f"- Gemini リクエスト見積もり: 日次{budget['daily']} + 月次{budget['monthly']}"
        f" = {budget['total']} / 上限{budget['limit']}"
    )
    if budget["over"]:
        # 止めはしない。枠を超えるのは設計の問題で、当日の実行を諦める理由には
        # ならない(超えた分は 429 として欠測に記録される)。
        lines.append("- ⚠️ 1日の枠を超える見込み。プロンプトを減らすか実行日を分けること")
        print("[warn] active な月次プロンプトが多く、Geminiの1日の枠を超える見込みです")

    # 1. 収集(日次と同じリトライ・掃き直し・欠測通知を使う)
    out_dir = DATA_RAW_MONTHLY_DIR / date
    records = _run(
        "collect_llm(monthly)",
        lambda: collect_llm.collect(date, prompts=prompts, out_dir=out_dir),
        failures,
    ) or []

    missing = collect_llm.missing_observations(records)
    if missing:
        failures.append(f"collect_llm(欠測 {len(missing)}件): {', '.join(missing)}")
        lines.append(f"- ⚠️ 観測の欠測 {len(missing)}件: {', '.join(missing)}")

    # 2. 抽出(§4スキーマは不変。比較の勝敗判定などの新項目は足さない)
    extractions = _run(
        "extract",
        lambda: [extract.extract_record(r) for r in records],
        failures,
    ) or []

    # 収集時のメタ(category / target_brand)は抽出結果に残らないので戻す。
    # シートの列と月次サマリの両方がこれを見る。
    meta = {(r["prompt_id"], r["model"]): r for r in records}
    for e in extractions:
        src = meta.get((e.get("prompt_id"), e.get("model")), {})
        e.setdefault("category", src.get("category", ""))
        e.setdefault("target_brand", src.get("target_brand", ""))

    # 3. 保存
    if args.no_sheets:
        lines.append("- Sheets: skipped (--no-sheets)")
    else:
        _run("write_monthly_observations",
             lambda: sheets_writer.write_monthly_observations(extractions), failures)

    # 3-2. 比較型のKBF別評価(lk_kbf_compare)。
    # 比較3本は自然文なので、毎月人が読み直さずに済むよう軸の占有だけを
    # 機械で拾う。優劣は入れない(月次サマリの「要目視」と揃える)。
    kbf_rows = _run(
        "kbf_compare",
        lambda: kbf_compare.rows_from_records(month, records, prompts),
        failures,
    ) or []
    if kbf_rows and not args.no_sheets:
        _run("write_kbf_compare",
             lambda: sheets_writer.write_kbf_compare(kbf_rows), failures)
    if kbf_rows:
        lines += [f"- 比較KBF: {len(kbf_rows)}行"] +                  [f"  - {s}" for s in kbf_compare.summary(kbf_rows)]

    # 3-3. 取り下げたURLの引用(A-011)。**月次でも数える。**
    # 日次は E-1 だけを見るが、fsdg.jp のように日次では一度も引用されず
    # 月次(M-4)で初めて出るURLがある。日次だけだと永久に0件と表示され、
    # 「引用が止まった」と読めてしまう。月次は12本すべてが自社を聞く面なので
    # プロンプトを絞らない。
    retired_rows = _run(
        "retired_url_citations(monthly)",
        lambda: retired_urls.event_rows(
            date, records, resolve=True,
            prompt_ids=retired_urls.ALL_PROMPTS,
            scope=retired_urls.SCOPE_MONTHLY),
        failures,
    ) or []
    if retired_rows and not args.no_sheets:
        _run("write_lk_events(monthly)",
             lambda: sheets_writer.write_looker_tabs({"lk_events": retired_rows}),
             failures)
    if records:
        lines.append("- " + retired_urls.summary_line(
            date, records, resolve=True, prompt_ids=retired_urls.ALL_PROMPTS))

    # 4. 配信
    if args.no_slack:
        print(notify_slack.build_monthly_message(month, extractions, prompts))
    else:
        _run("notify_monthly",
             lambda: notify_slack.notify_monthly(month, extractions, prompts),
             failures)

    lines += [
        f"- 観測: {len(prompts)}本 × モデル = {len(records)}レコード",
        f"- 抽出成功: {sum(1 for e in extractions if not e.get('error'))}/{len(extractions)}",
    ]
    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    else:
        lines += ["", "All phases completed ✅"]
    _job_summary(lines)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
