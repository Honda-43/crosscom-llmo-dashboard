"""R5 競合ポジション — 散布図 + シェアランキング横棒(Phase 5 §3-1)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source
from settings import SELF_ENTITY

board.face_header("R5", "競合ポジション", "シェアと順位の両方でどこに立っているか")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

sov = board.sov_frame()
obs = board.observations()
if sov.empty:
    common.empty_state("sov_daily にデータがありません。")
    st.stop()

end = board.latest_date(sov)
position = board.self_position(sov, end)
window = sov[(sov["pillar"] == "all")
             & (sov["date"] > end - pd.Timedelta(days=board.LOOKBACK_DAYS))]
recent = sov[(sov["pillar"] == "all")
             & (sov["date"] > end - pd.Timedelta(days=board.WINDOW_DAYS))]

totals = window.groupby("entity")["mention_count"].sum().sort_values(ascending=False)
observed = window.groupby("date")["observed_total"].max().sum()
recent_counts = recent.groupby("entity")["mention_count"].sum()

# 縦軸。自社の順位中央値は llm_observations の rank から取れるが、
# 競合の順位は観測していないため SoV順位を代理として置く。
self_rank_median = None
if not obs.empty:
    ranked = obs[(obs["date"] > end - pd.Timedelta(days=board.LOOKBACK_DAYS))
                 & obs["rank_num"].notna()]
    if not ranked.empty:
        self_rank_median = float(ranked["rank_num"].median())

entities = list(totals.head(10).index)
if SELF_ENTITY in totals.index and SELF_ENTITY not in entities:
    entities.append(SELF_ENTITY)

rows = []
for sov_rank, entity in enumerate(list(totals.index), start=1):
    if entity not in entities:
        continue
    rows.append({
        "entity": entity,
        "share": float(totals[entity] / observed) if observed else 0.0,
        "rank_axis": self_rank_median if entity == SELF_ENTITY else float(sov_rank),
        "recent": float(recent_counts.get(entity, 0)),
        "is_self": entity == SELF_ENTITY,
    })
frame = pd.DataFrame(rows).dropna(subset=["rank_axis"])

st.caption(
    f"対象: {end - pd.Timedelta(days=board.LOOKBACK_DAYS):%Y-%m-%d} 〜 {end:%Y-%m-%d}"
    "(28日)。点の大きさは直近7日の出現数。"
)

if frame.empty:
    common.empty_state("散布図に描けるデータがありません。")
else:
    share_mid = float(frame["share"].median())
    rank_mid = float(frame["rank_axis"].median())

    figure = go.Figure()
    for is_self, group in frame.groupby("is_self"):
        figure.add_trace(go.Scatter(
            x=group["share"], y=group["rank_axis"],
            mode="markers+text" if is_self else "markers",
            text=group["entity"] if is_self else None,
            textposition="top center",
            textfont=dict(color=common.SELF_COLOR, size=13),
            marker=dict(
                size=(group["recent"] * 3 + 14) if is_self else (group["recent"] * 2 + 9),
                color=common.SELF_COLOR if is_self else common.OTHER_COLOR,
                line=dict(width=1.5, color="white"),
            ),
            customdata=list(zip(group["entity"], group["recent"])),
            hovertemplate=("<b>%{customdata[0]}</b><br>シェア %{x:.1%}<br>"
                           "縦軸 %{y:.1f}<br>直近7日 %{customdata[1]:.0f}回<extra></extra>"),
        ))
    figure.add_vline(x=share_mid, line=dict(color=common.INK_MUTED, width=1, dash="dot"))
    figure.add_hline(y=rank_mid, line=dict(color=common.INK_MUTED, width=1, dash="dot"))

    x_hi, x_lo = float(frame["share"].max()), float(frame["share"].min())
    y_hi, y_lo = float(frame["rank_axis"].max()), float(frame["rank_axis"].min())
    for x, y, label in [
        (x_hi, y_lo, "高シェア×上位"), (x_hi, y_hi, "高シェア×下位"),
        (x_lo, y_lo, "低シェア×上位"), (x_lo, y_hi, "低シェア×下位"),
    ]:
        figure.add_annotation(x=x, y=y, text=label, showarrow=False,
                              font=dict(color=common.INK_MUTED, size=11), opacity=0.85)

    figure.update_layout(
        height=470, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
        xaxis=dict(title="言及シェア(28日)", tickformat=".0%",
                   showgrid=True, gridcolor="#eceef1"),
        yaxis=dict(title="順位(上が上位)", autorange="reversed",
                   showgrid=True, gridcolor="#eceef1"),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(figure, width="stretch")
    st.caption(
        "縦軸は自社のみ推薦リスト内の順位中央値。競合の順位は観測していないため"
        "SoV順位を代理として置いている(競合の実順位ではない)。"
    )

st.subheader("シェアランキング(28日)")
ranking = pd.DataFrame({"エンティティ": totals.index,
                        "出現回数": totals.values}).head(10).iloc[::-1]
bars = go.Figure(go.Bar(
    x=ranking["出現回数"], y=ranking["エンティティ"], orientation="h",
    marker=dict(color=[common.SELF_COLOR if e == SELF_ENTITY else common.OTHER_COLOR
                       for e in ranking["エンティティ"]]),
    cliponaxis=False,
    customdata=[[float(v / observed) if observed else 0.0]
                for v in ranking["出現回数"]],
    hovertemplate="%{y}<br>出現 %{x:.0f}回（シェア %{customdata[0]:.1%}）<extra></extra>",
))
bars.update_layout(height=max(260, 32 * len(ranking) + 80),
                   margin=dict(l=10, r=40, t=10, b=40),
                   xaxis=dict(title="出現回数(28日合計)", gridcolor="#eceef1"),
                   yaxis=dict(title=None), plot_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(bars, width="stretch")

board.verdict_panel("R5", board.build_context(
    self_share=position["share"], self_share_rank=position["rank"],
    self_rank_median=self_rank_median, top_competitor=str(position["top"]),
    share_gap_to_top=position["gap"],
))
