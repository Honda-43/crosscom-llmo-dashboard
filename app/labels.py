"""labels.py — 画面に出すラベルの対応表(表示層だけ).

シートのタブ名・カラム名、action_id / rule_id / prompt_id の値、yaml やコードの
内部名は変更しない。ここは「内部名 → 画面に出す日本語」の一方向の対応表で、
表示の直前だけで使う。データそのものには触らない。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from analyze_diff import parse_bool  # noqa: E402  - needs the sys.path line above

# 表の見出しに出るカラム名。ここに無いカラムは元の名前のまま出す
# (日本語のカラム名はシート側ですでに日本語のため触らない)。
COLUMN_LABELS: Dict[str, str] = {
    "date": "日付",
    "prompt_id": "プロンプト",
    "model": "モデル",
    "pillar": "区分",
    "entity": "エンティティ",
    "action_id": "施策番号",
    "rule_id": "ルール番号",
    "根拠rule_id": "根拠ルール",
    "mention": "言及",
    "mention_count": "言及回数",
    "mention_rate": "言及率",
    "rank": "順位",
    "share": "シェア",
    "delta": "前週差",
    "status": "判定",
    "detail": "内容",
    "change_type": "変化の種類",
    "before": "変化前",
    "after": "変化後",
    "negative_or_outdated": "ネガ・旧情報",
    "kbf_tags": "KBF",
    "competitors_mentioned": "競合",
    "cited_crosscom_urls": "自社URL",
    "cited_urls": "引用URL",
    "observed_total": "観測数",
    "sessions": "セッション",
    "key_events": "主要イベント",
    "clicks": "クリック",
    "impressions": "インプレッション",
    "ai_sessions": "AI経由セッション",
    "ai_key_events": "AI経由の主要イベント",
    "branded_clicks": "指名検索クリック",
    "branded_impressions": "指名検索インプレッション",
}

# Pillar は観測の区分名。画面では何の区分かが分かる名前で出す。
PILLAR_LABELS: Dict[str, str] = {
    "all": "全体(A+B)",
    "A": "Agentforce系(A)",
    "B": "Agentic CRM系(B)",
}

# changes タブの change_type。シートはこの値でキーされているので値は変えない。
CHANGE_TYPE_LABELS: Dict[str, str] = {
    "mention_gained": "言及が出た",
    "mention_lost": "言及が消えた",
    "rank_up": "順位が上がった",
    "rank_down": "順位が下がった",
    "competitor_added": "競合が増えた",
    "competitor_removed": "競合が消えた",
    "crosscom_url_added": "自社URLが増えた",
    "crosscom_url_removed": "自社URLが消えた",
    "negative_flag_on": "ネガ・旧情報を検知",
    "negative_flag_off": "ネガ・旧情報が消えた",
}

# 変化前・変化後が真偽値になる種類。ここだけ「あり・なし」に置き換える
# (順位や競合名の行まで訳すと値が壊れる)。
_BOOLEAN_CHANGES = frozenset({
    "mention_gained", "mention_lost", "negative_flag_on", "negative_flag_off",
})

# ルール判定の値。値そのもの(rules_engine の fired 等)は変えず、表示だけ訳す。
STATUS_LABELS: Dict[str, str] = {
    "fired": "発火",
    "not_fired": "非発火",
    "insufficient_data": "判定不能",
}

YES, NO = "あり", "なし"


def ja_columns(frame: pd.DataFrame,
               extra: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """表示の直前に見出しだけ日本語化する(元のフレームは変えない)。"""
    mapping = dict(COLUMN_LABELS)
    if extra:
        mapping.update(extra)
    return frame.rename(
        columns={c: mapping[c] for c in frame.columns if c in mapping})


def column(name: str) -> str:
    """カラム1つ分の見出し。表以外(カード名など)で使う。"""
    return COLUMN_LABELS.get(name, name)


def pillar(code: Any) -> str:
    return PILLAR_LABELS.get(str(code).strip(), str(code))


def status(value: Any) -> str:
    return STATUS_LABELS.get(str(value).strip(), str(value))


def yes_no(value: Any) -> str:
    """TRUE / FALSE を「あり・なし」で出す(判定できない値は空欄)。"""
    parsed = parse_bool(value)
    return "" if parsed is None else (YES if parsed else NO)


def change_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """changes タブの行を表示用に訳す(元の行は変えない)。"""
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = str(row.get("change_type", "")).strip()
        shown = dict(row)
        shown["change_type"] = CHANGE_TYPE_LABELS.get(raw, raw)
        if raw in _BOOLEAN_CHANGES:
            for side in ("before", "after"):
                shown[side] = yes_no(row.get(side)) or row.get(side, "")
        out.append(shown)
    return out
