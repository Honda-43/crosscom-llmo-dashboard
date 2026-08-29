"""display_map.py — 表示用の値の対応表(表示層とLooker出力の共通定義).

シートのセル値そのものは変えない。ここは「保存されている値 → 画面に出す日本語」
の一方向の対応表で、ローカルアプリ(app/labels.py)と Looker 用タブ
(src/looker_tabs.py)の両方が同じ対応を使うために置いている。

同じ意味の値が画面ごとに違う言葉で出るのを防ぐのが目的なので、
どちらか一方だけを書き換えないこと。
"""
from __future__ import annotations

from typing import Any, Dict

# 施策の「対象」列。プロンプトID(E-1・B-3 等)は識別コードなので
# 対応表に載せず、そのまま通す。
TARGET_LABELS: Dict[str, str] = {"KGI": "成果指標"}

# ルール判定の値。値そのもの(rules_engine の fired 等)は変えず、表示だけ訳す。
STATUS_LABELS: Dict[str, str] = {
    "fired": "発火",
    "not_fired": "非発火",
    "insufficient_data": "判定不能",
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

# 観測の区分。画面では何の区分かが分かる名前で出す。
PILLAR_LABELS: Dict[str, str] = {
    "all": "全体(A+B)",
    "A": "Agentforce系(A)",
    "B": "Agentic CRM系(B)",
}

MISSING = "—"


def _lookup(table: Dict[str, str], value: Any) -> str:
    """対応表に無い値はそのまま返す(識別コードを壊さないため)。"""
    text = str(value).strip() if value is not None else ""
    return table.get(text, text)


def target(value: Any) -> str:
    return _lookup(TARGET_LABELS, value)


def status(value: Any) -> str:
    return _lookup(STATUS_LABELS, value)


def change_type(value: Any) -> str:
    return _lookup(CHANGE_TYPE_LABELS, value)


def pillar(value: Any) -> str:
    return _lookup(PILLAR_LABELS, value)
