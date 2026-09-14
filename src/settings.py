"""Central configuration for the LLMO monitoring pipeline.

All environment-driven configuration and constants live here so that the
collectors / writers stay thin. Model enable/disable is controlled here so a
model can be toggled without touching collector code (§3).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
# 月次の回答全文。日次と混ざると data/raw の日付ディレクトリの意味が変わるため分ける。
DATA_RAW_MONTHLY_DIR = ROOT_DIR / "data" / "raw" / "monthly"
PROMPTS_FILE = CONFIG_DIR / "prompts.yaml"
# Phase 3 — 月次観測(BOFU:社名指名・競合比較)。日次とはファイルを分ける。
PROMPTS_MONTHLY_FILE = CONFIG_DIR / "prompts_monthly.yaml"
# LLMO効果測定実験(2026-09-14)。47記事に対応する質問文。本田さんが貼った CSV を
# **加工せずそのまま**置いている(YAML にするとクォートの付け方で文字が変わりうる)。
PROMPTS_EXPERIMENT_FILE = CONFIG_DIR / "prompts_experiment.csv"
# 実験の回答全文。日次・月次の日付ディレクトリと混ぜない。
DATA_RAW_EXPERIMENT_DIR = ROOT_DIR / "data" / "raw" / "experiment"
# Entity alias table (Phase 1 §2-1) — appended to during operation, no code change.
ENTITY_ALIASES_FILE = CONFIG_DIR / "entity_aliases.yaml"
# Generic phrases that are not company names and must not be counted.
ENTITY_STOPLIST_FILE = CONFIG_DIR / "entity_stoplist.yaml"
# Phase 2 — weekly insight engine
RULES_THRESHOLDS_FILE = CONFIG_DIR / "rules_thresholds.yaml"
LEGACY_PATHS_FILE = CONFIG_DIR / "legacy_paths.yaml"
# 取り下げた掲載先URL(A-011)。消したあと何日引用され続けるかを実測する。
RETIRED_URLS_FILE = CONFIG_DIR / "retired_urls.yaml"
PLAYBOOK_FILE = CONFIG_DIR / "playbook.md"
# Phase 5 — 判定欄のテンプレート(LLMを使わず決定的に文面を作る)
VERDICT_TEMPLATES_FILE = CONFIG_DIR / "verdict_templates.yaml"
# 目標指標(KGI)の定義と、各指標が有効になった日(2026-09-14 確定)
KGI_FILE = CONFIG_DIR / "kgi.yaml"
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
# 目標指標(KGI)の定義(config/kgi.yaml)
# --------------------------------------------------------------------------
def load_kgi() -> Dict[str, Any]:
    return load_yaml(KGI_FILE)


def key_events_valid_from() -> Optional[str]:
    """GA4 キーイベントが有効になった日(YYYY-MM-DD)。

    これより前は retURL 不備で発火していなかったので、0 は「問い合わせが
    無かった」ではなく「数えられていなかった」。集計側はこの日で切る。
    """
    value = ((load_kgi().get("supplementary") or {}).get("key_events") or {}).get("valid_from")
    return str(value).strip() if value else None


def key_events_valid(date: Any, valid_from: Optional[str] = None) -> bool:
    """その日の key_events を数に入れてよいか。"""
    start = valid_from if valid_from is not None else key_events_valid_from()
    return not start or str(date or "").strip()[:10] >= start


# --------------------------------------------------------------------------
# Prompts (§2 — approved, do not modify the YAML content)
# --------------------------------------------------------------------------
def load_prompts() -> List[Dict[str, Any]]:
    """Load the approved observation prompts from config/prompts.yaml."""
    return load_yaml(PROMPTS_FILE)["prompts"]


# 月次観測の実行日の分割(2026-09-11)。順番に意味がある — 最後のバッチが
# 終わった時点で月次サマリを投稿する。
MONTHLY_BATCHES = ("A", "B")


def load_monthly_prompts(active_only: bool = True,
                         batch: Optional[str] = None) -> List[Dict[str, Any]]:
    """月次観測プロンプト(Phase 3 §1)。

    ``active_only`` が真なら実行対象だけを返す。第2弾候補は
    ``active: false`` で定義だけ置いてあるので、実行数の見積もりと
    区別できるようにしている。

    ``batch`` を渡すとその日に走らせるぶんだけを返す。Gemini の枠が
    20/日で、日次7本が毎日走るため、月次12本を1日で回すと 19 になって
    リトライの余地が無い。6本ずつ2日に割っている(settings.MONTHLY_BATCHES)。
    """
    prompts = load_yaml(PROMPTS_MONTHLY_FILE)["prompts"]
    if active_only:
        prompts = [p for p in prompts if p.get("active")]
    if batch:
        prompts = [p for p in prompts if str(p.get("batch") or "").strip() == batch]
    return prompts


# --------------------------------------------------------------------------
# 観測の曜日割り(2026-09-14 確定)
# --------------------------------------------------------------------------
# 曜日は JST の date.weekday()(月=0 … 日=6)。
#
# Gemini 無料枠は1日20リクエスト。本田さんの判定(2026-09-14):
#   - 日次7本は 火・木・土 だけ観測する(ワークフロー自体は毎日走る。
#     GA4 / GSC は1回の実行で1日分しか取らないので、止めると欠ける)
#   - 実験の Claude は 月・木 に47本
#   - 実験の Gemini は**週2回**。47本を2周に割り、毎日少しずつ回す
#       1周目 月E01-18 火E19-29 水E30-42 木E43-47
#       2周目 金E01-18 土E19-29 日E30-47
#     同じ質問の2回の観測は3〜4日あく。
#
# 曜日ごとの Gemini の計画本数(日次 + 月次 + 実験)。**第1週が最も厳しい**:
#   月18 火18 水13(第1週19) 木12(第1週18) 金18 土18 日18
# 週の実験94本 + 日次21本。第1週は月次12本も入り、枠の余りは週で13しかない。
# どの日も余りは1〜2本で、通常のリトライ(1観測で最大3回追加)は収まらない。
# そのため実験の Gemini は**リトライをその日の余りの範囲に限る**(run_experiment)。
#
# Gemini の1日は太平洋時間で切り替わる(JST 16〜17時)。どのワークフローも
# JST の朝に走るので、JST の1日と枠の1日は1対1に対応する。
DAILY_LLM_WEEKDAYS = (1, 3, 5)                  # 火・木・土
EXPERIMENT_CLAUDE_WEEKDAYS = (0, 3)             # 月・木
# 曜日 -> 実験IDの番号の範囲(両端を含む)
EXPERIMENT_GEMINI_GROUPS: Dict[int, tuple] = {
    0: (1, 18),     # 月 E01〜E18(1周目)
    1: (19, 29),    # 火 E19〜E29
    2: (30, 42),    # 水 E30〜E42
    3: (43, 47),    # 木 E43〜E47
    4: (1, 18),     # 金 E01〜E18(2周目)
    5: (19, 29),    # 土 E19〜E29
    6: (30, 47),    # 日 E30〜E47
}
# 月次のバッチが走る曜日(第1週のみ)。monthly.yml の guard と同じ判定。
MONTHLY_BATCH_WEEKDAYS = {"A": 2, "B": 3}
GEMINI_DAILY_REQUEST_LIMIT = 20
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")


def _weekday(date: str) -> int:
    return dt.date.fromisoformat(str(date)[:10]).weekday()


def is_daily_llm_day(date: str) -> bool:
    """日次の7本を観測する日か(JST の日付)。"""
    return _weekday(date) in DAILY_LLM_WEEKDAYS


def load_experiment_prompts() -> List[Dict[str, Any]]:
    """実験の47本。CSV の値は**strip も含めて一切加工しない**。

    collect_llm が読むキー(``id`` / ``text``)に合わせて ``prompt`` 列を
    ``text`` として渡す。元の列名も残す。
    """
    with open(PROMPTS_EXPERIMENT_FILE, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [dict(row, text=row["prompt"]) for row in rows]


def experiment_number(prompt_id: str) -> int:
    """"E07" -> 7"""
    return int(str(prompt_id).lstrip("E"))


def experiment_plan(date: str) -> Dict[str, List[Dict[str, Any]]]:
    """その日に観測する実験プロンプトをモデルごとに返す。無いモデルは入れない。"""
    weekday = _weekday(date)
    prompts = load_experiment_prompts()
    plan: Dict[str, List[Dict[str, Any]]] = {}
    group = EXPERIMENT_GEMINI_GROUPS.get(weekday)
    if group:
        lo, hi = group
        plan["gemini"] = [p for p in prompts if lo <= experiment_number(p["id"]) <= hi]
    if weekday in EXPERIMENT_CLAUDE_WEEKDAYS:
        plan["claude"] = list(prompts)
    return plan


def gemini_requests_on(date: str, daily_count: int = 7,
                       monthly_batch_size: int = 6) -> Dict[str, int]:
    """その日(JST)の Gemini リクエスト数の見積もり。日次・月次・実験の合計。

    ``retry_headroom`` は「何本まで最大リトライしても枠に収まるか」
    (run_monthly.request_budget と同じ数え方)。
    """
    day = dt.date.fromisoformat(str(date)[:10])
    weekday = day.weekday()
    daily = daily_count if weekday in DAILY_LLM_WEEKDAYS else 0
    monthly = (monthly_batch_size
               if day.day <= 7 and weekday in MONTHLY_BATCH_WEEKDAYS.values() else 0)
    experiment = len(experiment_plan(date).get("gemini", []))
    total = daily + monthly + experiment
    spare = GEMINI_DAILY_REQUEST_LIMIT - total
    return {
        "daily": daily, "monthly": monthly, "experiment": experiment,
        # 日次・月次を引いたあとに実験が使える本数(計画 + リトライの上限)
        "experiment_budget": GEMINI_DAILY_REQUEST_LIMIT - daily - monthly,
        "total": total, "limit": GEMINI_DAILY_REQUEST_LIMIT,
        "over": total > GEMINI_DAILY_REQUEST_LIMIT, "spare": spare,
        "retry_headroom": max(0, spare // max(1, MAX_RETRIES - 1)),
    }


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

# Retry policy (§3): exponential backoff.
#
# 2026-08 まで 3回 / 基準2秒(待機 2+4=6秒)だった。実測した provider 側の
# 障害は20〜90秒続いており、3回とも同じ障害窓の中で落ちていた
# (08-27・08-30 の gemini。窓を抜けた次のプロンプトは35秒後に成功している)。
#
# ただし回数を増やしすぎてはいけない。gemini の 429 が返す quotaId は
# `GenerateRequestsPerDayPerProjectPerModel-FreeTier` で quotaValue は 20 ——
# **1日あたりのリクエスト数**である。7プロンプト×5回 = 35 では、対策が
# 枠を食い潰して原因を悪化させる。回数は4回に抑え、代わりに
# 1回あたりの待ちを長くして障害窓をまたぐ(待機 5+10+20=35秒)。
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
BACKOFF_BASE_SECONDS = float(os.getenv("BACKOFF_BASE_SECONDS", "5"))

# provider が「何秒後に再試行せよ」と返してきたときは、その値を優先する
# (gemini の 429 は RetryInfo.retryDelay を持つ)。ただし1回の実行が
# 止まらないよう上限を設ける。
RETRY_DELAY_CAP_SECONDS = float(os.getenv("RETRY_DELAY_CAP_SECONDS", "90"))

# 収集ループを一巡したあと、失敗した観測だけをもう一度取り直す前の待ち時間。
# 一巡するのに数分かかるので、ここを待てば障害窓はほぼ確実に抜けている。
SWEEP_COOLDOWN_SECONDS = float(os.getenv("SWEEP_COOLDOWN_SECONDS", "60"))


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
# 記事単位のGSC(2026-09-14)。差の差分析の単位。gsc_branded とは別に持つ。
TAB_GSC_PAGES = "gsc_pages"
TAB_AHREFS = "ahrefs_aio"
TAB_SUMMARY = "daily_summary"
# Phase 1 tabs (approved — do not change the schema)
TAB_SOV = "sov_daily"
TAB_CHANGES = "changes"
# Phase 2
TAB_WEEKLY = "weekly_reports"
# Phase 3 — 月次観測。日次の llm_observations には混ぜない
# (言及率など日次指標の母数を汚さないため)。
TAB_MONTHLY = "monthly_observations"
# LLMO効果測定実験(2026-09-14)。ダッシュボード用のタブとは混ぜない。
TAB_EXPERIMENT = "llm_experiment"
# 比較型観測のKBF別評価。月次実行のたびに書き換える(Phase 3 追加)。
TAB_LK_KBF_COMPARE = "lk_kbf_compare"
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
# Phase 7 — プロンプト別の推移。日次と月次の両方が同じタブに入り、
# funnel(MOFU/BOFU)で区別できる。
TAB_LK_MENTION_GRID = "lk_mention_grid"
# 1プロンプト1行 × 日付を横に並べた回答の一覧。列が日付なので
# ヘッダが実行のたびに変わる。LOOKER_TABS(固定ヘッダ)には入れない。
TAB_LK_ANSWERS_PIVOT = "lk_answers_pivot"


def spreadsheet_url() -> str:
    """Public URL of the output spreadsheet (used in Slack messages)."""
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit" if SHEET_ID else ""
