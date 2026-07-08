"""collect_gsc.py — Search Console branded queries (§5, daily).

Pulls Search Analytics for the date 3 days ago (GSC data-finalisation lag) and
keeps only branded queries, aggregating clicks / impressions.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional

from settings import BRANDED_QUERY_FRAGMENTS, GSC_SITE_URL, google_credentials


def _three_days_ago_utc() -> str:
    return (dt.datetime.utcnow().date() - dt.timedelta(days=3)).strftime("%Y-%m-%d")


def _is_branded(query: str) -> bool:
    low = query.lower()
    return any(frag.lower() in low for frag in BRANDED_QUERY_FRAGMENTS)


def collect(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return rows: {date, query, clicks, impressions}."""
    date = date or _three_days_ago_utc()
    if not GSC_SITE_URL:
        print("[warn] GSC_SITE_URL not set — skipping GSC collection.")
        return []

    from googleapiclient.discovery import build

    service = build("searchconsole", "v1", credentials=google_credentials())
    body = {
        "startDate": date,
        "endDate": date,
        "dimensions": ["query", "date"],
        "rowLimit": 25000,
    }
    response = (
        service.searchanalytics()
        .query(siteUrl=GSC_SITE_URL, body=body)
        .execute()
    )

    rows: List[Dict[str, Any]] = []
    for row in response.get("rows", []):
        query = row["keys"][0]
        if not _is_branded(query):
            continue
        rows.append(
            {
                "date": date,
                "query": query,
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
            }
        )
    print(f"[ok] GSC {date}: {len(rows)} branded-query rows")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="GSC branded-query collector")
    ap.add_argument("--date", help="YYYY-MM-DD (default: 3 days ago UTC)")
    args = ap.parse_args()
    collect(args.date)


if __name__ == "__main__":
    main()
