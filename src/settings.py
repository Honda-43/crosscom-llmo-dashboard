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


# --------------------------------------------------------------------------
# Prompts (§2 — approved, do not modify the YAML content)
# --------------------------------------------------------------------------
def load_prompts() -> List[Dict[str, Any]]:
    """Load the approved observation prompts from config/prompts.yaml."""
    with open(PROMPTS_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["prompts"]


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
