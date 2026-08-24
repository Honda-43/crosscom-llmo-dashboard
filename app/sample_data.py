"""sample_data.py — synthetic tabs for previewing the UI without credentials.

Only reachable when ``LLMO_DASHBOARD_SAMPLE`` is set, and every page shows a
warning banner while it is on. This exists so the layout and the chart code can
be exercised before a service account is wired up — it is never a data source
for analysis, and it never touches Google Sheets.

The shapes match the approved tab schemas exactly; only the values are made up.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from typing import Any, Dict, List

from settings import (
    TAB_ACTION_LOG, TAB_CHANGES, TAB_CITATION_GAP, TAB_GA4, TAB_GSC, TAB_LLM,
    TAB_SOV, TAB_SUMMARY, TAB_WEEKLY,
)

_END = dt.date(2026, 8, 17)
_DAYS = 41
_PROMPTS = [("A-1", "A"), ("A-2", "A"), ("A-3", "A"),
            ("B-1", "B"), ("B-2", "B"), ("B-3", "B"), ("E-1", "entity")]
_MODELS = ["claude", "gemini"]
_ENTITIES = ["クロスコム", "メンバーズ", "三菱総研DCS", "船井総合研究所",
             "日立ソリューションズ", "ハンドレッド", "ウフル"]


def _dates() -> List[dt.date]:
    return [_END - dt.timedelta(days=n) for n in range(_DAYS - 1, -1, -1)]


def sample_tabs() -> Dict[str, List[Dict[str, str]]]:
    rng = random.Random(20260817)  # deterministic so screenshots are stable

    llm, summary, sov, changes, ga4, gsc = [], [], [], [], [], []

    for day_index, date in enumerate(_dates()):
        iso = date.isoformat()
        trend = day_index / max(_DAYS - 1, 1)
        mention_p = {"A": 0.35 + 0.25 * trend, "B": 0.20 + 0.20 * trend, "entity": 1.0}

        hits = {"A": 0, "B": 0}
        totals = {"A": 0, "B": 0}
        day_entities: Dict[str, Dict[str, int]] = {"A": {}, "B": {}, "all": {}}

        for prompt_id, pillar in _PROMPTS:
            for model in _MODELS:
                mentioned = rng.random() < mention_p[pillar]
                rank = rng.choice([1, 2, 3, 4, 6, 7]) if mentioned and pillar != "entity" else ""
                competitors = rng.sample(_ENTITIES[1:], rng.randint(1, 4))
                negative = prompt_id == "E-1" and model == "claude" and day_index % 13 == 5
                llm.append({
                    "date": iso, "prompt_id": prompt_id, "pillar": pillar, "model": model,
                    "mention": "TRUE" if mentioned else "FALSE",
                    "mention_type": "recommended_list" if mentioned else "none",
                    "rank": str(rank),
                    "kbf_tags": ", ".join(rng.sample(
                        ["ベンダー中立", "設計支援", "定着支援", "Agentforce専門性",
                         "ソリューション営業知見", "実績・事例"], rng.randint(1, 3))),
                    "negative_or_outdated": "TRUE" if negative else "FALSE",
                    "negative_detail": "旧MA/メール配信事業の記述が含まれる" if negative else "",
                    "cited_crosscom_urls": "https://cross-com.jp/about/, https://cross-com.jp/"
                                            if model == "claude" else "",
                    "competitors_mentioned": ", ".join(competitors),
                    "raw_file": f"data/raw/{iso}/{prompt_id}_{model}.json",
                })
                if pillar in totals:
                    totals[pillar] += 1
                    hits[pillar] += 1 if mentioned else 0
                    for bucket in (pillar, "all"):
                        if mentioned:
                            day_entities[bucket]["クロスコム"] = \
                                day_entities[bucket].get("クロスコム", 0) + 1
                        for entity in competitors:
                            day_entities[bucket][entity] = \
                                day_entities[bucket].get(entity, 0) + 1

        rate_a = round(hits["A"] / totals["A"], 4) if totals["A"] else 0.0
        rate_b = round(hits["B"] / totals["B"], 4) if totals["B"] else 0.0
        rate_all = round((hits["A"] + hits["B"]) / (totals["A"] + totals["B"]), 4)
        summary.append({
            "date": iso, "mention_rate_all": str(rate_all),
            "mention_rate_pillar_a": str(rate_a), "mention_rate_pillar_b": str(rate_b),
            "negative_flag_count": "1" if day_index % 13 == 5 else "0",
            "ai_sessions": str(rng.randint(0, 4)), "branded_clicks": str(rng.randint(0, 3)),
        })

        for pillar, counts in day_entities.items():
            observed = totals["A"] + totals["B"] if pillar == "all" else totals[pillar]
            for entity, count in counts.items():
                sov.append({
                    "date": iso, "pillar": pillar, "entity": entity,
                    "mention_count": str(count), "observed_total": str(observed),
                })

        ga4.append({"date": iso, "source": "chatgpt.com", "landing_page": "/",
                    "sessions": str(rng.randint(0, 3)), "key_events": "0"})
        gsc.append({"date": iso, "query": "クロスコム", "clicks": str(rng.randint(0, 2)),
                    "impressions": str(rng.randint(1, 6))})

        if day_index % 5 == 0 and day_index:
            prompt_id, _ = rng.choice(_PROMPTS[:6])
            kind = rng.choice(["mention_gained", "mention_lost", "rank_up",
                               "competitor_added", "negative_flag_on"])
            changes.append({
                "date": iso, "prompt_id": prompt_id, "model": rng.choice(_MODELS),
                "change_type": kind, "before": "FALSE", "after": "TRUE",
                "detail": "船井総合研究所" if kind == "competitor_added" else "",
            })

    weekly = []
    for week_end in (_END, _END - dt.timedelta(days=7)):
        iso = week_end.isoformat()
        stats = {
            "date": iso, "fired_rules": ["R-P7", "R-P2"], "insufficient_rules": ["R-P5"],
            "mention_rate": {"all": {"this_week": 0.48, "prev_week": 0.41, "delta": 0.07}},
            "kgi": {"ai_sessions": {"this_week": 2, "prev_week": 4, "delta": -2,
                                    "noise_zone": True}, "noise_floor": 10,
                    "noise_zone_metrics": ["ai_sessions"]},
        }
        weekly.append({
            "date": iso,
            "stats_json": json.dumps(stats, ensure_ascii=False),
            "report_md": (
                f"## 1. 今週のサマリ\n\n【サンプル】{iso} 週の所見です。"
                "言及率は改善傾向、ネガティブ検知が1件あります。\n\n"
                "## 2. 数値ハイライト\n\n- mention_rate (all): 0.48 (前週比 +0.07)\n"
                "- AI経由セッション: 2 (前週比 -2) ※母数が小さく判断できない水準\n\n"
                "## 3. 発火パターンと推奨アクション\n\n"
                "- **R-P7**: E-1でネガティブ検知。引用元URLの特定を今週中に実施。\n"
                "- **R-P2**: B-1×claudeで言及消失。事例ページを1本更新。\n\n"
                "## 4. ウォッチ項目\n\n- 船井総合研究所のSoVが2週連続で増加\n\n"
                "## 5. 判定不能・データ不足\n\n- R-P5: 4週分のrank中央値が揃わない\n"
            ),
        })

    from action_log import SEED_ROWS

    return {
        TAB_SUMMARY: summary, TAB_LLM: llm, TAB_SOV: sov,
        TAB_CHANGES: changes, TAB_GA4: ga4, TAB_GSC: gsc, TAB_WEEKLY: weekly,
        TAB_ACTION_LOG: [dict(r) for r in SEED_ROWS],
        TAB_CITATION_GAP: [],
    }
