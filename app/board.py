"""board.py — 8面レポート共通の部品(Phase 5 §1 / §2).

各面が同じ見た目・同じ判定の作り方になるよう、ここに集約する。
判定欄の文面は config/verdict_templates.yaml 由来で、この層では組み立てない。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
import verdicts
from settings import (
    SELF_ENTITY, TAB_ACTION_LOG, TAB_CHANGES, TAB_GA4, TAB_GSC, TAB_LLM,
    TAB_SOV, TAB_SUMMARY,
)

WINDOW_DAYS = 7
LOOKBACK_DAYS = 28


# --------------------------------------------------------------------------
# データ取得(タブごと1回・10分キャッシュは data_source 側)
# --------------------------------------------------------------------------
def observations() -> pd.DataFrame:
    return common.observations_frame(data_source.tab(TAB_LLM))


def summary_frame() -> pd.DataFrame:
    return common.to_frame(
        data_source.tab(TAB_SUMMARY),
        numeric=["mention_rate_all", "mention_rate_pillar_a", "mention_rate_pillar_b",
                 "negative_flag_count", "ai_sessions", "branded_clicks"],
    )


def sov_frame() -> pd.DataFrame:
    return common.to_frame(data_source.tab(TAB_SOV),
                           numeric=["mention_count", "observed_total"])


def changes_frame() -> pd.DataFrame:
    return common.to_frame(data_source.tab(TAB_CHANGES))


def action_rows() -> List[Dict[str, str]]:
    return data_source.tab(TAB_ACTION_LOG)


def kgi_frames():
    return (common.to_frame(data_source.tab(TAB_GA4), numeric=["sessions", "key_events"]),
            common.to_frame(data_source.tab(TAB_GSC), numeric=["clicks", "impressions"]))


def noise_floor() -> float:
    try:
        from rules_engine import load_thresholds

        return float((load_thresholds().get("kgi") or {}).get("noise_floor", 10))
    except Exception:  # noqa: BLE001
        return 10.0


# --------------------------------------------------------------------------
# 見た目の部品
# --------------------------------------------------------------------------
def face_header(code: str, title: str, subtitle: str = "") -> None:
    common.page_header(f"{code} {title}", subtitle)


def metric_card(col, label: str, value: str, delta: Optional[str] = None,
                note: str = "", help_text: str = "") -> None:
    """白カード1枚。前週比はチップとしてStreamlitのdeltaに載せる。"""
    col.metric(label, value, delta, help=help_text or None)
    if note:
        col.caption(note)


def verdict_panel(face: str, context: Dict[str, Any]) -> None:
    """各面の下部に出す判定欄(§2)。文面はテンプレート由来。"""
    st.divider()
    try:
        text = verdicts.render(face, context)
    except verdicts.MissingPlaceholder as exc:
        st.error(f"判定テンプレートが未定義の変数を参照しています: {exc}")
        return
    if not text:
        st.info("判定: 条件に一致するテンプレートがありません。"
                "config/verdict_templates.yaml を確認してください。")
        return
    st.markdown(
        f"<div style='background:#f6f8fa;border-left:4px solid {common.PALETTE[0]};"
        f"border-radius:6px;padding:14px 18px;line-height:1.9;font-size:15px'>"
        f"{text}</div>",
        unsafe_allow_html=True,
    )


def action_annotations(figure: go.Figure, actions: Sequence[Dict[str, Any]]) -> str:
    """実施済みの施策を縦線注釈として描き、凡例用の対応表を返す(§4)。

    注釈にはaction_idだけを置く。施策名まで載せると、日付が近い注釈どうしで
    文字が重なって全部読めなくなるため。名称はキャプションに逃がす。
    """
    by_date: Dict[Any, List[Dict[str, Any]]] = {}
    for action in actions:
        by_date.setdefault(action["date"], []).append(action)

    legend = []
    for date, same_day in sorted(by_date.items()):
        ids = ", ".join(a["action_id"] for a in same_day)
        figure.add_vline(
            x=pd.Timestamp(date),
            line=dict(color=common.INK, width=1.5, dash="dash"),
            annotation_text=ids,
            annotation_position="top left",
            annotation_font=dict(color=common.INK_MUTED, size=11),
        )
        for action in same_day:
            legend.append(f"{action['action_id']} {action['label']}({date:%m/%d})")
    return " / ".join(legend)


# --------------------------------------------------------------------------
# 指標の算出(判定欄と各面で同じ値を使う)
# --------------------------------------------------------------------------
def latest_date(frame: pd.DataFrame) -> Optional[pd.Timestamp]:
    return None if frame.empty else frame["date"].max()


def window_mean(frame: pd.DataFrame, column: str, end: pd.Timestamp,
                days: int = WINDOW_DAYS) -> Optional[float]:
    if frame.empty or column not in frame.columns:
        return None
    rows = frame[(frame["date"] > end - pd.Timedelta(days=days)) & (frame["date"] <= end)]
    values = rows[column].dropna()
    return round(float(values.mean()), 4) if len(values) else None


def negative_streak(obs: pd.DataFrame, end: pd.Timestamp) -> int:
    if obs.empty:
        return 0
    by_date = obs[obs["date"] <= end].groupby("date")["negative_bool"].any()
    streak = 0
    for day in sorted(by_date.index, reverse=True):
        if not bool(by_date.loc[day]):
            break
        streak += 1
    return streak


def build_context(face: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """全面共通のコンテキスト。各面が必要な値だけ上書きする。

    ``face`` を渡すと「直近の施策・次の施策・判断期限」をその面に関係する
    施策だけから求める(R3はネガ検知に効く施策、R7はKGI向けのみ)。
    """
    obs = observations()
    summary = summary_frame()
    sov = sov_frame()
    ga4, gsc = kgi_frames()
    end = latest_date(summary) or latest_date(obs) or pd.Timestamp(dt.date.today())

    rate_now = window_mean(summary, "mention_rate_all", end)
    rate_prev = window_mean(summary, "mention_rate_all", end - pd.Timedelta(days=WINDOW_DAYS))
    delta = None if (rate_now is None or rate_prev is None) else round(rate_now - rate_prev, 4)

    week = obs[obs["date"] > end - pd.Timedelta(days=WINDOW_DAYS)] if not obs.empty else obs
    negatives = int(week["negative_bool"].sum()) if not week.empty else 0

    ai_sessions = float(ga4[ga4["date"] > end - pd.Timedelta(days=WINDOW_DAYS)]["sessions"]
                        .fillna(0).sum()) if not ga4.empty else 0.0
    clicks = float(gsc[gsc["date"] > end - pd.Timedelta(days=WINDOW_DAYS)]["clicks"]
                   .fillna(0).sum()) if not gsc.empty else 0.0
    floor = noise_floor()

    base = dict(
        negative_streak_days=negative_streak(obs, end),
        negative_count_7d=negatives,
        mention_rate_all_7d=rate_now,
        mention_rate_delta_7d=delta,
        ai_sessions_wk=ai_sessions,
        branded_clicks_wk=clicks,
        kgi_noise=max(ai_sessions, clicks) < floor,
        noise_floor=floor,
    )
    base.update(overrides)
    scoped = verdicts.actions_for_face(face, action_rows()) if face else action_rows()
    return verdicts.build_context(end.strftime("%Y-%m-%d"), scoped, **base)


def self_position(sov: pd.DataFrame, end: pd.Timestamp,
                  days: int = LOOKBACK_DAYS) -> Dict[str, Any]:
    """直近 ``days`` 日の pillar=all における自社のシェアと順位。"""
    if sov.empty:
        return {"share": None, "rank": None, "top": "—", "gap": None, "totals": None}
    window = sov[(sov["pillar"] == "all") & (sov["date"] > end - pd.Timedelta(days=days))]
    if window.empty:
        return {"share": None, "rank": None, "top": "—", "gap": None, "totals": None}
    totals = window.groupby("entity")["mention_count"].sum().sort_values(ascending=False)
    observed = window.groupby("date")["observed_total"].max().sum()
    shares = totals / observed if observed else totals * 0
    rank = list(totals.index).index(SELF_ENTITY) + 1 if SELF_ENTITY in totals.index else None
    top = totals.index[0] if len(totals) else "—"
    gap = None
    if rank and top != SELF_ENTITY:
        gap = round(float(shares.iloc[0] - shares.get(SELF_ENTITY, 0)), 4)
    return {
        "share": round(float(shares.get(SELF_ENTITY, 0)), 4) if rank else None,
        "rank": rank, "top": top, "gap": gap, "totals": totals, "shares": shares,
        "observed": observed,
    }
