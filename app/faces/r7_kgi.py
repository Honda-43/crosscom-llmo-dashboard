"""R7 KGI — 週計カード + 波及順序(Phase 5 §1)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source

board.face_header("R7", "成果指標(KGI)", "先行指標から遅行指標への波及を順に見る")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

summary = board.summary_frame()
ga4, gsc = board.kgi_frames()
if summary.empty:
    common.empty_state("`daily_summary` にデータがありません。")
    st.stop()

end = board.latest_date(summary)
floor = board.noise_floor()


def week_sum(frame: pd.DataFrame, column: str, offset: int = 0) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    hi = end - pd.Timedelta(days=7 * offset)
    lo = hi - pd.Timedelta(days=7)
    return float(frame[(frame["date"] > lo) & (frame["date"] <= hi)][column].fillna(0).sum())


rate_now = board.window_mean(summary, "mention_rate_all", end)
rate_prev = board.window_mean(summary, "mention_rate_all", end - pd.Timedelta(days=7))
ai_now, ai_prev = week_sum(ga4, "sessions"), week_sum(ga4, "sessions", 1)
clicks_now, clicks_prev = week_sum(gsc, "clicks"), week_sum(gsc, "clicks", 1)
impressions_now = week_sum(gsc, "impressions")
events_now = week_sum(ga4, "key_events")

st.caption(f"対象週: {end - pd.Timedelta(days=6):%Y-%m-%d} 〜 {end:%Y-%m-%d}")

# --- 波及順序 --------------------------------------------------------------
st.markdown(
    f"""<div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap;
    background:#f6f8fa;border-radius:8px;padding:14px 18px;margin-bottom:8px'>
    <b>言及率</b>(先行)<span style='color:{common.INK_MUTED}'>→</span>
    <b>指名検索</b><span style='color:{common.INK_MUTED}'>→</span>
    <b>AI経由流入</b><span style='color:{common.INK_MUTED}'>→</span>
    <b>問い合わせ</b>(遅行)
    </div>""",
    unsafe_allow_html=True,
)
st.caption(
    "AIに言及されるようになってから指名検索・流入に出るまでには時間差がある。"
    "左が動いていないのに右だけを見ても判断できない。"
)

cards = st.columns(4)
# 率の差分は生値ではなくポイントで出す(0.071 では読めない)
rate_delta = None
if rate_now is not None and rate_prev is not None:
    points = round((rate_now - rate_prev) * 100, 1)
    rate_delta = "±0" if abs(points) < 0.05 else f"{points:+.1f}ポイント"
board.metric_card(cards[0], "言及率(7日平均)",
                  "—" if rate_now is None else f"{rate_now:.0%}",
                  rate_delta, note="先行指標")
board.metric_card(cards[1], "指名検索クリック(週計)", f"{clicks_now:.0f}",
                  common.delta_text(clicks_now, clicks_prev, digits=0),
                  note=(f"母数が判断に足りない(週{floor:.0f}未満)"
                        if clicks_now < floor else "母数は判断に足る"))
board.metric_card(cards[2], "AI経由セッション(週計)", f"{ai_now:.0f}",
                  common.delta_text(ai_now, ai_prev, digits=0),
                  note=(f"母数が判断に足りない(週{floor:.0f}未満)"
                        if ai_now < floor else "母数は判断に足る"))
board.metric_card(cards[3], "AI経由の主要イベント(週計)", f"{events_now:.0f}",
                  None, note="遅行指標。母数が小さいうちは0が続く")

st.divider()
st.subheader("週次の推移")
figure = go.Figure()
for frame, column, label, color in [
    (gsc, "clicks", "指名検索クリック", common.PALETTE[0]),
    (gsc, "impressions", "指名検索インプレッション", common.PALETTE[3]),
    (ga4, "sessions", "AI経由セッション", common.PALETTE[2]),
]:
    if frame.empty or column not in frame.columns:
        continue
    daily = frame.groupby("date")[column].sum().sort_index()
    figure.add_trace(go.Scatter(
        x=daily.index, y=common.moving_average(daily), name=label, mode="lines",
        line=dict(color=color, width=2.5), connectgaps=False,
        customdata=daily.values,
        hovertemplate=(f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>"
                       "7日平均 %{y:.1f}<br>当日 %{customdata:.0f}<extra></extra>"),
    ))
figure.update_layout(
    height=340, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(title="件数(7日移動平均)", rangemode="tozero"), xaxis=dict(title=None),
    legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")
st.caption(f"インプレッション週計 {impressions_now:.0f}。母数の目安は週{floor:.0f}。")

board.verdict_panel("R7", board.build_context("R7"))
