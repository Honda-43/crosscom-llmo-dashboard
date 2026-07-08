"""collect_ahrefs.py — AI Overview keyword count (§6, weekly, best-effort).

Queries Ahrefs API v3 ``site-explorer/organic-keywords`` for cross-com.jp and
counts keywords whose SERP features include an AI Overview. On the Lite plan
this endpoint may return 402/403; in that case we log a warning and return an
empty result rather than failing the pipeline.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional

from settings import AHREFS_API_KEY, AHREFS_TARGET


def _today_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d")


def collect(date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return {date, aio_keyword_count, keywords} or None if unavailable."""
    date = date or _today_utc()
    if not AHREFS_API_KEY:
        print("[warn] AHREFS_API_KEY not set — skipping Ahrefs collection.")
        return None

    import requests

    params = {
        "target": AHREFS_TARGET,
        "country": "jp",
        "select": "keyword,serp_features,volume,best_position",
        "mode": "subdomains",
        "limit": 1000,
    }
    headers = {
        "Authorization": f"Bearer {AHREFS_API_KEY}",
        "Accept": "application/json",
    }
    try:
        r = requests.get(
            "https://api.ahrefs.com/v3/site-explorer/organic-keywords",
            headers=headers,
            params=params,
            timeout=120,
        )
        if r.status_code in (401, 402, 403):
            print(
                f"[warn] Ahrefs returned {r.status_code} (Lite plan restriction) — "
                "skipping without failing the pipeline."
            )
            return None
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:  # noqa: BLE001 - best-effort, never crash pipeline
        print(f"[warn] Ahrefs request failed ({exc}) — skipping without failing.")
        return None

    keywords = payload.get("keywords") or payload.get("organic_keywords") or []
    aio_keywords: List[Dict[str, Any]] = []
    for kw in keywords:
        features = kw.get("serp_features") or []
        # serp_features may be a list of names or dicts depending on API shape.
        names = [
            (f.get("feature") if isinstance(f, dict) else f) for f in features
        ]
        joined = " ".join(str(n) for n in names).lower()
        if "ai_overview" in joined or "ai overview" in joined or "aio" in joined:
            aio_keywords.append(kw)

    result = {
        "date": date,
        "aio_keyword_count": len(aio_keywords),
        "keywords": aio_keywords,
    }
    print(f"[ok] Ahrefs {date}: {len(aio_keywords)} AI-Overview keywords")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Ahrefs AI-Overview keyword collector")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()
    collect(args.date)


if __name__ == "__main__":
    main()
