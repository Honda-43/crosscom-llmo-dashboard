"""P3 プロンプト詳細 — prompt_id × model の日次推移とKBF/引用/競合(Phase 4 §2 P3)."""
from __future__ import annotations

import collections

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import common
import data_source
import labels
from settings import TAB_LLM

common.page_header("P3 プロンプト詳細",
                   "プロンプト単位で言及と順位、語られ方を追う")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

observations = common.observations_frame(data_source.tab(TAB_LLM))
if observations.empty:
    common.empty_state("`llm_observations` にデータがありません。")
    st.stop()

# --- 選択 ------------------------------------------------------------------
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    prompt_id = st.selectbox("プロンプト", sorted(observations["prompt_id"].unique()))
scoped_prompt = observations[observations["prompt_id"] == prompt_id]
with c2:
    models = sorted(scoped_prompt["model"].unique())
    model = st.selectbox("モデル", ["(全モデル)"] + models)
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
    f"{labels.pillar(pillar)} / 観測 {len(scoped)}件 / 言及 {mention_days}件 "
    f"({mention_days / len(scoped):.0%})"
)

# --- rank の推移 + mention の帯 ---------------------------------------------
# 順位と言及は尺度が違うので同じ軸に重ねない。上段=順位(欠測は線を繋がない)、
# 下段=言及の有無を帯で表す。
st.subheader("順位の推移と言及の有無")

models_in_view = sorted(scoped["model"].unique())
all_days = pd.Index(sorted(scoped["date"].unique()), name="date")

figure = make_subplots(
    rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.06,
)

for index, model_name in enumerate(models_in_view):
    rows = scoped[scoped["model"] == model_name].set_index("date").sort_index()
    color = common.PALETTE[index % len(common.PALETTE)]

    # 観測のない日・言及のない日は None にして線を途切れさせる(§4)
    rank_series = rows["rank_num"].reindex(all_days)
    mentioned = rows["mention_bool"].reindex(all_days)
    hover_state = [
        "観測なし" if pd.isna(m) else ("言及あり・リスト外" if m and pd.isna(r)
                                     else ("言及あり" if m else "言及なし"))
        for m, r in zip(mentioned, rank_series)
    ]
    figure.add_trace(go.Scatter(
        x=all_days, y=rank_series, name=model_name, mode="lines+markers",
        line=dict(color=color, width=2), marker=dict(size=8),
        connectgaps=False,  # 欠測日は繋がない
        customdata=hover_state,
        hovertemplate=("<b>%{fullData.name}</b><br>%{x|%Y-%m-%d}<br>"
                       "%{y:.0f}位（%{customdata}）<extra></extra>"),
    ), row=1, col=1)

# --- 言及の帯(ストリップ) ---
strip_z, strip_hover = [], []
for model_name in models_in_view:
    rows = scoped[scoped["model"] == model_name].set_index("date").sort_index()
    mentioned = rows["mention_bool"].reindex(all_days)
    strip_z.append([None if pd.isna(v) else (1 if v else 0) for v in mentioned])
    strip_hover.append([
        f"{model_name}<br>{pd.Timestamp(d):%Y-%m-%d}<br>"
        + ("観測なし" if pd.isna(v) else ("言及あり" if v else "言及なし"))
        for d, v in zip(all_days, mentioned)
    ])

figure.add_trace(go.Heatmap(
    z=strip_z, x=all_days, y=models_in_view, zmin=0, zmax=1,
    colorscale=[[0.0, common.EMPTY_CELL], [1.0, common.PALETTE[0]]],
    xgap=1, ygap=3, showscale=False,
    customdata=strip_hover, hovertemplate="%{customdata}<extra></extra>",
), row=2, col=1)

figure.update_layout(
    height=470, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
    plot_bgcolor="rgba(0,0,0,0)",
)
# 順位は小さいほど良いので軸を反転する
figure.update_yaxes(title="順位(上が上位)", autorange="reversed", dtick=1, row=1, col=1)
figure.update_yaxes(title=None, row=2, col=1)
figure.update_xaxes(title=None, row=2, col=1)
st.plotly_chart(figure, width="stretch")
st.caption(
    "上段: 順位の推移。**言及がない日・観測がない日は線を繋いでいない**"
    "(途切れ = そこで推薦リストから消えている)。"
    f"下段: 言及の有無(<span style='color:{common.PALETTE[0]}'>■</span> 言及あり / "
    "薄いグレー = 言及なし / 空白 = 観測なし)。",
    unsafe_allow_html=True,
)

# --- KBF / 引用URL / 競合 ---------------------------------------------------
left, right = st.columns(2)

with left:
    st.subheader("KBFの出現頻度")
    tags = collections.Counter()
    for value in scoped["kbf_tags"]:
        for tag in common.split_list(value):
            tags[tag] += 1
    if tags:
        frame = pd.DataFrame(sorted(tags.items(), key=lambda kv: kv[1]),
                             columns=["KBF", "出現"])
        observations_in_view = len(scoped)
        bar = go.Figure(go.Bar(
            x=frame["出現"], y=frame["KBF"], orientation="h",
            marker_color=common.PALETTE[0],
            customdata=[[observations_in_view] for _ in range(len(frame))],
            hovertemplate=("%{y}<br>%{x:.0f} 回 / %{customdata[0]} 観測"
                           "<extra></extra>"),
        ))
        bar.update_layout(height=max(220, 40 * len(frame)),
                          margin=dict(l=10, r=10, t=10, b=10), xaxis_title="出現回数",
                          plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(bar, width="stretch")
    else:
        st.info("期間内にKBFの記録がありません。")

with right:
    st.subheader("競合の出現集計")
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

st.subheader("自社URLの引用(期間内の出現一覧)")
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
        "(Gemini は解決できない形式のリダイレクトURLを返すため常に空になります)"
    )
