"""P3 プロンプト詳細 — prompt_id × model の日次推移とKBF/引用/競合(Phase 4 §2 P3)."""
from __future__ import annotations

import collections

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
from settings import TAB_LLM

common.page_header("P3 プロンプト詳細", "プロンプト単位で mention / rank と語られ方を追う")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

observations = common.observations_frame(data_source.tab(TAB_LLM))
if observations.empty:
    common.empty_state("llm_observations にデータがありません。")
    st.stop()

# --- 選択 ------------------------------------------------------------------
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    prompt_id = st.selectbox("prompt_id", sorted(observations["prompt_id"].unique()))
scoped_prompt = observations[observations["prompt_id"] == prompt_id]
with c2:
    models = sorted(scoped_prompt["model"].unique())
    model = st.selectbox("model", ["(全モデル)"] + models)
with c3:
    start, end = common.date_range_picker(scoped_prompt, key="p3_range", default_days=28)

scoped = scoped_prompt if model == "(全モデル)" else scoped_prompt[scoped_prompt["model"] == model]
scoped = common.slice_dates(scoped, start, end)
if scoped.empty:
    common.empty_state("選択した条件のデータがありません。")
    st.stop()

pillar = scoped["pillar"].iloc[0]
mention_days = int(scoped["mention_bool"].sum())
st.caption(
    f"Pillar {pillar} / 観測 {len(scoped)}件 / 言及 {mention_days}件 "
    f"({mention_days / len(scoped):.0%})"
)

# --- mention / rank の日次推移 ---------------------------------------------
st.subheader("mention / rank の推移")
figure = go.Figure()
for index, model_name in enumerate(sorted(scoped["model"].unique())):
    rows = scoped[scoped["model"] == model_name].sort_values("date")
    color = common.PALETTE[index % len(common.PALETTE)]
    figure.add_trace(go.Scatter(
        x=rows["date"], y=rows["mention_bool"].astype(int), name=f"{model_name}: 言及",
        mode="lines+markers", line=dict(color=color, width=2, shape="hv"),
        yaxis="y", hovertemplate="言及: %{y}<br>%{x|%Y-%m-%d}<extra></extra>",
    ))
    ranked = rows[rows["rank_num"].notna()]
    if not ranked.empty:
        figure.add_trace(go.Scatter(
            x=ranked["date"], y=ranked["rank_num"], name=f"{model_name}: rank",
            mode="markers+lines", yaxis="y2", line=dict(color=color, width=1, dash="dot"),
            marker=dict(size=9, symbol="diamond"),
            hovertemplate="rank: %{y}<br>%{x|%Y-%m-%d}<extra></extra>",
        ))

figure.update_layout(
    height=400, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(title="言及(1=あり)", tickvals=[0, 1], range=[-0.1, 1.1]),
    # rank は小さいほど良いので軸を反転する
    yaxis2=dict(title="rank(上が上位)", overlaying="y", side="right",
                autorange="reversed", dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(figure, width="stretch")

# --- KBF / 引用URL / 競合 ---------------------------------------------------
left, right = st.columns(2)

with left:
    st.subheader("kbf_tags の出現頻度")
    tags = collections.Counter()
    for value in scoped["kbf_tags"]:
        for tag in common.split_list(value):
            tags[tag] += 1
    if tags:
        frame = pd.DataFrame(sorted(tags.items(), key=lambda kv: kv[1]),
                             columns=["KBF", "出現"])
        bar = go.Figure(go.Bar(x=frame["出現"], y=frame["KBF"], orientation="h",
                               marker_color="#4c78a8"))
        bar.update_layout(height=max(220, 40 * len(frame)),
                          margin=dict(l=10, r=10, t=10, b=10), xaxis_title="出現回数")
        st.plotly_chart(bar, width="stretch")
    else:
        st.info("期間内に kbf_tags の記録がありません。")

with right:
    st.subheader("competitors_mentioned 集計")
    competitors = collections.Counter()
    for value in scoped["competitors_mentioned"]:
        for entity in common.competitor_list(value):
            competitors[entity] += 1
    if competitors:
        frame = pd.DataFrame(competitors.most_common(), columns=["競合", "出現回数"])
        frame["出現率"] = (frame["出現回数"] / len(scoped)).map(lambda v: f"{v:.0%}")
        st.dataframe(frame, width="stretch", hide_index=True, height=340)
    else:
        st.info("期間内に競合の記録がありません。")

st.subheader("cited_crosscom_urls(期間内の出現一覧)")
urls = collections.Counter()
last_seen = {}
for _, row in scoped.iterrows():
    for url in common.split_list(row["cited_crosscom_urls"]):
        urls[url] += 1
        last_seen[url] = max(last_seen.get(url, row["date"]), row["date"])
if urls:
    frame = pd.DataFrame(
        [{"URL": u, "出現回数": n, "最終出現": last_seen[u].strftime("%Y-%m-%d")}
         for u, n in urls.most_common()]
    )
    st.dataframe(frame, width="stretch", hide_index=True,
                 column_config={"URL": st.column_config.LinkColumn("URL")})
else:
    st.info(
        "期間内に自社URLの引用記録がありません。"
        "(Gemini は grounding リダイレクトを返すため常に空になります)"
    )
