"""data_source.py — read-only data access for the local dashboard (Phase 4 §1).

This module never writes. It opens its own gspread client rather than reusing
``src/sheets_writer`` so that no write path is reachable from the app at all,
and so the pipeline's module-level spreadsheet cache is left untouched.

Sheets reads are cached for 10 minutes (§1) and each tab is fetched exactly
once per refresh, so running the dashboard cannot eat into the daily job's API
quota (§3).

Credentials are optional by design (§3): without them the Sheets-backed pages
show guidance instead of an error, and the pages fed by ``data/raw`` keep
working.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from settings import (  # noqa: E402  - needs the sys.path line above
    DATA_RAW_DIR,
    DATA_REPORTS_DIR,
    GOOGLE_SCOPES,
    SELF_ENTITY,
    TAB_CHANGES,
    TAB_GA4,
    TAB_GSC,
    TAB_LLM,
    TAB_SOV,
    TAB_SUMMARY,
    TAB_WEEKLY,
)

CREDENTIALS_DIR = ROOT_DIR / "credentials"
SERVICE_ACCOUNT_FILE = CREDENTIALS_DIR / "service_account.json"
SPREADSHEET_ID_FILE = CREDENTIALS_DIR / "spreadsheet_id.txt"

CACHE_TTL_SECONDS = 600  # §1: 10 minutes

ALL_TABS = [TAB_SUMMARY, TAB_LLM, TAB_SOV, TAB_CHANGES, TAB_GA4, TAB_GSC, TAB_WEEKLY]

# Sample mode renders the UI without credentials so the layout can be reviewed
# (and the chart code exercised) before the service account is wired up.
# Every page shows a loud banner while it is on — see main.py.
SAMPLE_MODE_ENV = "LLMO_DASHBOARD_SAMPLE"


def sample_mode() -> bool:
    return os.getenv(SAMPLE_MODE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
def spreadsheet_id() -> str:
    """Spreadsheet id from the environment, or credentials/spreadsheet_id.txt."""
    env = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
    if env:
        return env
    if SPREADSHEET_ID_FILE.exists():
        return SPREADSHEET_ID_FILE.read_text(encoding="utf-8").strip()
    return ""


def credentials_status() -> Dict[str, Any]:
    """What is present, so pages can explain precisely what is missing."""
    return {
        "service_account": SERVICE_ACCOUNT_FILE.exists(),
        "spreadsheet_id": bool(spreadsheet_id()),
        "sample_mode": sample_mode(),
    }


def sheets_available() -> bool:
    if sample_mode():
        return True
    status = credentials_status()
    return status["service_account"] and status["spreadsheet_id"]


def missing_credentials_notice() -> None:
    """Guidance shown in place of Sheets content (§3) — never an exception."""
    status = credentials_status()
    st.info("**Google Sheets に接続していないため、このページは表示できません。**")
    lines = []
    if not status["service_account"]:
        lines.append(
            f"- サービスアカウントJSONが見つかりません → `credentials/service_account.json` に配置してください"
        )
    if not status["spreadsheet_id"]:
        lines.append(
            "- スプレッドシートIDが未設定です → 環境変数 `SHEETS_SPREADSHEET_ID` を設定するか、"
            "`credentials/spreadsheet_id.txt` にIDを1行で保存してください"
        )
    st.markdown("\n".join(lines))
    st.caption(
        "`credentials/` は .gitignore 済みでコミットされません。"
        "認証なしでも「P4 回答ビューア・差分」は data/raw だけで動作します。"
    )


# --------------------------------------------------------------------------
# Sheets (read-only, cached)
# --------------------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Google Sheets を読み込み中…")
def load_tabs() -> Dict[str, List[Dict[str, str]]]:
    """Every tab, one read each, header-keyed. Cached for 10 minutes (§1/§3)."""
    if sample_mode():
        from sample_data import sample_tabs

        return sample_tabs()

    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=GOOGLE_SCOPES
    )
    spreadsheet = gspread.authorize(creds).open_by_key(spreadsheet_id())

    tabs: Dict[str, List[Dict[str, str]]] = {}
    for title in ALL_TABS:
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            tabs[title] = []
            continue
        values = worksheet.get_all_values()
        if len(values) < 2:
            tabs[title] = []
            continue
        header = values[0]
        tabs[title] = [
            dict(zip(header, list(row) + [""] * (len(header) - len(row))))
            for row in values[1:]
        ]
    return tabs


def tab(name: str) -> List[Dict[str, str]]:
    """One tab's rows, or [] when unavailable."""
    try:
        return load_tabs().get(name, [])
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI, never raised
        st.error(f"Sheets の読み取りに失敗しました: {exc}")
        return []


# --------------------------------------------------------------------------
# Local files (always available)
# --------------------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_raw_index() -> List[Dict[str, Any]]:
    """Index of data/raw without loading every answer body."""
    entries = []
    if not DATA_RAW_DIR.exists():
        return entries
    for path in sorted(DATA_RAW_DIR.glob("*/*.json")):
        stem = path.stem
        prompt_id, _, model = stem.partition("_")
        entries.append({
            "date": path.parent.name,
            "prompt_id": prompt_id,
            "model": model,
            "path": str(path),
        })
    return entries


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_raw_answer(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_stats_reports() -> Dict[str, Dict[str, Any]]:
    """Weekly stats.json files keyed by date (data/reports/)."""
    reports: Dict[str, Dict[str, Any]] = {}
    if not DATA_REPORTS_DIR.exists():
        return reports
    for path in sorted(DATA_REPORTS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                reports[path.stem] = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def raw_data_span() -> Optional[tuple]:
    index = load_raw_index()
    if not index:
        return None
    dates = sorted({e["date"] for e in index})
    return dates[0], dates[-1]
