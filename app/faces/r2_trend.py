"""R2 言及率トレンド — 移動平均3系列 + 施策実施日の縦線(Phase 5 §1)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source
import labels
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
    f"破線は実施済みの施策({len(actions)}件)。"
)
if legend:
    st.caption(legend)

board.verdict_panel("R2", board.build_context("R2"))
