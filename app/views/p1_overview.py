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
# 主線は7日移動平均。日次の生データは1日の1件で大きく振れるため背景に退かせる。
st.subheader("mention_rate の推移(全期間)")

series = [
    ("mention_rate_all", "全体 (A+B)", "#4c78a8"),
    ("mention_rate_pillar_a", "Pillar A", "#54a24b"),
    ("mention_rate_pillar_b", "Pillar B", "#f58518"),
]
figure = go.Figure()
for column, label, color in series:
    raw = summary[column]
    # 背景線: 凡例からは隠し、ホバーも主線側に集約する
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

figure.update_layout(
    height=420, hovermode="x unified",
    yaxis=dict(tickformat=".0%", title="言及率", rangemode="tozero"),
    xaxis=dict(title=None), margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")
st.caption(
    f"太線は{common.MA_WINDOW}日移動平均、薄い線は日次の生データ。"
    "ホバーで当日値も表示。凡例クリックで系列の表示/非表示を切り替えられる。"
)

st.divider()

observations = common.observations_frame(data_source.tab(TAB_LLM))

# --- 直近7日の観測内訳(ヒートグリッド) ------------------------------------
st.subheader("直近7日の観測内訳(prompt_id × model)")
if observations.empty:
    st.info("llm_observations にデータがありません。")
else:
    recent = observations[observations["date"] > latest - pd.Timedelta(days=7)]
    grid = (
        recent.groupby(["prompt_id", "model"])
        .agg(mentioned=("mention_bool", "sum"), observed=("mention_bool", "size"))
        .reset_index()
    )
    prompts = sorted(grid["prompt_id"].unique())
    models = sorted(grid["model"].unique())
    lookup = {(r.prompt_id, r.model): (int(r.mentioned), int(r.observed))
              for r in grid.itertuples()}

    z, text, hover = [], [], []
    for prompt_id in prompts:
        z_row, t_row, h_row = [], [], []
        for model in models:
            mentioned, observed_days = lookup.get((prompt_id, model), (None, 0))
            z_row.append(mentioned)
            t_row.append("—" if mentioned is None else str(mentioned))
            h_row.append(
                f"{prompt_id} × {model}<br>言及 {mentioned} 日 / 観測 {observed_days} 日"
                if mentioned is not None else f"{prompt_id} × {model}<br>観測なし"
            )
        z.append(z_row); text.append(t_row); hover.append(h_row)

    heat = go.Figure(go.Heatmap(
        z=z, x=models, y=prompts, zmin=0, zmax=7,
        colorscale=common.SEQUENTIAL,
        xgap=3, ygap=3,  # セル間の隙間で境界を作る(枠線を足さない)
        text=text, texttemplate="%{text}",
        textfont=dict(size=15),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title=dict(text="言及日数", side="right"),
                      tickvals=[0, 1, 2, 3, 4, 5, 6, 7], thickness=14, len=0.9),
    ))
    # E-1 は「必ず言及される」前提のプロンプトなので、他と同じ尺度で読ませない。
    if "E-1" in prompts:
        row = prompts.index("E-1")
        heat.add_shape(type="rect", x0=-0.5, x1=len(models) - 0.5,
                       y0=row - 0.5, y1=row + 0.5,
                       line=dict(color=common.INK, width=2.5), fillcolor="rgba(0,0,0,0)")
    heat.update_layout(
        height=max(260, 46 * len(prompts) + 90),
        margin=dict(l=10, r=10, t=10, b=40),
        xaxis=dict(title="model", side="bottom", tickfont=dict(color=common.INK)),
        yaxis=dict(title=None, autorange="reversed", tickfont=dict(color=common.INK)),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(heat, width="stretch")
    st.caption(
        "セルの数字と濃さは直近7日で mention=TRUE だった日数(0日=白 〜 7日=濃)。"
        "**枠線のE-1**はエンティティ質問で必ず言及されるため、他プロンプトとは意味が異なる。"
    )

st.divider()

# --- ネガティブ検知カレンダー ----------------------------------------------
# 「毎日鳴っていること」ではなく「鳴らなくなる日」を読むための図。
BASELINE_DATE = pd.Timestamp("2026-08-11")
BASELINE_LABEL = "8/11 外部プロフィール更新"

st.subheader("ネガティブ検知の推移(8/11外部プロフィール更新の効果測定)")
if observations.empty:
    st.info("llm_observations にデータがありません。")
else:
    fired = (
        observations.groupby(["prompt_id", "date"])["negative_bool"].any().reset_index()
    )
    # 一度でも発火したprompt_idを行にする。将来E-1以外で出れば自動で行が増える。
    active = sorted(fired[fired["negative_bool"]]["prompt_id"].unique())
    if not active:
        active = ["E-1"]  # まだ発火がない期間でも枠は見せる

    all_dates = sorted(observations["date"].unique())
    z, hover = [], []
    for prompt_id in active:
        by_date = fired[fired["prompt_id"] == prompt_id].set_index("date")["negative_bool"]
        z_row, h_row = [], []
        for day in all_dates:
            if day not in by_date.index:
                z_row.append(None)
                h_row.append(f"{prompt_id}<br>{pd.Timestamp(day):%Y-%m-%d}<br>観測なし")
            else:
                hit = bool(by_date.loc[day])
                z_row.append(1 if hit else 0)
                h_row.append(f"{prompt_id}<br>{pd.Timestamp(day):%Y-%m-%d}<br>"
                             f"{'⚠️ 検知あり' if hit else '検知なし'}")
        z.append(z_row); hover.append(h_row)

    calendar = go.Figure(go.Heatmap(
        z=z, x=all_dates, y=active, zmin=0, zmax=1,
        colorscale=[[0.0, common.EMPTY_CELL], [1.0, common.STATUS_ALERT]],
        xgap=2, ygap=3, showscale=False,
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    ))
    calendar.add_vline(
        x=BASELINE_DATE, line=dict(color=common.INK, width=2, dash="dash"),
        annotation_text=BASELINE_LABEL, annotation_position="top",
        annotation_font=dict(color=common.INK, size=12),
    )
    calendar.update_layout(
        height=max(200, 52 * len(active) + 120),
        margin=dict(l=10, r=10, t=46, b=40),
        xaxis=dict(title=None, tickformat="%m/%d", tickfont=dict(color=common.INK_MUTED)),
        yaxis=dict(title=None, tickfont=dict(color=common.INK)),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(calendar, width="stretch")

    after = [d for d in all_dates if pd.Timestamp(d) >= BASELINE_DATE]
    fired_after = fired[(fired["prompt_id"].isin(active)) & (fired["negative_bool"])
                        & (fired["date"] >= BASELINE_DATE)]
    st.caption(
        f"<span style='color:{common.STATUS_ALERT}'>■</span> 検知あり / "
        "薄いグレー = 検知なし / 空白 = 観測なし。"
        f"基準日以降 {len(after)} 日のうち検知 {len(fired_after)} 日。"
        "**検知が止まった日**が外部プロフィール更新の効果を示す。",
        unsafe_allow_html=True,
    )
