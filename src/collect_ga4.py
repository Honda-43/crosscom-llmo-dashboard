"""collect_ga4.py — GA4 AI-referral traffic (§5, daily).

Pulls the previous day's sessions / key events broken down by source and
landing page, keeping only rows whose sessionSource contains one of the known
AI assistant hostnames.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional

from settings import AI_SOURCE_FRAGMENTS, GA4_PROPERTY_ID, google_credentials


def _yesterday_utc() -> str:
    return (dt.datetime.utcnow().date() - dt.timedelta(days=1)).strftime("%Y-%m-%d")


def collect(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return rows: {date, source, landing_page, sessions, key_events}."""
    date = date or _yesterday_utc()
    if not GA4_PROPERTY_ID:
        print("[warn] GA4_PROPERTY_ID not set — skipping GA4 collection.")
        return []

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    client = BetaAnalyticsDataClient(credentials=google_credentials())
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[DateRange(start_date=date, end_date=date)],
        dimensions=[
            Dimension(name="date"),
            Dimension(name="sessionSource"),
            Dimension(name="landingPagePlusQueryString"),
        ],
        metrics=[Metric(name="sessions"), Metric(name="keyEvents")],
    )
    response = client.run_report(request)

    rows: List[Dict[str, Any]] = []
    for row in response.rows:
        source = row.dimension_values[1].value or ""
        low = source.lower()
        if not any(frag in low for frag in AI_SOURCE_FRAGMENTS):
            continue
        rows.append(
            {
                "date": date,
                "source": source,
                "landing_page": row.dimension_values[2].value or "",
                "sessions": int(row.metric_values[0].value or 0),
                "key_events": int(float(row.metric_values[1].value or 0)),
            }
        )
    print(f"[ok] GA4 {date}: {len(rows)} AI-referral rows")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="GA4 AI-referral collector")
    ap.add_argument("--date", help="YYYY-MM-DD (default: yesterday UTC)")
    args = ap.parse_args()
    collect(args.date)


if __name__ == "__main__":
    main()
