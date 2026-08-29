"""backfill_sov.py — regenerate sov_daily for the whole history.

``sov_daily`` is fully derived from ``llm_observations``: nothing in it is
observed data. So whenever the normalisation rules change (a new alias, a new
stop-list entry, a fix like the "100" fragment), the correct repair is to throw
the tab away and rebuild every day from the observations that are still stored.

Usage (from ``src/``)::

    python backfill_sov.py --dry-run     # print what would be written
    python backfill_sov.py               # rewrite the whole sov_daily tab
    python backfill_sov.py --since 2026-08-01

``--dry-run`` never touches the spreadsheet. Without it the tab is **replaced**,
not merged: rows for entities that no longer exist after a normalisation change
(the stale "100" row) have to disappear, and an upsert alone cannot delete them.
Days outside the selected range keep their existing rows (they are read back and
rewritten unchanged), so a narrowed ``--since`` never silently drops history.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

import analyze_sov
import sheets_writer
from analyze_diff import parse_bool, split_list
from normalize import normalize_entity, resolve_entity


def _as_extraction(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a stored ``llm_observations`` row back to an extraction record.

    Only the fields analyze_sov reads are reconstructed. A row whose ``mention``
    is blank is an error/missing observation: it is marked as such so it stays
    out of ``observed_total`` exactly like it did on the original run.
    """
    mention = parse_bool(row.get("mention"))
    return {
        "date": str(row.get("date") or "").strip(),
        "prompt_id": str(row.get("prompt_id") or "").strip(),
        "pillar": str(row.get("pillar") or "").strip(),
        "model": str(row.get("model") or "").strip(),
        "mention": mention,
        "competitors_mentioned": split_list(row.get("competitors_mentioned")),
        "error": None if mention is not None else "no observation recorded",
    }


def build_rows(
    observations: Sequence[Dict[str, Any]],
    since: Optional[str] = None,
    until: Optional[str] = None,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Recompute every sov_daily row from stored observations, date by date."""
    by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in observations:
        record = _as_extraction(row)
        date = record["date"]
        if not date:
            continue
        if since and date < since:
            continue
        if until and date > until:
            continue
        by_date[date].append(record)

    rows: List[Dict[str, Any]] = []
    for date in sorted(by_date):
        rows.extend(analyze_sov.analyze(by_date[date], date, verbose=verbose))
    return rows


def excluded_report(observations: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Count the raw competitor values that the stop list / junk guard dropped.

    The whole point of the stop list is that it removes rows silently. Printing
    what it removed is how a wrong entry gets noticed — if a real competitor
    shows up here, it belongs in entity_aliases.yaml, not in the stop list.
    """
    dropped: Dict[str, int] = defaultdict(int)
    for row in observations:
        for raw in split_list(row.get("competitors_mentioned")):
            if resolve_entity(raw) is None:
                dropped[normalize_entity(raw) or raw.strip()] += 1
    return dict(dropped)


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild sov_daily from llm_observations")
    ap.add_argument("--since", help="earliest date to rebuild (YYYY-MM-DD)")
    ap.add_argument("--until", help="latest date to rebuild (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the result without writing to Sheets")
    args = ap.parse_args()

    observations = sheets_writer.read_llm_observations()
    if not observations:
        print("[warn] llm_observations is empty — nothing to backfill")
        return

    rows = build_rows(observations, args.since, args.until)
    dates = sorted({r["date"] for r in rows})
    print(
        f"[ok] rebuilt {len(rows)} sov_daily rows over {len(dates)} days"
        + (f" ({dates[0]} .. {dates[-1]})" if dates else "")
    )

    dropped = excluded_report(observations)
    if dropped:
        total = sum(dropped.values())
        print(f"[info] excluded {total} non-company values (stop list / junk guard):")
        for value, count in sorted(dropped.items(), key=lambda kv: -kv[1]):
            print(f"        {count:4d}  {value}")
        print("[info] a real competitor in this list belongs in entity_aliases.yaml")

    if args.dry_run:
        for row in rows:
            print(row)
        print("[dry-run] nothing written")
        return

    if args.since or args.until:
        # Keep days outside the requested window exactly as they are.
        kept = [
            r for r in sheets_writer.read_sov_daily()
            if not ((not args.since or r.get("date", "") >= args.since)
                    and (not args.until or r.get("date", "") <= args.until))
        ]
        print(f"[ok] preserving {len(kept)} rows outside the rebuilt range")
        rows = sorted(kept + rows, key=lambda r: (r.get("date", ""), r.get("pillar", "")))

    sheets_writer.rewrite_sov_daily(rows)


if __name__ == "__main__":
    main()
