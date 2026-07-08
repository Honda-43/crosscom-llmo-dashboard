"""run_weekly.py — weekly pipeline orchestrator (§8).

Runs the best-effort Ahrefs AI-Overview collection and writes tab 4. Ahrefs
failures (e.g. Lite-plan 402/403) never fail the run.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable, List

import collect_ahrefs
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
    except Exception as exc:  # noqa: BLE001
        print(f"[phase-fail] {name}: {exc}")
        failures.append(f"{name}: {exc}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly LLMO pipeline (Ahrefs)")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()

    failures: List[str] = []
    result = _run("collect_ahrefs", lambda: collect_ahrefs.collect(args.date), failures)
    _run("write_ahrefs", lambda: sheets_writer.write_ahrefs(result), failures)

    lines = ["## LLMO weekly pipeline (Ahrefs)", ""]
    if result:
        lines.append(f"- AI-Overview keywords: {result.get('aio_keyword_count')}")
    else:
        lines.append("- Ahrefs unavailable/skipped (best-effort).")
    if failures:
        lines += ["", "### ⚠️ Failed phases"] + [f"- {f}" for f in failures]
    _job_summary(lines)

    # Weekly Ahrefs is best-effort — never fail the run.
    sys.exit(0)


if __name__ == "__main__":
    main()
