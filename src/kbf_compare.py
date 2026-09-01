"""kbf_compare.py — 比較型観測のKBF別評価を機械集計する(Phase 3 追加).

月次の比較3本(M-7〜M-9)は「自社と競合のどちらに寄ったか」を読むための面だが、
回答は自然文なので毎月人が読み直すことになる。**KBFごとに自社と競合の
どちらが語られたかだけ**を機械で拾い、月をまたいで並べられる形にする。

判定するのは3つだけ。**優劣は判定しない。**

    self_eval  … そのKBFが自社の文脈で語られたか
    rival_eval … そのKBFが競合の文脈で語られたか
    diff       … self / rival / both / neither

「どちらが優れているか」は回答文の含意によるもので、機械では取れない。
取れないものを取れたことにすると、月次サマリの「要目視」と矛盾する。
ここで出すのは**軸の占有**(その軸を誰が語っているか)だけ。

自社の文脈か競合の文脈かは、KBF語の出現位置がどちらの社名により近いかで決める。
比較回答は社ごとの節に分かれているため、近さで十分に切り分けられる。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from extract import KBF_TAG_OPTIONS
from settings import BRAND_ALIASES

# KBF ごとの手がかり語。extract.py の選択肢(§4・変更禁止)に1対1で対応させる。
# 抽出済みの kbf_tags は「回答全体でどのKBFが語られたか」しか持たないので、
# 自社/競合のどちらの文脈かを取るには本文を見る必要がある。
KBF_PATTERNS: Dict[str, str] = {
    "ベンダー中立": r"ベンダー(?:中立|ニュートラル)|特定(?:の)?(?:製品|ツール|ベンダー)に(?:縛られ|依存|限定)|製品を前提とせず|ツール非依存",
    "設計支援": r"設計(?:支援|から|を起点|内容|論)|業務設計|データ設計|要件定義|構想",
    "定着支援": r"定着|伴走|運用の自走|内製化|モニタリング",
    "Agentforce専門性": r"Agentforce|公式(?:コンサルティング)?パートナー|Sales\s*Cloud|Account\s*Engagement",
    "ソリューション営業知見": r"ソリューション営業|BtoB(?:マーケティング|営業)|商談プロセス|法人営業|営業(?:現場|実務)",
    "実績・事例": r"実績|事例|社以上|年以上|導入企業|支援してきた|PoC実施",
}
assert set(KBF_PATTERNS) <= KBF_TAG_OPTIONS

# 「その他」は手がかり語を定義できないので集計しない。
SKIP_TAGS = {"その他"}

DIFF_SELF = "self"
DIFF_RIVAL = "rival"
DIFF_BOTH = "both"
DIFF_NEITHER = "neither"

COMPARE_CATEGORY = "bofu_compare"


def _positions(text: str, pattern: str) -> List[int]:
    return [m.start() for m in re.finditer(pattern, text, re.IGNORECASE)]


def _brand_positions(text: str, names: Sequence[str]) -> List[int]:
    out: List[int] = []
    for name in names:
        if name:
            out.extend(_positions(text, re.escape(name)))
    return sorted(out)


def _distance(position: int, anchors: Sequence[int]) -> Optional[int]:
    """``position`` がどの社の節に属するかを測る距離。

    **直前の社名を優先する。** 比較回答は「◯◯社は…」と社名で節が始まり、
    そのあとにKBF語が続く構造になっている。単純な近さで測ると、
    直後に別の社名が来ただけでそちらの節に取られてしまう
    (「クロスコムは定着支援。テクノデジタル…も定着支援。」の前半が競合になる)。

    直前に社名が無い場合だけ、直後の社名までの距離を使う。
    その場合は不利に扱う(+1000)ので、直前に社名がある側が勝つ。
    """
    if not anchors:
        return None
    before = [position - a for a in anchors if a <= position]
    if before:
        return min(before)
    return min(a - position for a in anchors) + 1000


def classify(text: str, rival: str,
             self_names: Optional[Sequence[str]] = None) -> Dict[str, str]:
    """回答本文から、KBFごとに誰がその軸を語られたかを返す。

    自社と競合のどちらの文脈かは、KBF語の**直前にある社名**で決める。
    比較回答は「◯◯社は…」と社名で節が始まる構造なので、直前の社名が
    その語の持ち主になる。同じ距離なら両方に数える(節の境目を取りこぼさない)。
    """
    self_names = list(self_names or BRAND_ALIASES)
    self_at = _brand_positions(text, self_names)
    rival_at = _brand_positions(text, [rival]) if rival else []

    out: Dict[str, str] = {}
    for tag, pattern in KBF_PATTERNS.items():
        hits = _positions(text, pattern)
        by_self = by_rival = False
        for position in hits:
            d_self = _distance(position, self_at)
            d_rival = _distance(position, rival_at)
            if d_self is None and d_rival is None:
                continue
            if d_rival is None or (d_self is not None and d_self < d_rival):
                by_self = True
            elif d_self is None or d_rival < d_self:
                by_rival = True
            else:                      # 同距離。どちらの節とも言えない
                by_self = by_rival = True
        out[tag] = (
            DIFF_BOTH if by_self and by_rival else
            DIFF_SELF if by_self else
            DIFF_RIVAL if by_rival else
            DIFF_NEITHER
        )
    return out


def rows_from_records(month: str, records: Sequence[Dict[str, Any]],
                      prompts: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """lk_kbf_compare の行を作る。

    ``records`` は collect_llm の生レコード(answer と target_brand を持つ)。
    比較型(bofu_compare)以外は無視する。
    """
    brands = {str(p.get("id")): str(p.get("target_brand") or "")
              for p in prompts if p.get("target_brand")}
    rows: List[Dict[str, Any]] = []
    for record in records:
        if str(record.get("category") or "") != COMPARE_CATEGORY:
            continue
        answer = str(record.get("answer") or "")
        if not answer or record.get("error"):
            continue
        prompt_id = str(record.get("prompt_id") or "")
        rival = str(record.get("target_brand") or "") or brands.get(prompt_id, "")
        verdicts = classify(answer, rival)
        for tag in sorted(KBF_PATTERNS):
            if tag in SKIP_TAGS:
                continue
            diff = verdicts[tag]
            rows.append({
                "month": month,
                "prompt_id": prompt_id,
                "model": str(record.get("model") or ""),
                "kbf": tag,
                "self_eval": "TRUE" if diff in (DIFF_SELF, DIFF_BOTH) else "FALSE",
                "rival_eval": "TRUE" if diff in (DIFF_RIVAL, DIFF_BOTH) else "FALSE",
                "diff": diff,
            })
    rows.sort(key=lambda r: (r["prompt_id"], r["model"], r["kbf"]))
    return rows


def summary(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """ジョブサマリ用。**競合だけが語ったKBF**を並べる(埋めるべき軸)。"""
    only_rival = sorted({r["kbf"] for r in rows if r["diff"] == DIFF_RIVAL})
    only_self = sorted({r["kbf"] for r in rows if r["diff"] == DIFF_SELF})
    lines = []
    if only_rival:
        lines.append(f"競合のみが語った軸: {', '.join(only_rival)}")
    if only_self:
        lines.append(f"自社のみが語った軸: {', '.join(only_self)}")
    if not lines:
        lines.append("比較型のKBF差分なし")
    return lines
