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

import claude_budget
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

import action_log
import citation_gap
import collect_ahrefs
import generate_insight
import looker_tabs
import notify_slack
import rules_engine
import run_experiment
import sheets_writer
from settings import DATA_REPORTS_DIR


def _job_summary(lines: List[str]) -> None:
    print("\n".join(lines))
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def _step_outputs(delivered: bool, failures: List[str]) -> None:
    """ワークフローの失敗通知に渡す(所見が届いたか・落ちたフェーズ名)。

    フェーズ名だけを渡す。例外の文面は引用符や改行を含み得て、
    通知の JSON を壊すので載せない(文面は job summary にある)。
    """
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    names = [f.split(":", 1)[0] for f in failures]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"delivered={'true' if delivered else 'false'}\n")
        fh.write(f"failed_phases={', '.join(names)}\n")


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


def _refresh_scatter(date: str) -> int:
    """lk_scatter を週次で取り直す(Phase 6 §2)。

    競合ポジションは28日窓の集計なので、週の途中の日次追記だけでは
    引用元の入れ替わりが反映されきらない。週次でまとめて置き直す。
    """
    observations = sheets_writer.read_llm_observations()
    sov_rows = looker_tabs.sov_rows_from_observations(observations)
    rows = looker_tabs.scatter_rows(date, sov_rows, observations)
    sheets_writer.write_looker_tabs({"lk_scatter": rows})
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly LLMO pipeline")
    ap.add_argument("--date", help="week ending date YYYY-MM-DD (default: today JST)")
    ap.add_argument("--skip-ahrefs", action="store_true", help="weekly insight only")
    ap.add_argument("--no-slack", action="store_true", help="build the report but do not post")
    args = ap.parse_args()
    date = args.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    # Claude API の1日の呼び出し上限(2026-10-03)。回数は実際に呼ぶ日(JST の今日)で数える
    claude_budget.start('weekly')

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
    delivered = False
    if stats is not None:
        _run("save_stats", lambda: _save_stats(date, stats), failures)

        # 3. Stage 2 — prose. generate() never raises; it degrades to numbers.
        result = _run("generate_insight", lambda: generate_insight.generate(stats), failures) or {}
        report_md = result.get("report_md") or generate_insight.fallback_report(stats)
        source = result.get("source", "fallback")
        if result.get("error"):
            failures.append(f"generate_insight(fallback used): {result['error']}")
        # 記述ルール(Phase 7 §B)のうち機械で直せなかったもの。落とさないが、
        # 毎週見えるところに出す。見えないと直らない。
        for warning in result.get("warnings") or []:
            lines.append(f"- ⚠️ 所見の記述ルール: {warning}")
        for note in result.get("suppressed") or []:
            lines.append(f"- 実施済みのため再提案を差し替え: {note}")
        for note in result.get("frozen") or []:
            lines.append(f"- 実験の凍結対象のため差し替え: {note}")

        # 3-2. 引用元の3分類(Phase 5 §3-2)。data/raw を読むだけで
        # Sheets の追加読み取りはしない。
        gap = _run("citation_gap", lambda: citation_gap.analyze(date), failures)
        if gap:
            _run(
                "write_citation_gap",
                lambda: sheets_writer.write_citation_gap(gap["rows_for_sheet"]),
                failures,
            )
            # 引用元が変わると R6 の判定も競合の顔ぶれも変わるので、
            # citation_gap を更新した直後に lk_scatter を取り直す(Phase 6 §2)。
            _run("refresh_lk_scatter", lambda: _refresh_scatter(date), failures)

        # 3-3. 所見の推奨アクションを action_log に「提案中」で追記(§5)。
        # 同一内容+同一rule_idが未完了で存在すれば追記しない。
        proposals = _run(
            "propose_actions",
            lambda: action_log.sync_from_report(
                report_md, date, settled_lines=result.get("settled_lines") or []),
            failures,
        ) or []
        if proposals:
            _run("write_action_log",
                 lambda: sheets_writer.write_action_log(proposals), failures)
            lines.append(f"- 新規アクション提案: {len(proposals)}件")

        # 3-4. 同日実施の施策に「個別効果は分離不能」を記録する(測定設計 §4)。
        # 実施日は人がシートで入れるので、週次で読み直して足りない記録だけ書く。
        same_day = _run(
            "same_day_notes",
            lambda: action_log.same_day_notes(sheets_writer.read_action_log()),
            failures,
        ) or {}
        if same_day:
            _run("write_same_day_notes",
                 lambda: sheets_writer.write_action_log_column(same_day, "備考"), failures)
            lines.append(f"- 同日実施の記録: {', '.join(sorted(same_day))}")

        # 4. Persist and deliver
        _run(
            "write_weekly_report",
            lambda: sheets_writer.write_weekly_report(date, stats, report_md),
            failures,
        )
        if args.no_slack:
            print(report_md)
        else:
            delivered = bool(_run(
                "notify_weekly",
                lambda: notify_slack.notify_weekly(date, report_md),
                failures,
            ))

        lines += [
            f"- Fired rules: {', '.join(stats['fired_rules']) or 'none'}",
            f"- Insufficient data: {', '.join(stats['insufficient_rules']) or 'none'}",
            f"- Report source: {source}",
            f"- Report length: {len(report_md)} chars",
        ]

    # 実験の503欠測の監視(2026-09-18)。取り直しの枠が足りているかは
    # 1日では分からないので、週次で2週ぶんを並べて見る。警告どまりで
    # 週次の成否は変えない — 週次の失敗は週次の仕事の失敗を指すべきなので。
    watch = _run("unavailable_watch",
                 lambda: run_experiment.unavailable_watch_line(date), failures)
    if watch:
        lines.append(watch)
    weekly_count = _run("experiment_weekly_count",
                        lambda: run_experiment.weekly_count_line(date), failures)
    if weekly_count:
        lines.append(weekly_count)
    # 実験の Claude(2026-10-05 から月曜のみ・週46本。それまでは月・木で92本)
    claude_count = _run("experiment_weekly_claude_count",
                        lambda: run_experiment.weekly_claude_count_line(date), failures)
    if claude_count:
        lines.append(claude_count)

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
    _step_outputs(delivered, critical)
    sys.exit(1 if critical or stats is None or report_md is None else 0)


if __name__ == "__main__":
    main()
