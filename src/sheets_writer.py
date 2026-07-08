"""sheets_writer.py — Google Sheets long-format writer (§7).

Auto-creates the five approved tabs and appends daily rows in long format with
idempotent upsert (re-running the same day overwrites rather than duplicates).

The tab names and column headers are approved (§7) and must not change.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from settings import (
    SHEET_ID,
    TAB_AHREFS,
    TAB_GA4,
    TAB_GSC,
    TAB_LLM,
    TAB_SUMMARY,
    google_credentials,
)

# --- Approved headers (§7) — do not modify --------------------------------
HEADERS_LLM = [
    "date", "prompt_id", "pillar", "model", "mention", "mention_type", "rank",
    "kbf_tags", "negative_or_outdated", "negative_detail", "cited_crosscom_urls",
    "competitors_mentioned", "raw_file",
]
HEADERS_GA4 = ["date", "source", "landing_page", "sessions", "key_events"]
HEADERS_GSC = ["date", "query", "clicks", "impressions"]
HEADERS_AHREFS = ["date", "aio_keyword_count", "keywords_json"]
HEADERS_SUMMARY = [
    "date", "mention_rate_all", "mention_rate_pillar_a", "mention_rate_pillar_b",
    "negative_flag_count", "ai_sessions", "branded_clicks",
]

# Idempotency key columns per tab (§7: date × prompt_id × model for tab1).
KEYS_LLM = ["date", "prompt_id", "model"]
KEYS_GA4 = ["date", "source", "landing_page"]
KEYS_GSC = ["date", "query"]
KEYS_AHREFS = ["date"]
KEYS_SUMMARY = ["date"]


# --------------------------------------------------------------------------
# Low-level Sheets helpers
# --------------------------------------------------------------------------
def _open_spreadsheet():
    import gspread

    if not SHEET_ID:
        raise RuntimeError("SHEET_ID is not set.")
    gc = gspread.authorize(google_credentials())
    return gc.open_by_key(SHEET_ID)


def _ensure_worksheet(ss, title: str, headers: List[str]):
    """Return the worksheet, creating it (with header row) if absent, and
    ensuring the header row matches the approved schema."""
    import gspread

    try:
        ws = ss.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=1000, cols=max(len(headers), 10))
        ws.update(values=[headers], range_name="A1")
        return ws

    current = ws.row_values(1)
    if current != headers:
        ws.update(values=[headers], range_name="A1")
    return ws


def _to_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        # Lists of scalars -> comma joined; lists of dicts -> JSON.
        if all(not isinstance(v, (dict, list)) for v in value):
            return ", ".join(str(v) for v in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


def _upsert(ss, title: str, headers: List[str], key_cols: List[str],
            rows: List[Dict[str, Any]]) -> None:
    """Idempotent long-format upsert keyed by ``key_cols``."""
    if not rows:
        return
    ws = _ensure_worksheet(ss, title, headers)
    existing = ws.get_all_values()
    key_pos = [headers.index(k) for k in key_cols]

    index: Dict[tuple, int] = {}
    for rnum, row in enumerate(existing[1:], start=2):
        key = tuple(row[p] if p < len(row) else "" for p in key_pos)
        index[key] = rnum

    updates: List[Dict[str, Any]] = []
    appends: List[List[Any]] = []
    for d in rows:
        values = [_to_cell(d.get(h, "")) for h in headers]
        key = tuple(str(_to_cell(d.get(k, ""))) for k in key_cols)
        if key in index:
            rnum = index[key]
            updates.append({"range": f"A{rnum}", "values": [values]})
        else:
            appends.append(values)
            # Track so duplicates within this batch also upsert, not double-append.
            index[key] = -1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    if appends:
        ws.append_rows(appends, value_input_option="USER_ENTERED")
    print(f"[ok] {title}: {len(updates)} updated, {len(appends)} appended")


# --------------------------------------------------------------------------
# Row builders
# --------------------------------------------------------------------------
def _llm_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Map an extraction record (extract.py) to the llm_observations schema.
    Error/missing rows keep the columns but flag the failure in negative_detail."""
    if rec.get("error"):
        return {
            "date": rec.get("date"),
            "prompt_id": rec.get("prompt_id"),
            "pillar": rec.get("pillar"),
            "model": rec.get("model"),
            "mention": "",
            "mention_type": "",
            "rank": "",
            "kbf_tags": "",
            "negative_or_outdated": "",
            "negative_detail": f"[error] {rec['error']}",
            "cited_crosscom_urls": "",
            "competitors_mentioned": "",
            "raw_file": rec.get("raw_file", ""),
        }
    return {
        "date": rec.get("date"),
        "prompt_id": rec.get("prompt_id"),
        "pillar": rec.get("pillar"),
        "model": rec.get("model"),
        "mention": rec.get("mention"),
        "mention_type": rec.get("mention_type"),
        "rank": "" if rec.get("rank") is None else rec.get("rank"),
        "kbf_tags": rec.get("kbf_tags", []),
        "negative_or_outdated": rec.get("negative_or_outdated"),
        "negative_detail": rec.get("negative_detail"),
        "cited_crosscom_urls": rec.get("cited_crosscom_urls", []),
        "competitors_mentioned": rec.get("competitors_mentioned", []),
        "raw_file": rec.get("raw_file", ""),
    }


def build_summary(extractions: List[Dict[str, Any]], ga4_rows: List[Dict[str, Any]],
                  gsc_rows: List[Dict[str, Any]], date: str) -> Dict[str, Any]:
    """Compute the daily_summary row (§7).

    mention_rate denominators use the count of *valid* (non-error) observations,
    excluding the E-1 entity prompt — so they scale with the number of enabled
    models rather than any hardcoded value.
    """
    def rate(records: List[Dict[str, Any]]) -> Optional[float]:
        valid = [r for r in records if not r.get("error")]
        if not valid:
            return 0.0
        hits = sum(1 for r in valid if r.get("mention") is True)
        return round(hits / len(valid), 4)

    non_entity = [r for r in extractions if r.get("prompt_id") != "E-1"]
    pillar_a = [r for r in non_entity if r.get("pillar") == "A"]
    pillar_b = [r for r in non_entity if r.get("pillar") == "B"]

    negative_flag_count = sum(
        1 for r in extractions if not r.get("error") and r.get("negative_or_outdated") is True
    )
    ai_sessions = sum(int(r.get("sessions", 0) or 0) for r in ga4_rows)
    branded_clicks = sum(int(r.get("clicks", 0) or 0) for r in gsc_rows)

    return {
        "date": date,
        "mention_rate_all": rate(non_entity),
        "mention_rate_pillar_a": rate(pillar_a),
        "mention_rate_pillar_b": rate(pillar_b),
        "negative_flag_count": negative_flag_count,
        "ai_sessions": ai_sessions,
        "branded_clicks": branded_clicks,
    }


# --------------------------------------------------------------------------
# Public write functions
# --------------------------------------------------------------------------
def write_llm_observations(extractions: List[Dict[str, Any]]) -> None:
    ss = _open_spreadsheet()
    rows = [_llm_row(r) for r in extractions]
    _upsert(ss, TAB_LLM, HEADERS_LLM, KEYS_LLM, rows)


def write_daily_summary(summary: Dict[str, Any]) -> None:
    ss = _open_spreadsheet()
    _upsert(ss, TAB_SUMMARY, HEADERS_SUMMARY, KEYS_SUMMARY, [summary])


def write_ga4(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    ss = _open_spreadsheet()
    _upsert(ss, TAB_GA4, HEADERS_GA4, KEYS_GA4, rows)


def write_gsc(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    ss = _open_spreadsheet()
    _upsert(ss, TAB_GSC, HEADERS_GSC, KEYS_GSC, rows)


def write_ahrefs(result: Optional[Dict[str, Any]]) -> None:
    if not result:
        return
    ss = _open_spreadsheet()
    row = {
        "date": result["date"],
        "aio_keyword_count": result["aio_keyword_count"],
        "keywords_json": json.dumps(result.get("keywords", []), ensure_ascii=False),
    }
    _upsert(ss, TAB_AHREFS, HEADERS_AHREFS, KEYS_AHREFS, [row])
