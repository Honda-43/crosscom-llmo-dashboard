"""Central configuration for the LLMO monitoring pipeline.

All environment-driven configuration and constants live here so that the
collectors / writers stay thin. Model enable/disable is controlled here so a
model can be toggled without touching collector code (§3).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
PROMPTS_FILE = CONFIG_DIR / "prompts.yaml"
# Entity alias table (Phase 1 §2-1) — appended to during operation, no code change.
ENTITY_ALIASES_FILE = CONFIG_DIR / "entity_aliases.yaml"
# Generic phrases that are not company names and must not be counted.
ENTITY_STOPLIST_FILE = CONFIG_DIR / "entity_stoplist.yaml"
# Phase 2 — weekly insight engine
RULES_THRESHOLDS_FILE = CONFIG_DIR / "rules_thresholds.yaml"
LEGACY_PATHS_FILE = CONFIG_DIR / "legacy_paths.yaml"
PLAYBOOK_FILE = CONFIG_DIR / "playbook.md"
# Phase 5 — 判定欄のテンプレート(LLMを使わず決定的に文面を作る)
VERDICT_TEMPLATES_FILE = CONFIG_DIR / "verdict_templates.yaml"
DATA_REPORTS_DIR = ROOT_DIR / "data" / "reports"


# --------------------------------------------------------------------------
# YAML loading
# --------------------------------------------------------------------------
class DuplicateKeyError(ValueError):
    """A config file defines the same key twice."""


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys.

    Plain YAML silently keeps the *last* value, so a second
    ``ゼロワングロース:`` line further down the alias file would quietly
    override the first one and undo an edit with no error anywhere. These files
    are hand-maintained during operation, which is exactly the situation where
    that failure mode goes unnoticed — so it is made fatal instead.
    """


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise DuplicateKeyError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1} "
                f"of {key_node.start_mark.name}"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def load_yaml(path: Any) -> Any:
    """Load a config YAML, failing loudly on duplicate keys."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_StrictLoader)


# --------------------------------------------------------------------------
# Prompts (§2 — approved, do not modify the YAML content)
# --------------------------------------------------------------------------
def load_prompts() -> List[Dict[str, Any]]:
    """Load the approved observation prompts from config/prompts.yaml."""
    return load_yaml(PROMPTS_FILE)["prompts"]


# --------------------------------------------------------------------------
# Model configuration (§3)
# Initial state: chatgpt / gemini / claude enabled, perplexity disabled.
# Enable/disable is env-overridable so activating Perplexity later is a
# matter of setting a key + flipping the flag (no code change).
# --------------------------------------------------------------------------
def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


MODEL_CONFIG: Dict[str, Dict[str, Any]] = {
    "chatgpt": {
        # Disabled by default (same treatment as Perplexity). Register
        # OPENAI_API_KEY and set ENABLE_CHATGPT=true to activate — no code change.
        # A missing OPENAI_API_KEY never raises; the model is simply skipped.
        "enabled": _flag("ENABLE_CHATGPT", False),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "api_key_env": "OPENAI_API_KEY",
    },
    "gemini": {
        "enabled": _flag("ENABLE_GEMINI", True),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "api_key_env": "GEMINI_API_KEY",
    },
    "claude": {
        "enabled": _flag("ENABLE_CLAUDE", True),
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "perplexity": {
        # Disabled by default. Register PERPLEXITY_API_KEY and set
        # ENABLE_PERPLEXITY=true to activate — no code change required.
        "enabled": _flag("ENABLE_PERPLEXITY", False),
        "model": os.getenv("PERPLEXITY_MODEL", "sonar"),
        "api_key_env": "PERPLEXITY_API_KEY",
    },
}


def enabled_models() -> List[str]:
    """Ordered list of currently enabled model keys."""
    return [k for k, v in MODEL_CONFIG.items() if v["enabled"]]


# --------------------------------------------------------------------------
# Extraction model (§4) — cheapest current Anthropic model (Haiku class).
# --------------------------------------------------------------------------
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# --------------------------------------------------------------------------
# Weekly insight model (Phase 2 §3) — Sonnet class, one call per week.
# --------------------------------------------------------------------------
INSIGHT_MODEL = os.getenv("INSIGHT_MODEL", "claude-sonnet-5")
INSIGHT_MAX_CHARS = int(os.getenv("INSIGHT_MAX_CHARS", "2000"))

# 出力トークンの上限。INSIGHT_MAX_CHARS(本文の字数)とは別物で、こちらは
# モデルが1回の応答で使える枠。2026-08 まで 4096 に固定されていて、
# 3週続けて所見が文の途中で切れていた(セクション4・5が丸ごと欠落)。
# 日本語1文字が複数トークンになること、応答トークンが本文だけに使われるとは
# 限らないことを踏まえ、本文の想定量に対して十分な余裕を取る。
# 足りなければ generate_insight が1度だけ倍にして取り直す。
INSIGHT_MAX_TOKENS = int(os.getenv("INSIGHT_MAX_TOKENS", "16000"))

# Retry policy (§3): exponential backoff, max 3 attempts.
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
BACKOFF_BASE_SECONDS = float(os.getenv("BACKOFF_BASE_SECONDS", "2"))


# --------------------------------------------------------------------------
# Google / analytics configuration
# --------------------------------------------------------------------------
SHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID", "")
GA4_PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "")
# Search Console property, e.g. "https://cross-com.jp/" or "sc-domain:cross-com.jp"
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "sc-domain:cross-com.jp")

AHREFS_API_KEY = os.getenv("AHREFS_API_KEY", "")
AHREFS_TARGET = os.getenv("AHREFS_TARGET", "cross-com.jp")

# GA4 AI-referral source fragments (§5)
AI_SOURCE_FRAGMENTS = [
    "chatgpt.com",
    "chat.openai.com",
    "perplexity.ai",
    "gemini.google.com",
    "copilot.microsoft.com",
    "claude.ai",
    "bing.com/chat",
]

# GSC branded-query fragments (§5)
BRANDED_QUERY_FRAGMENTS = ["クロスコム", "crosscom", "cross-com", "cross com"]

# Brand surface forms treated as a self-mention (§4)
BRAND_ALIASES = ["クロスコム", "合同会社クロスコム", "cross-com", "Crosscom"]

# Canonical name of our own company in the SoV aggregation (Phase 1 §2).
SELF_ENTITY = "クロスコム"

# Slack Incoming Webhook (Phase 1 §4). Unset = alerts are skipped, never fatal.
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()

# Looker Studio dashboard. Shown as a link at the end of the daily alert;
# omitted entirely when unset.
LOOKER_STUDIO_URL = os.getenv("LOOKER_STUDIO_URL", "").strip()

# Google service-account scopes needed across Sheets / GA4 / GSC.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]


def google_credentials():
    """Build google.oauth2 service-account credentials.

    Accepts either GCP_SERVICE_ACCOUNT_JSON (raw JSON string, preferred for
    CI secrets) or GOOGLE_APPLICATION_CREDENTIALS (path to a JSON file).
    """
    from google.oauth2.service_account import Credentials

    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if path and Path(path).exists():
        return Credentials.from_service_account_file(path, scopes=GOOGLE_SCOPES)

    raise RuntimeError(
        "No Google credentials found. Set GCP_SERVICE_ACCOUNT_JSON "
        "(raw JSON) or GOOGLE_APPLICATION_CREDENTIALS (file path)."
    )


# --------------------------------------------------------------------------
# Sheet tab names (§7)
# --------------------------------------------------------------------------
TAB_LLM = "llm_observations"
TAB_GA4 = "ga4_ai_traffic"
TAB_GSC = "gsc_branded"
TAB_AHREFS = "ahrefs_aio"
TAB_SUMMARY = "daily_summary"
# Phase 1 tabs (approved — do not change the schema)
TAB_SOV = "sov_daily"
TAB_CHANGES = "changes"
# Phase 2
TAB_WEEKLY = "weekly_reports"
# Phase 5
TAB_ACTION_LOG = "action_log"
TAB_CITATION_GAP = "citation_gap"
TAB_BOARD = "board_daily"
# Phase 6 — Looker Studio 専用の表示タブ。接頭辞 lk_ で「計算済み・表示用」を
# 明示する。中身はすべて他タブから導出できるので、消しても作り直せる。
TAB_LK_VERDICTS = "lk_verdicts"
TAB_LK_HEATGRID = "lk_heatgrid"
TAB_LK_SCATTER = "lk_scatter"
TAB_LK_SOV_TREND = "lk_sov_trend"
TAB_LK_NEGATIVE = "lk_negative"
TAB_LK_EVENTS = "lk_events"
TAB_LK_ACTIONS = "lk_actions"
TAB_LK_ANSWERS = "lk_answers"


def spreadsheet_url() -> str:
    """Public URL of the output spreadsheet (used in Slack messages)."""
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit" if SHEET_ID else ""
