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
    TAB_CHANGES,
    TAB_GA4,
    TAB_GSC,
    TAB_LLM,
    TAB_SOV,
    TAB_ACTION_LOG,
    TAB_BOARD,
    TAB_CITATION_GAP,
    TAB_SUMMARY,
    TAB_WEEKLY,
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
# --- Phase 1 headers (approved — do not modify) ---------------------------
HEADERS_SOV = ["date", "pillar", "entity", "mention_count", "observed_total"]
HEADERS_CHANGES = [
    "date", "prompt_id", "model", "change_type", "before", "after", "detail",
]

# Idempotency key columns per tab (§7: date × prompt_id × model for tab1).
KEYS_LLM = ["date", "prompt_id", "model"]
KEYS_GA4 = ["date", "source", "landing_page"]
KEYS_GSC = ["date", "query"]
KEYS_AHREFS = ["date"]
KEYS_SUMMARY = ["date"]
KEYS_SOV = ["date", "pillar", "entity"]
# --- Phase 2 (approved — do not modify) -----------------------------------
HEADERS_WEEKLY = ["date", "stats_json", "report_md"]
KEYS_WEEKLY = ["date"]
# A single Google Sheets cell holds at most 50,000 characters. The full
# stats.json is committed to data/reports/ regardless, so the cell carries a
# pointer instead of silently losing the tail.
CELL_CHAR_LIMIT = 49_000

# --- Phase 5 headers ------------------------------------------------------
# 施策記録。状態はアプリからではなく本田さんがシート上で直接編集する。
HEADERS_ACTION_LOG = [
    "action_id", "優先度", "内容", "対象", "根拠rule_id", "状態",
    "提案日", "実施日", "判断期限",
]
KEYS_ACTION_LOG = ["action_id"]

# 引用元ドメインの3分類(自社 / 共通 / 自社不在)。週次で書き出す。
HEADERS_CITATION_GAP = ["date", "domain", "category", "cited_count", "prompts"]
KEYS_CITATION_GAP = ["date", "domain"]

# Looker Studio 用のフラットタブ。1日1行。
HEADERS_BOARD = [
    "date", "mention_rate_all_7d", "mention_rate_a_7d", "mention_rate_b_7d",
    "sov_rank", "sov_share", "negative_streak_days", "branded_clicks_wk",
    "ai_sessions_wk", "noise_flag", "material_events",
]
KEYS_BOARD = ["date"]
# ``detail`` is part of the key so several competitor_added rows for the same
# day/prompt/model (one per company) coexist while a re-run still overwrites.
KEYS_CHANGES = ["date", "prompt_id", "model", "change_type", "detail"]


# --------------------------------------------------------------------------
# Low-level Sheets helpers
# --------------------------------------------------------------------------
_SPREADSHEET = None


def _open_spreadsheet():
    """Open (once per process) the output spreadsheet.

    The handle is cached so the analysis phases added in Phase 1 reuse the same
    authorised gspread client instead of re-authenticating per write (§8).
    """
    global _SPREADSHEET
    if _SPREADSHEET is not None:
        return _SPREADSHEET

    import gspread

    if not SHEET_ID:
        raise RuntimeError("SHEET_ID is not set.")
    gc = gspread.authorize(google_credentials())
    _SPREADSHEET = gc.open_by_key(SHEET_ID)
    return _SPREADSHEET


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


def _read_tab(title: str) -> List[Dict[str, str]]:
    """Read a whole tab as header-keyed dicts (one API read, §8).

    A missing tab or a header-only tab yields ``[]`` so first-run callers do not
    need to special-case an empty spreadsheet.
    """
    import gspread

    ss = _open_spreadsheet()
    try:
        ws = ss.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        print(f"[warn] tab not found (treated as empty): {title}")
        return []

    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    rows: List[Dict[str, str]] = []
    for row in values[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        rows.append(dict(zip(header, padded)))
    return rows


def read_llm_observations() -> List[Dict[str, str]]:
    """All rows of the llm_observations tab (used by analyze_diff)."""
    return _read_tab(TAB_LLM)


def read_sov_daily() -> List[Dict[str, str]]:
    """All rows of the sov_daily tab (used by the backfill)."""
    return _read_tab(TAB_SOV)


def read_action_log() -> List[Dict[str, str]]:
    """施策記録。無ければ空(タブ未作成でもエラーにしない)。"""
    return _read_tab(TAB_ACTION_LOG)


def read_citation_gap() -> List[Dict[str, str]]:
    return _read_tab(TAB_CITATION_GAP)


def write_action_log(rows: List[Dict[str, Any]]) -> None:
    """action_id をキーに upsert。状態列は人が編集するため上書きに注意。"""
    if not rows:
        return
    _upsert(_open_spreadsheet(), TAB_ACTION_LOG, HEADERS_ACTION_LOG,
            KEYS_ACTION_LOG, rows)


def write_citation_gap(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    _upsert(_open_spreadsheet(), TAB_CITATION_GAP, HEADERS_CITATION_GAP,
            KEYS_CITATION_GAP, rows)


def write_board_daily(row: Dict[str, Any]) -> None:
    if not row:
        return
    _upsert(_open_spreadsheet(), TAB_BOARD, HEADERS_BOARD, KEYS_BOARD, [row])


def read_for_rules() -> Dict[str, List[Dict[str, str]]]:
    """Every tab the weekly rules engine needs, one read per tab (§2).

    Returned as ``{tab_name: rows}`` so rules_engine stays a pure function of
    its input and can be unit-tested without touching Sheets.
    """
    return {
        TAB_SUMMARY: _read_tab(TAB_SUMMARY),
        TAB_LLM: _read_tab(TAB_LLM),
        TAB_SOV: _read_tab(TAB_SOV),
        TAB_CHANGES: _read_tab(TAB_CHANGES),
        TAB_GA4: _read_tab(TAB_GA4),
        TAB_GSC: _read_tab(TAB_GSC),
    }


def rewrite_sov_daily(rows: List[Dict[str, Any]]) -> None:
    """**Replace** the whole sov_daily tab with ``rows``.

    sov_daily is derived data — every row is recomputable from
    llm_observations — so a full rewrite is the only way to retire rows that a
    normalisation change made obsolete. An upsert cannot delete. Used by
    backfill_sov.py; the daily pipeline keeps using the idempotent
    ``write_sov_daily``.
    """
    ss = _open_spreadsheet()
    ws = _ensure_worksheet(ss, TAB_SOV, HEADERS_SOV)
    values = [HEADERS_SOV] + [[_to_cell(r.get(h, "")) for h in HEADERS_SOV] for r in rows]
    ws.clear()
    ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    print(f"[ok] {TAB_SOV}: rewritten with {len(rows)} rows")


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


def write_sov_daily(rows: List[Dict[str, Any]]) -> None:
    """Upsert the sov_daily rows (Phase 1 §2), keyed by date × pillar × entity."""
    if not rows:
        return
    ss = _open_spreadsheet()
    _upsert(ss, TAB_SOV, HEADERS_SOV, KEYS_SOV, rows)


def write_changes(rows: List[Dict[str, Any]]) -> None:
    """Upsert the detected changes (Phase 1 §3). No changes = nothing written."""
    if not rows:
        return
    ss = _open_spreadsheet()
    _upsert(ss, TAB_CHANGES, HEADERS_CHANGES, KEYS_CHANGES, rows)


def write_weekly_report(date: str, stats: Dict[str, Any], report_md: str) -> None:
    """Upsert the weekly report row (Phase 2 §4), keyed by date."""
    stats_json = json.dumps(stats, ensure_ascii=False, sort_keys=True)
    if len(stats_json) > CELL_CHAR_LIMIT:
        stats_json = json.dumps(
            {
                "truncated": True,
                "reason": f"stats.json is {len(stats_json)} chars, over the cell limit",
                "full_copy": f"data/reports/{date}.json",
                "rules": stats.get("rules", []),
            },
            ensure_ascii=False,
        )
    ss = _open_spreadsheet()
    row = {"date": date, "stats_json": stats_json, "report_md": report_md}
    _upsert(ss, TAB_WEEKLY, HEADERS_WEEKLY, KEYS_WEEKLY, [row])


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
