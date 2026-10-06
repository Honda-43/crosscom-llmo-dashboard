"""R2 言及率トレンド — 移動平均3系列 + 施策実施日の縦線(Phase 5 §1)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source
import labels
import observation_notes
import verdicts

board.face_header("R2", "言及率トレンド", "7日移動平均と、施策を打った日の関係を見る")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

summary = board.summary_frame()
if summary.empty:
    common.empty_state("`daily_summary` にデータがありません。")
    st.stop()

series = [
    ("mention_rate_all", labels.pillar("all"), "#4c78a8"),
    ("mention_rate_pillar_a", labels.pillar("A"), "#54a24b"),
    ("mention_rate_pillar_b", labels.pillar("B"), "#f58518"),
]
figure = go.Figure()
for column, label, color in series:
    raw = summary[column]
    figure.add_trace(go.Scatter(
        x=summary["date"], y=raw, name=f"{label}(日次)", mode="lines",
        line=dict(color=color, width=1), opacity=0.22,
        showlegend=False, hoverinfo="skip",
    ))
    figure.add_trace(go.Scatter(
        x=summary["date"], y=common.moving_average(raw), name=label, mode="lines",
        line=dict(color=color, width=2.8), connectgaps=False,
        customdata=raw.values,
        hovertemplate=(f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>"
                       "7日平均 %{y:.1%}<br>当日 %{customdata:.1%}<extra></extra>"),
    ))

actions = verdicts.implemented_actions(board.action_rows())
legend = board.action_annotations(figure, actions)
intervention_legend = board.intervention_annotations(figure)
# 2026-10-06:言及率の母数が 14本→7本(Claude 停止で Gemini のみ)。前後の水準を単純比較しない
figure.add_vline(
    x=pd.Timestamp(observation_notes.DENOMINATOR_CHANGE_DATE),
    line=dict(color=common.STATUS_ALERT, width=1.5, dash="dashdot"),
    annotation_text=observation_notes.DENOMINATOR_SHORT,
    annotation_position="top right",
    annotation_font=dict(color=common.STATUS_ALERT, size=11),
)

figure.update_layout(
    height=460, hovermode="x unified",
    yaxis=dict(tickformat=".0%", title="言及率", rangemode="tozero"),
    xaxis=dict(title=None), margin=dict(l=10, r=10, t=60, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")
st.caption(
    f"太線は{common.MA_WINDOW}日移動平均、薄い線は日次の生データ。"
    f"破線は実施済みの施策({len(actions)}件)、点線は介入の記録。"
)
st.caption(f"**⚠️ 一点鎖線({observation_notes.DENOMINATOR_SHORT}):{observation_notes.DENOMINATOR_NOTE}**")
if legend:
    st.caption(legend)
if intervention_legend:
    st.caption(f"介入: {intervention_legend}")

board.verdict_panel("R2", board.build_context("R2"))
