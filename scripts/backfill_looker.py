"""backfill_looker.py — lk_* を全履歴分まとめて生成する(Phase 6 §2).

日次パイプラインは当日分しか書かないので、Looker を初めて組むときには
過去分の行が無い。ここでは保存済みの llm_observations から
lk_sov_trend / lk_negative / lk_verdicts を過去に遡って作る。

lk_sov_trend と lk_negative は観測だけで完全に復元できる。lk_verdicts は
その日に判定できた分だけを作る(施策の状態はシートの現在値しか残って
いないため、過去日の判定に出る「直近の施策」は現在の action_log から
見た値になる。何が起きていたかの再現ではなく、Looker の線を過去まで
伸ばすための行として扱う)。

使い方(リポジトリ直下から)::

    python scripts/backfill_looker.py --dry-run       # 書かずに件数だけ出す
    python scripts/backfill_looker.py                 # 全期間を書き込む
    python scripts/backfill_looker.py --since 2026-08-01
    python scripts/backfill_looker.py --tabs lk_sov_trend,lk_negative

``--dry-run`` はスプレッドシートに触らない。書き込みは日次と同じ冪等な
upsert なので、二度実行しても行は増えない。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import citation_gap  # noqa: E402  - needs the sys.path line above
import looker_tabs  # noqa: E402
import sheets_writer  # noqa: E402

BACKFILLABLE = ("lk_sov_trend", "lk_negative", "lk_verdicts")


def observation_dates(observations: Sequence[Dict[str, Any]],
                      since: Optional[str] = None,
                      until: Optional[str] = None) -> List[str]:
    days = {str(r.get("date") or "").strip() for r in observations}
    days.discard("")
    return sorted(d for d in days
                  if (not since or d >= since) and (not until or d <= until))


def build(observations: Sequence[Dict[str, Any]],
          action_rows: Sequence[Dict[str, Any]] = (),
          ga4_rows: Sequence[Dict[str, Any]] = (),
          gsc_rows: Sequence[Dict[str, Any]] = (),
          since: Optional[str] = None,
          until: Optional[str] = None,
          tabs: Sequence[str] = BACKFILLABLE) -> Dict[str, List[Dict[str, Any]]]:
    """全期間分の lk_* 行。日次と同じ関数を日付ごとに回すだけ。"""
    dates = observation_dates(observations, since, until)
    if not dates:
        return {tab: [] for tab in tabs}

    sov_rows = looker_tabs.sov_rows_from_observations(observations)
    summary_rows = looker_tabs.summary_rows_from_observations(observations)
    payload: Dict[str, List[Dict[str, Any]]] = {tab: [] for tab in tabs}

    if "lk_sov_trend" in payload:
        # 系列は最新日で決めて全期間に固定する。日ごとに選び直すと
        # 線が入れ替わり、推移として読めなくなる。
        entities = looker_tabs.trend_entities(sov_rows, dates[-1])
        payload["lk_sov_trend"] = looker_tabs.sov_trend_rows(
            dates[-1], sov_rows, entities=entities, dates=dates)

    if "lk_negative" in payload:
        payload["lk_negative"] = looker_tabs.negative_rows(
            dates[-1], observations, dates=dates)

    if "lk_verdicts" in payload:
        rows: List[Dict[str, Any]] = []
        for day in dates:
            citation_rows = citation_gap.build_rows(
                day,
                citation_gap.load_raw_observations(
                    since=looker_tabs.window_of(day, looker_tabs.LOOKBACK_DAYS)[0],
                    until=day),
                observations,
            )
            contexts = looker_tabs.face_contexts(
                day, observations=observations, summary_rows=summary_rows,
                sov_rows=sov_rows, action_rows=action_rows,
                ga4_rows=ga4_rows, gsc_rows=gsc_rows,
                citation_rows=citation_rows,
            )
            rows.extend(looker_tabs.verdict_rows(day, contexts))
        payload["lk_verdicts"] = rows

    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="lk_* を全履歴分生成する")
    ap.add_argument("--since", help="最古の日付 (YYYY-MM-DD)")
    ap.add_argument("--until", help="最新の日付 (YYYY-MM-DD)")
    ap.add_argument("--tabs", default=",".join(BACKFILLABLE),
                    help=f"対象タブをカンマ区切りで指定 (既定: {','.join(BACKFILLABLE)})")
    ap.add_argument("--dry-run", action="store_true",
                    help="書き込まず件数とサンプルだけ表示する")
    args = ap.parse_args()

    tabs = [t.strip() for t in args.tabs.split(",") if t.strip()]
    unknown = [t for t in tabs if t not in BACKFILLABLE]
    if unknown:
        raise SystemExit(f"バックフィルできないタブです: {', '.join(unknown)}")

    observations = sheets_writer.read_llm_observations()
    if not observations:
        print("[warn] llm_observations が空です — 生成するものがありません")
        return

    action_rows = sheets_writer.read_action_log() if "lk_verdicts" in tabs else []
    ga4_rows = sheets_writer.read_ga4() if "lk_verdicts" in tabs else []
    gsc_rows = sheets_writer.read_gsc() if "lk_verdicts" in tabs else []

    payload = build(observations, action_rows=action_rows, ga4_rows=ga4_rows,
                    gsc_rows=gsc_rows, since=args.since, until=args.until,
                    tabs=tabs)

    dates = observation_dates(observations, args.since, args.until)
    print(f"[ok] {len(dates)} 日分 "
          + (f"({dates[0]} .. {dates[-1]})" if dates else ""))
    for tab in tabs:
        rows = payload.get(tab) or []
        print(f"     {tab}: {len(rows)} rows")
        for row in rows[:3]:
            print(f"        {row}")

    if args.dry_run:
        print("[dry-run] 何も書き込んでいません")
        return

    sheets_writer.write_looker_tabs({t: payload[t] for t in tabs if payload.get(t)})


if __name__ == "__main__":
    main()
