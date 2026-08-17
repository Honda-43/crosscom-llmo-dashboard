"""run_weekly.py — weekly pipeline orchestrator (§8 + Phase 2 §5).

Order:
  collect_ahrefs -> rules_engine -> generate_insight -> weekly_reports -> Slack

Every phase is isolated: a failure is recorded and reported in the job summary
while the remaining phases still run. Two deliberate asymmetries:

- Ahrefs stays best-effort (Lite-plan 402/403 is normal) and never fails the run.
- The insight report degrades rather than disappearing: if the LLM call fails,
  generate_insight returns a numbers-only fallback and delivery continues (§5).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any, Callable, Dict, List

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_ahrefs
import generate_insight
import notify_slack
import rules_engine
import sheets_writer
from settings import DATA_REPORTS_DIR


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


def _save_stats(date: str, stats: Dict[str, Any]) -> str:
    """Persist stats.json for audit (§4). Committed by the workflow."""
    DATA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_REPORTS_DIR / f"{date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"[ok] wrote {path}")
    return str(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly LLMO pipeline")
    ap.add_argument("--date", help="week ending date YYYY-MM-DD (default: today JST)")
    ap.add_argument("--skip-ahrefs", action="store_true", help="weekly insight only")
    ap.add_argument("--no-slack", action="store_true", help="build the report but do not post")
    args = ap.parse_args()
    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")

    failures: List[str] = []
    lines: List[str] = [f"## LLMO weekly pipeline — {date}", ""]

    # 1. Ahrefs (best-effort, unchanged)
    if args.skip_ahrefs:
        ahrefs = None
        lines.append("- Ahrefs: skipped (--skip-ahrefs)")
    else:
        ahrefs = _run("collect_ahrefs", lambda: collect_ahrefs.collect(date), failures)
        _run("write_ahrefs", lambda: sheets_writer.write_ahrefs(ahrefs), failures)
        lines.append(
            f"- AI-Overview keywords: {ahrefs.get('aio_keyword_count')}" if ahrefs
            else "- Ahrefs unavailable/skipped (best-effort)."
        )

    # 2. Stage 1 — deterministic rules
    stats = _run("rules_engine", lambda: rules_engine.run(date), failures)

    report_md, source = None, None
    if stats is not None:
        _run("save_stats", lambda: _save_stats(date, stats), failures)

        # 3. Stage 2 — prose. generate() never raises; it degrades to numbers.
        result = _run("generate_insight", lambda: generate_insight.generate(stats), failures) or {}
        report_md = result.get("report_md") or generate_insight.fallback_report(stats)
        source = result.get("source", "fallback")
        if result.get("error"):
            failures.append(f"generate_insight(fallback used): {result['error']}")

        # 4. Persist and deliver
        _run(
            "write_weekly_report",
            lambda: sheets_writer.write_weekly_report(date, stats, report_md),
            failures,
        )
        if args.no_slack:
            print(report_md)
        else:
            _run(
                "notify_weekly",
                lambda: notify_slack.notify_weekly(date, report_md),
                failures,
            )

        lines += [
            f"- Fired rules: {', '.join(stats['fired_rules']) or 'none'}",
            f"- Insufficient data: {', '.join(stats['insufficient_rules']) or 'none'}",
            f"- Report source: {source}",
            f"- Report length: {len(report_md)} chars",
        ]

    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    else:
        lines += ["", "All phases completed ✅"]
    _job_summary(lines)

    # Exit contract: Ahrefs stays best-effort (Lite-plan 402/403 is expected and
    # must not turn the run red), but everything else is real. A report that fell
    # back to numbers *did* get delivered, yet the run is still marked failed —
    # a degraded weekly insight is something to notice, not to swallow.
    critical = [f for f in failures if not f.startswith(("collect_ahrefs", "write_ahrefs"))]
    sys.exit(1 if critical or stats is None or report_md is None else 0)


if __name__ == "__main__":
    main()
