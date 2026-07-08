"""run_daily.py — daily pipeline orchestrator (§8).

Order (§8):
  1. collect_llm -> extract -> sheets(tabs 1 & 5)
  2. collect_ga4 -> tab 2
  3. collect_gsc -> tab 3

Every phase is isolated: a failure in one phase is recorded and reported in the
GitHub job summary, but the remaining phases still run. Raw-file commit/push is
handled by the workflow (§8 step 4). The process exits non-zero if any phase
failed so the run is visibly red, while the workflow's commit step uses
``if: always()`` to still persist data/raw.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any, Callable, Dict, List, Tuple

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing (e.g. bare Windows) — JST has no DST, so a
    # fixed +09:00 offset is exactly Asia/Tokyo.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_ga4
import collect_gsc
import collect_llm
import extract
import sheets_writer


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
    except Exception as exc:  # noqa: BLE001 - isolate each phase
        print(f"[phase-fail] {name}: {exc}")
        failures.append(f"{name}: {exc}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily LLMO pipeline")
    ap.add_argument("--date", help="YYYY-MM-DD for LLM observations (default: today JST)")
    args = ap.parse_args()
    # Timezone-aware, Asia/Tokyo-based date so the daily run is keyed to the
    # Japan business day regardless of the runner's clock (GitHub Actions is UTC).
    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")

    failures: List[str] = []
    summary_lines: List[str] = [f"## LLMO daily pipeline — {date}", ""]

    # Phase 1: LLM observation -> extraction
    records = _run("collect_llm", lambda: collect_llm.collect(date), failures) or []
    extractions = _run(
        "extract",
        lambda: [extract.extract_record(r) for r in records],
        failures,
    ) or []

    # Phase 2 & 3: GA4 / GSC (independent of LLM)
    ga4_rows = _run("collect_ga4", lambda: collect_ga4.collect(), failures) or []
    gsc_rows = _run("collect_gsc", lambda: collect_gsc.collect(), failures) or []

    # Build summary row
    summary = _run(
        "build_summary",
        lambda: sheets_writer.build_summary(extractions, ga4_rows, gsc_rows, date),
        failures,
    )

    # Write to Sheets (tabs 1, 2, 3, 5)
    _run("write_llm_observations", lambda: sheets_writer.write_llm_observations(extractions), failures)
    _run("write_ga4", lambda: sheets_writer.write_ga4(ga4_rows), failures)
    _run("write_gsc", lambda: sheets_writer.write_gsc(gsc_rows), failures)
    if summary is not None:
        _run("write_daily_summary", lambda: sheets_writer.write_daily_summary(summary), failures)

    # Counts for the job summary
    ok_obs = sum(1 for r in extractions if not r.get("error"))
    err_obs = sum(1 for r in extractions if r.get("error"))
    summary_lines += [
        f"- LLM observations: {ok_obs} ok / {err_obs} error (total {len(extractions)})",
        f"- GA4 AI-referral rows: {len(ga4_rows)}",
        f"- GSC branded-query rows: {len(gsc_rows)}",
    ]
    if summary:
        summary_lines += [
            f"- mention_rate_all: {summary.get('mention_rate_all')}",
            f"- negative_flag_count: {summary.get('negative_flag_count')}",
        ]
    if failures:
        summary_lines += ["", "### ⚠️ Failed phases"]
        summary_lines += [f"- {f}" for f in failures]
    else:
        summary_lines += ["", "All phases completed ✅"]

    _job_summary(summary_lines)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
