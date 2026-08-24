"""board_daily.py — Looker Studio 用フラットタブ(Phase 5 §6).

1日1行。Looker側で計算しなくても読めるよう、移動平均・週計・連続日数まで
ここで確定させておく。Looker Studio の再構築自体は本Phaseの対象外で、
先にタブとデータだけ用意する。

すべて既に読み込み済みのデータから組み立てるため、Sheets APIの追加読み取りは
発生しない(§8)。
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Dict, List, Optional, Sequence

from analyze_diff import parse_bool
from settings import SELF_ENTITY

WINDOW_DAYS = 7
ENTITY_PROMPT_ID = "E-1"


def _num(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _window(date: str, days: int = WINDOW_DAYS) -> tuple:
    end = dt.date.fromisoformat(date)
    return (end - dt.timedelta(days=days - 1)).isoformat(), date


def _in(row: Dict[str, Any], window: tuple) -> bool:
    day = str(row.get("date") or "").strip()
    return bool(day) and window[0] <= day <= window[1]


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 4) if values else None


def mention_rate_7d(summary_rows: Sequence[Dict[str, Any]], date: str,
                    column: str) -> Optional[float]:
    window = _window(date)
    values = [v for v in (_num(r.get(column)) for r in summary_rows if _in(r, window))
              if v is not None]
    return _mean(values)


def negative_streak_days(observations: Sequence[Dict[str, Any]], date: str) -> int:
    """いずれかのプロンプトで検知が続いている日数。0なら当日は検知なし。"""
    by_date: Dict[str, bool] = {}
    for row in observations:
        day = str(row.get("date") or "").strip()
        if not day or day > date:
            continue
        flag = bool(parse_bool(row.get("negative_or_outdated")))
        by_date[day] = by_date.get(day, False) or flag
    streak = 0
    for day in sorted(by_date, reverse=True):
        if not by_date[day]:
            break
        streak += 1
    return streak


def sov_position(sov_rows: Sequence[Dict[str, Any]], date: str) -> Dict[str, Any]:
    """当日 pillar=all における自社の順位とシェア。"""
    same_day = [r for r in sov_rows
                if str(r.get("date") or "") == date
                and str(r.get("pillar") or "") == "all"]
    if not same_day:
        return {"rank": None, "share": None}
    ranked = sorted(same_day, key=lambda r: -(_num(r.get("mention_count")) or 0))
    observed = max((_num(r.get("observed_total")) or 0) for r in same_day)
    for position, row in enumerate(ranked, start=1):
        if str(row.get("entity") or "") == SELF_ENTITY:
            count = _num(row.get("mention_count")) or 0
            return {"rank": position,
                    "share": round(count / observed, 4) if observed else None}
    return {"rank": None, "share": None}


def material_events(changes: Sequence[Dict[str, Any]], date: str,
                    limit: int = 5) -> str:
    """当日の重要な変化をセミコロン区切りで要約する。

    すべての change_type を並べると読めないので、意味が大きい3種に絞る。
    """
    priority = {"negative_flag_on": "ネガ検知", "mention_lost": "言及消失",
                "mention_gained": "言及獲得"}
    picked: List[str] = []
    for change_type, label in priority.items():
        targets = [
            f"{r.get('prompt_id')}({r.get('model')})"
            for r in changes
            if str(r.get("date") or "") == date
            and str(r.get("change_type") or "") == change_type
        ]
        if targets:
            picked.append(f"{label}:{','.join(targets[:limit])}")
    return "; ".join(picked)


def build_row(
    date: str,
    summary_rows: Sequence[Dict[str, Any]] = (),
    observations: Sequence[Dict[str, Any]] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    changes: Sequence[Dict[str, Any]] = (),
    ga4_rows: Sequence[Dict[str, Any]] = (),
    gsc_rows: Sequence[Dict[str, Any]] = (),
    noise_floor: float = 10.0,
) -> Dict[str, Any]:
    window = _window(date)
    ai_sessions = sum(_num(r.get("sessions")) or 0 for r in ga4_rows if _in(r, window))
    branded_clicks = sum(_num(r.get("clicks")) or 0 for r in gsc_rows if _in(r, window))
    position = sov_position(sov_rows, date)

    def pct(value: Optional[float]) -> str:
        return "" if value is None else f"{value:.4f}"

    return {
        "date": date,
        "mention_rate_all_7d": pct(mention_rate_7d(summary_rows, date, "mention_rate_all")),
        "mention_rate_a_7d": pct(mention_rate_7d(summary_rows, date, "mention_rate_pillar_a")),
        "mention_rate_b_7d": pct(mention_rate_7d(summary_rows, date, "mention_rate_pillar_b")),
        "sov_rank": "" if position["rank"] is None else position["rank"],
        "sov_share": pct(position["share"]),
        "negative_streak_days": negative_streak_days(observations, date),
        "branded_clicks_wk": f"{branded_clicks:.0f}",
        "ai_sessions_wk": f"{ai_sessions:.0f}",
        # 母数が判断に足りない週かどうか。Looker側で色分けに使う。
        "noise_flag": "TRUE" if max(ai_sessions, branded_clicks) < noise_floor else "FALSE",
        "material_events": material_events(changes, date),
    }
