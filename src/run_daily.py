"""run_daily.py — daily pipeline orchestrator (§8 + Phase 1 §1).

Order:
  collect_llm -> extract -> analyze_sov -> analyze_diff
  -> collect_ga4 -> collect_gsc -> build_summary -> Sheets writes -> notify_slack

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

import analyze_diff
import analyze_sov
import board_daily
import citation_gap
import collect_ga4
import collect_gsc
import collect_llm
import extract
import looker_tabs
import notify_slack
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

    # LLM observation -> extraction
    records = _run("collect_llm", lambda: collect_llm.collect(date), failures) or []
    extractions = _run(
        "extract",
        lambda: [extract.extract_record(r) for r in records],
        failures,
    ) or []

    # Analysis phases (Phase 1 §2 / §3). analyze_diff compares today's
    # extractions against the previous observation day still stored in Sheets,
    # so it must run *before* today's rows are written.
    #
    # The stored observations are read once here and shared with analyze_diff and
    # the Slack summary (which needs yesterday's rate and the negative streak),
    # instead of each of them reading the tab again (§8 API budget).
    observations = _run(
        "read_llm_observations", lambda: sheets_writer.read_llm_observations(), failures
    ) or []
    sov_rows = _run("analyze_sov", lambda: analyze_sov.analyze(extractions, date), failures) or []
    changes = _run(
        "analyze_diff",
        lambda: analyze_diff.analyze(extractions, date, previous_rows=observations),
        failures,
    ) or []

    # GA4 / GSC (independent of the LLM observation)
    ga4_rows = _run("collect_ga4", lambda: collect_ga4.collect(), failures) or []
    gsc_rows = _run("collect_gsc", lambda: collect_gsc.collect(), failures) or []

    # Build summary row
    summary = _run(
        "build_summary",
        lambda: sheets_writer.build_summary(extractions, ga4_rows, gsc_rows, date),
        failures,
    )

    # Write to Sheets (tabs 1, 2, 3, 5 + sov_daily / changes)
    _run("write_llm_observations", lambda: sheets_writer.write_llm_observations(extractions), failures)
    _run("write_sov_daily", lambda: sheets_writer.write_sov_daily(sov_rows), failures)
    _run("write_changes", lambda: sheets_writer.write_changes(changes), failures)
    _run("write_ga4", lambda: sheets_writer.write_ga4(ga4_rows), failures)
    _run("write_gsc", lambda: sheets_writer.write_gsc(gsc_rows), failures)
    if summary is not None:
        _run("write_daily_summary", lambda: sheets_writer.write_daily_summary(summary), failures)

    # ------------------------------------------------------------------
    # Looker Studio 用の表示タブ(Phase 6 §1・§2)
    # ------------------------------------------------------------------
    # 当日分はまだシートに無いので、読み込んだ履歴に足してから集計する。
    # 言及率と言及シェアの履歴は llm_observations から同じ式で復元できるので、
    # daily_summary / sov_daily は読み直さない(§8 のAPI予算)。
    def _merge(stored: List[Dict[str, Any]], fresh: List[Dict[str, Any]],
               keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
        """当日分で履歴を上書きする。

        同じ日を再実行すると読み込んだ履歴にも当日の行が含まれる。
        単純に足すと観測が二重になり、「7日中12日言及」のような行が出る。
        """
        index = {tuple(str(r.get(k, "")) for k in keys): r for r in stored}
        for row in fresh:
            index[tuple(str(row.get(k, "")) for k in keys)] = row
        return list(index.values())

    history = _merge(list(observations),
                     [sheets_writer._llm_row(r) for r in extractions],
                     ("date", "prompt_id", "model"))
    summary_history = looker_tabs.summary_rows_from_observations(history)
    sov_history = looker_tabs.sov_rows_from_observations(history)

    # 週計を出すには履歴が要る(collect_ga4/gsc は当日分しか返さない)。
    # action_log は lk_actions の元になるので読む。この3つだけが追加の読み取り。
    ga4_history = _run("read_ga4", lambda: sheets_writer.read_ga4(), failures) or []
    gsc_history = _run("read_gsc", lambda: sheets_writer.read_gsc(), failures) or []
    action_rows = _run(
        "read_action_log", lambda: sheets_writer.read_action_log(), failures) or []

    ga4_history = _merge(ga4_history, ga4_rows, ("date", "source", "landing_page"))
    gsc_history = _merge(gsc_history, gsc_rows, ("date", "query"))

    # 引用元の3分類は data/raw のローカル読みだけで出せる(Sheets を使わない)。
    citation_rows = _run(
        "citation_rows",
        lambda: citation_gap.build_rows(
            date,
            citation_gap.load_raw_observations(
                since=looker_tabs.window_of(date, looker_tabs.LOOKBACK_DAYS)[0],
                until=date),
            history,
        ),
        failures,
    ) or []

    contexts = _run(
        "verdict_contexts",
        lambda: looker_tabs.face_contexts(
            date, observations=history, summary_rows=summary_history,
            sov_rows=sov_history, action_rows=action_rows,
            ga4_rows=ga4_history, gsc_rows=gsc_history,
            citation_rows=citation_rows,
        ),
        failures,
    ) or {}

    _run(
        "write_board_daily",
        lambda: sheets_writer.write_board_daily(dict(
            board_daily.build_row(
                date,
                summary_rows=summary_history,
                observations=history,
                sov_rows=sov_history, changes=changes,
                ga4_rows=ga4_history, gsc_rows=gsc_history,
            ),
            verdict_r1=looker_tabs.verdict_for_face(contexts, "R1"),
        )),
        failures,
    )

    looker_payload = _run(
        "build_looker_tabs",
        lambda: looker_tabs.build_all(
            date, observations=history, summary_rows=summary_history,
            sov_rows=sov_history, changes=changes, action_rows=action_rows,
            ga4_rows=ga4_history, gsc_rows=gsc_history,
            citation_rows=citation_rows, contexts=contexts,
            raw_records=citation_gap.load_raw_observations(
                since=looker_tabs.window_of(date, looker_tabs.ANSWER_DAYS)[0],
                until=date),
        ),
        failures,
    ) or {}
    if looker_payload:
        _run("write_looker_tabs",
             lambda: sheets_writer.write_looker_tabs(looker_payload), failures)

    # Slack alert last, so it can report failures from every preceding phase.
    notified = _run(
        "notify_slack",
        lambda: notify_slack.notify(
            date, extractions, changes, list(failures),
            sov_rows=sov_rows, observations=observations,
        ),
        failures,
    )

    # Counts for the job summary
    ok_obs = sum(1 for r in extractions if not r.get("error"))
    err_obs = sum(1 for r in extractions if r.get("error"))
    summary_lines += [
        f"- LLM observations: {ok_obs} ok / {err_obs} error (total {len(extractions)})",
        f"- GA4 AI-referral rows: {len(ga4_rows)}",
        f"- GSC branded-query rows: {len(gsc_rows)}",
        f"- SoV rows: {len(sov_rows)}",
        f"- Detected changes: {len(changes)}",
        f"- Slack alert: {'sent' if notified else 'none'}",
    ]
    if summary:
        summary_lines += [
            f"- mention_rate_all: {summary.get('mention_rate_all')}",
            f"- negative_flag_count: {summary.get('negative_flag_count')}",
        ]
    if looker_payload:
        summary_lines += ["", "### Looker 用タブ"]
        summary_lines += [f"- {tab}: {len(rows)} rows"
                          for tab, rows in sorted(looker_payload.items())]
    if failures:
        summary_lines += ["", "### ⚠️ Failed phases"]
        summary_lines += [f"- {f}" for f in failures]
    else:
        summary_lines += ["", "All phases completed ✅"]

    _job_summary(summary_lines)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
