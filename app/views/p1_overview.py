"""P1 概況 — スコアカードと mention_rate の全期間推移(Phase 4 §2 P1)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
from settings import SELF_ENTITY, TAB_GA4, TAB_GSC, TAB_LLM, TAB_SOV, TAB_SUMMARY

common.page_header("P1 概況", "直近7日の状態と、mention_rate の全期間推移")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

summary = common.to_frame(
    data_source.tab(TAB_SUMMARY),
    numeric=["mention_rate_all", "mention_rate_pillar_a", "mention_rate_pillar_b",
             "negative_flag_count", "ai_sessions", "branded_clicks"],
)
if summary.empty:
    common.empty_state("daily_summary にデータがありません。")
    st.stop()

latest = summary["date"].max()
this_week = summary[summary["date"] > latest - pd.Timedelta(days=7)]
prev_week = summary[(summary["date"] <= latest - pd.Timedelta(days=7))
                    & (summary["date"] > latest - pd.Timedelta(days=14))]

st.caption(
    f"直近7日: {this_week['date'].min():%Y-%m-%d} 〜 {latest:%Y-%m-%d}"
    f"({len(this_week)}日) / 前週比較: {len(prev_week)}日"
)


def mean_of(frame: pd.DataFrame, column: str):
    values = frame[column].dropna()
    return round(float(values.mean()), 4) if len(values) else None


# --- 上段スコアカード ------------------------------------------------------
row1 = st.columns(3)
for col, (label, column) in zip(row1, [
    ("mention_rate 全体", "mention_rate_all"),
    ("mention_rate Pillar A", "mention_rate_pillar_a"),
    ("mention_rate Pillar B", "mention_rate_pillar_b"),
]):
    current, previous = mean_of(this_week, column), mean_of(prev_week, column)
    col.metric(label,
               "—" if current is None else f"{current:.0%}",
               common.delta_text(current, previous))

row2 = st.columns(4)

# SoV首位
sov = common.to_frame(data_source.tab(TAB_SOV), numeric=["mention_count", "observed_total"])
top_label, top_delta = "—", None
if not sov.empty:
    window = sov[(sov["pillar"] == "all") & (sov["date"] > latest - pd.Timedelta(days=7))]
    prev = sov[(sov["pillar"] == "all")
               & (sov["date"] <= latest - pd.Timedelta(days=7))
               & (sov["date"] > latest - pd.Timedelta(days=14))]
    if not window.empty:
        totals = window.groupby("entity")["mention_count"].sum().sort_values(ascending=False)
        prev_totals = prev.groupby("entity")["mention_count"].sum() if not prev.empty else {}
        entity = totals.index[0]
        top_label = f"{entity}"
        top_delta = common.delta_text(
            float(totals.iloc[0]), float(prev_totals.get(entity, 0)), digits=0
        )
row2[0].metric("SoV首位(直近7日・全体)", top_label, top_delta,
               help="mention_count の合計が最大のエンティティ")

# negative_flag
neg_this = this_week["negative_flag_count"].dropna().sum()
neg_prev = prev_week["negative_flag_count"].dropna().sum()
row2[1].metric("negative_flag(直近7日)", f"{int(neg_this)} 件",
               common.delta_text(float(neg_this), float(neg_prev), digits=0),
               delta_color="inverse")

# KGI — noise_zone は週次エンジンと同じ閾値で判定する
try:
    from rules_engine import load_thresholds

    noise_floor = float((load_thresholds().get("kgi") or {}).get("noise_floor", 10))
except Exception:  # noqa: BLE001
    noise_floor = 10.0


def kgi_metric(col, label: str, rows, field: str):
    frame = common.to_frame(rows, numeric=[field])
    if frame.empty:
        col.metric(label, "—")
        return
    current = float(frame[(frame["date"] > latest - pd.Timedelta(days=7))][field].sum())
    previous = float(frame[(frame["date"] <= latest - pd.Timedelta(days=7))
                           & (frame["date"] > latest - pd.Timedelta(days=14))][field].sum())
    col.metric(label, f"{current:.0f}", common.delta_text(current, previous, digits=0))
    if current < noise_floor:
        col.caption(f"⚠️ ノイズ域(週計 {noise_floor:.0f} 未満)— 増減は判断材料にしない")


kgi_metric(row2[2], "AI経由セッション(週計)", data_source.tab(TAB_GA4), "sessions")
kgi_metric(row2[3], "指名検索クリック(週計)", data_source.tab(TAB_GSC), "clicks")

st.divider()

# --- 下段:mention_rate 3系列の全期間推移 --------------------------------
st.subheader("mention_rate の推移(全期間)")
show_ma = st.checkbox("7日移動平均を表示", value=True)

series = [
    ("mention_rate_all", "全体 (A+B)", "#4c78a8"),
    ("mention_rate_pillar_a", "Pillar A", "#54a24b"),
    ("mention_rate_pillar_b", "Pillar B", "#f58518"),
]
figure = go.Figure()
for column, label, color in series:
    figure.add_trace(go.Scatter(
        x=summary["date"], y=summary[column], name=label, mode="lines",
        line=dict(color=color, width=1), opacity=0.35 if show_ma else 1.0,
        hovertemplate=f"{label}: %{{y:.0%}}<br>%{{x|%Y-%m-%d}}<extra></extra>",
    ))
    if show_ma:
        figure.add_trace(go.Scatter(
            x=summary["date"], y=summary[column].rolling(7, min_periods=1).mean(),
            name=f"{label}(7日移動平均)", mode="lines",
            line=dict(color=color, width=2.5),
            hovertemplate=f"{label} 7日平均: %{{y:.0%}}<extra></extra>",
        ))

figure.update_layout(
    height=420, hovermode="x unified", yaxis=dict(tickformat=".0%", title="言及率"),
    xaxis=dict(title=None), margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(figure, width="stretch")

with st.expander("直近7日の観測内訳(prompt_id × model)"):
    observations = common.observations_frame(data_source.tab(TAB_LLM))
    if observations.empty:
        st.info("llm_observations にデータがありません。")
    else:
        recent = observations[observations["date"] > latest - pd.Timedelta(days=7)]
        matrix = (
            recent.groupby(["prompt_id", "model"])
            .agg(言及日数=("mention_bool", "sum"), 観測日数=("mention_bool", "size"))
            .reset_index()
        )
        matrix["言及日数"] = matrix["言及日数"].astype(int)
        st.dataframe(matrix, width="stretch", hide_index=True)
