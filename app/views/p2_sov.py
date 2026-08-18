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
left, middle, right = st.columns([1, 1, 2])
with left:
    pillars = [p for p in ("all", "A", "B") if p in set(sov["pillar"])]
    pillar = st.selectbox("Pillar", pillars,
                          format_func=lambda p: common.PILLAR_LABELS.get(p, p))
with middle:
    granularity = st.radio("表示粒度", [common.WEEKLY, common.DAILY],
                           horizontal=True, key="p2_gran")
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

# 色は「順位」ではなく「役割」で決める。自社=赤、上位4社=識別色、5位以下=グレー。
competitors_ranked = [e for e in ranking["エンティティ"] if e != SELF_ENTITY]
highlighted = competitors_ranked[:4]


def line_style(entity: str):
    if entity == SELF_ENTITY:
        return common.SELF_COLOR, 3.5, 1.0
    if entity in highlighted:
        return common.PALETTE[highlighted.index(entity)], 2.0, 1.0
    return common.OTHER_COLOR, 1.0, 0.75


# 期間が短いときは移動平均が意味を持たないので生データに落とす(§1)。
raw_only = common.use_raw_only(start, end)
is_weekly = granularity == common.WEEKLY

frame = current.copy()
if is_weekly:
    frame["bucket"] = common.to_week(frame["date"])
    bucket_label, smoothing = "週", None
else:
    frame["bucket"] = frame["date"]
    bucket_label = "日"
    smoothing = None if raw_only else f"{common.MA_WINDOW}日移動平均"

# 分母は日付ごとに1つ(同じ日・同じpillarの全行で同値)なので max をとってから合算する。
observed_by_bucket = (
    frame.groupby(["bucket", "date"])["observed_total"].max()
    .groupby(level="bucket").sum()
)
counts = (
    frame.groupby(["entity", "bucket"])["mention_count"].sum()
    .unstack(fill_value=0.0).reindex(columns=observed_by_bucket.index, fill_value=0.0)
)

figure = go.Figure()
for entity in top_entities:
    if entity not in counts.index:
        continue
    raw_counts = counts.loc[entity]
    share = raw_counts / observed_by_bucket
    plotted = share if (is_weekly or raw_only) else common.moving_average(share)
    color, width, opacity = line_style(entity)
    is_self = entity == SELF_ENTITY

    # 実数(出現数 / 観測数)をホバーに出す(§5)。平滑化していても素の値を見せる。
    customdata = list(zip(raw_counts.values, observed_by_bucket.values, share.values))
    figure.add_trace(go.Scatter(
        x=plotted.index, y=plotted.values, name=entity,
        mode="lines+markers" if is_self else "lines",
        line=dict(color=color, width=width),
        marker=dict(size=7) if is_self else None,
        opacity=opacity, connectgaps=False,
        customdata=customdata,
        hovertemplate=(
            f"<b>{entity}</b><br>%{{x|%Y-%m-%d}} 週<br>" if is_weekly else
            f"<b>{entity}</b><br>%{{x|%Y-%m-%d}}<br>"
        ) + (
            "表示値 %{y:.1%}<br>実数 %{customdata[0]:.0f} / %{customdata[1]:.0f} 観測"
            "（%{customdata[2]:.1%}）<extra></extra>"
        ),
    ))

figure.update_layout(
    height=430, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(tickformat=".0%", title="シェア(出現数 / 観測数)", rangemode="tozero"),
    xaxis=dict(title=None),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")

note = f"{bucket_label}次" + (f"・{smoothing}" if smoothing else "")
if not is_weekly and raw_only:
    note += f"（期間が{common.RAW_ONLY_BELOW_DAYS}日未満のため生データ）"
st.caption(
    f"{note}。<span style='color:{common.SELF_COLOR}'>■</span> クロスコム(太線) / "
    f"上位4社は色付き / 5位以下は<span style='color:{common.OTHER_COLOR}'>グレー細線</span>。"
    "**凡例をクリックすると個別に表示/非表示**を切り替えられる。"
    "ホバーで実数(出現数 / 観測数)を表示。",
    unsafe_allow_html=True,
)

# --- 出現回数ランキング(横棒) ---------------------------------------------
# 量の比較なので棒。ラベルが日本語の社名で長いため横棒にしている。
st.subheader("出現回数ランキング")

chart_rows = ranking.head(max(top_n, 8)).iloc[::-1]  # 上位が上に来るよう反転
bar_colors = [
    common.SELF_COLOR if e == SELF_ENTITY else common.OTHER_COLOR
    for e in chart_rows["エンティティ"]
]
delta_labels = [
    "±0" if d == 0 else f"{d:+.0f}" for d in chart_rows["増減"]
]

bars = go.Figure(go.Bar(
    x=chart_rows["出現回数"], y=chart_rows["エンティティ"], orientation="h",
    marker=dict(color=bar_colors, line=dict(width=0)),
    text=delta_labels, textposition="outside",
    textfont=dict(color=common.INK_MUTED, size=12),
    cliponaxis=False,
    customdata=list(zip(chart_rows["前期間"], chart_rows["シェア"])),
    hovertemplate=("%{y}<br>出現 %{x:.0f}回（前期間 %{customdata[0]:.0f}回）"
                   "<br>シェア %{customdata[1]:.1%}<extra></extra>"),
))
bars.update_layout(
    height=max(260, 34 * len(chart_rows) + 90),
    margin=dict(l=10, r=70, t=10, b=40),
    xaxis=dict(title="出現回数（期間合計）", showgrid=True, gridcolor="#eceef1",
               zeroline=False),
    yaxis=dict(title=None, tickfont=dict(color=common.INK)),
    plot_bgcolor="rgba(0,0,0,0)", bargap=0.35, showlegend=False,
)
st.plotly_chart(bars, width="stretch")
st.caption(
    f"棒の右の数字は前期間比の増減。<span style='color:{common.SELF_COLOR}'>■</span> クロスコム / "
    f"<span style='color:{common.OTHER_COLOR}'>■</span> 競合。"
    f"期間内の観測総数(シェアの分母): {int(observed)}",
    unsafe_allow_html=True,
)

# --- 詳細数値(折りたたみ) -------------------------------------------------
with st.expander("詳細な数値を表で見る"):
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
