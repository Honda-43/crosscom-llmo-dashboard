"""P2 SoV分析 — エンティティ別シェア推移と出現ランキング(Phase 4 §2 P2)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
from settings import SELF_ENTITY, TAB_SOV

common.page_header("P2 SoV分析", "競合とのShare of Voice。クロスコムは赤で固定表示")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

sov = common.to_frame(data_source.tab(TAB_SOV), numeric=["mention_count", "observed_total"])
if sov.empty:
    common.empty_state("sov_daily にデータがありません。")
    st.stop()

# --- フィルタ --------------------------------------------------------------
left, right = st.columns([1, 2])
with left:
    pillars = [p for p in ("all", "A", "B") if p in set(sov["pillar"])]
    pillar = st.selectbox("Pillar", pillars,
                          format_func=lambda p: common.PILLAR_LABELS.get(p, p))
with right:
    start, end = common.date_range_picker(sov, key="p2_range", default_days=28)

scoped = sov[sov["pillar"] == pillar]
current = common.slice_dates(scoped, start, end)
prev_start, prev_end = common.previous_window(start, end)
previous = common.slice_dates(scoped, prev_start, prev_end)

if current.empty:
    common.empty_state("選択した期間にデータがありません。")
    st.stop()

st.caption(
    f"対象: {start} 〜 {end}(比較対象の前期間: {prev_start} 〜 {prev_end})"
)

# --- 出現回数ランキング ----------------------------------------------------
totals = current.groupby("entity")["mention_count"].sum()
prev_totals = previous.groupby("entity")["mention_count"].sum() if not previous.empty \
    else pd.Series(dtype=float)
observed = current.groupby("date")["observed_total"].max().sum()

ranking = pd.DataFrame({
    "エンティティ": totals.index,
    "出現回数": totals.values,
    "前期間": [float(prev_totals.get(e, 0)) for e in totals.index],
})
ranking["増減"] = ranking["出現回数"] - ranking["前期間"]
ranking["シェア"] = ranking["出現回数"] / observed if observed else 0.0
ranking = ranking.sort_values("出現回数", ascending=False).reset_index(drop=True)

top_n = st.slider("表示する上位N社", min_value=3, max_value=15, value=8, key="p2_topn")
top_entities = list(ranking["エンティティ"].head(top_n))
if SELF_ENTITY in set(ranking["エンティティ"]) and SELF_ENTITY not in top_entities:
    top_entities.append(SELF_ENTITY)  # 自社は圏外でも必ず表示する

# --- シェア推移 ------------------------------------------------------------
st.subheader("シェア推移")
colors = common.entity_color_map(top_entities)
daily_observed = current.groupby("date")["observed_total"].max()

figure = go.Figure()
for entity in top_entities:
    rows = current[current["entity"] == entity].set_index("date")["mention_count"]
    share = (rows / daily_observed).reindex(daily_observed.index).fillna(0.0)
    is_self = entity == SELF_ENTITY
    figure.add_trace(go.Scatter(
        x=share.index, y=share.values, name=entity, mode="lines+markers",
        line=dict(color=colors[entity], width=3.5 if is_self else 1.8),
        marker=dict(size=6 if is_self else 4),
        hovertemplate=f"{entity}: %{{y:.0%}}<br>%{{x|%Y-%m-%d}}<extra></extra>",
    ))
figure.update_layout(
    height=430, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(tickformat=".0%", title="シェア(出現数 / 観測数)"), xaxis=dict(title=None),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(figure, width="stretch")

# --- ランキング表 ----------------------------------------------------------
st.subheader("出現回数ランキング")
display = ranking.copy()
display["シェア"] = display["シェア"].map(lambda v: f"{v:.1%}")
display["増減"] = display["増減"].map(lambda v: "±0" if v == 0 else f"{v:+.0f}")
display["出現回数"] = display["出現回数"].astype(int)
display["前期間"] = display["前期間"].astype(int)


def highlight_self(row):
    if row["エンティティ"] == SELF_ENTITY:
        return [f"background-color: {common.SELF_COLOR}22; font-weight: 600"] * len(row)
    return [""] * len(row)


st.dataframe(
    display.style.apply(highlight_self, axis=1),
    width="stretch", hide_index=True,
)
st.caption(f"期間内の観測総数(シェアの分母): {int(observed)}")
