"""R3 ネガ検知 — モデル別の日次カレンダー + 施策基準線(Phase 5 §1)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source
import verdicts

board.face_header("R3", "ネガ検知", "検知が「止まった日」が施策の効果を示す")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

obs = board.observations()
if obs.empty:
    common.empty_state("llm_observations にデータがありません。")
    st.stop()

# 行 = prompt_id × model。一度でも検知されたものだけを並べる。
obs = obs.copy()
obs["series"] = obs["prompt_id"] + " × " + obs["model"]
fired = obs.groupby(["series", "date"])["negative_bool"].any().reset_index()
active = sorted(fired[fired["negative_bool"]]["series"].unique())
if not active:
    active = sorted(obs[obs["prompt_id"] == "E-1"]["series"].unique()) or [obs["series"].iloc[0]]

all_dates = sorted(obs["date"].unique())
z, hover = [], []
for name in active:
    by_date = fired[fired["series"] == name].set_index("date")["negative_bool"]
    z_row, h_row = [], []
    for day in all_dates:
        if day not in by_date.index:
            z_row.append(None)
            h_row.append(f"{name}<br>{pd.Timestamp(day):%Y-%m-%d}<br>観測なし")
        else:
            hit = bool(by_date.loc[day])
            z_row.append(1 if hit else 0)
            h_row.append(f"{name}<br>{pd.Timestamp(day):%Y-%m-%d}<br>"
                         f"{'検知あり' if hit else '検知なし'}")
    z.append(z_row); hover.append(h_row)

figure = go.Figure(go.Heatmap(
    z=z, x=all_dates, y=active, zmin=0, zmax=1,
    colorscale=[[0.0, common.EMPTY_CELL], [1.0, common.STATUS_ALERT]],
    xgap=2, ygap=3, showscale=False,
    customdata=hover, hovertemplate="%{customdata}<extra></extra>",
))
actions = verdicts.implemented_actions(board.action_rows())
legend = board.action_annotations(figure, actions)
figure.update_layout(
    height=max(240, 54 * len(active) + 140),
    margin=dict(l=10, r=10, t=60, b=40),
    xaxis=dict(title=None, tickformat="%m/%d", tickfont=dict(color=common.INK_MUTED)),
    yaxis=dict(title=None, tickfont=dict(color=common.INK)),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")

end = board.latest_date(obs)
streak = board.negative_streak(obs, end)
st.caption(
    f"<span style='color:{common.STATUS_ALERT}'>■</span> 検知あり / 薄いグレー = 検知なし / "
    f"空白 = 観測なし。破線は実施済みの施策({len(actions)}件)。"
    f"現在の連続検知は{streak}日。",
    unsafe_allow_html=True,
)
if legend:
    st.caption(legend)

board.verdict_panel("R3", board.build_context())
