"""R6 情報源分析 — E-1引用の推移 + 不在引用元(Phase 5 §3-2)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import citation_gap
import common
import data_source

board.face_header("R6", "情報源分析", "AIが見ている場所と、そこに自社が載っていない場所")

obs_rows = data_source.tab("llm_observations") if data_source.sheets_available() else []
raw_records = citation_gap.load_raw_observations()

if not raw_records:
    common.empty_state("`data/raw` に回答がありません。`git pull` で取得してください。")
    st.stop()

# --- E-1 の自社URL引用の推移 ------------------------------------------------
st.subheader("E-1 が引用した自社URLの推移")
obs = board.observations() if data_source.sheets_available() else pd.DataFrame()
if obs.empty:
    st.info("Google Sheets に未接続のため推移は表示できません(下の集計は利用できます)。")
else:
    entity = obs[obs["prompt_id"] == "E-1"].copy()
    if entity.empty:
        st.info("E-1 の観測がありません。")
    else:
        entity["url_count"] = entity["cited_crosscom_urls"].map(
            lambda v: len(common.split_list(v)))
        daily = entity.groupby(["date", "model"])["url_count"].sum().reset_index()
        figure = go.Figure()
        for index, model in enumerate(sorted(daily["model"].unique())):
            rows = daily[daily["model"] == model]
            figure.add_trace(go.Scatter(
                x=rows["date"], y=rows["url_count"], name=model, mode="lines+markers",
                line=dict(color=common.PALETTE[index % len(common.PALETTE)], width=2),
                hovertemplate=f"<b>{model}</b><br>%{{x|%Y-%m-%d}}<br>"
                              "自社URL %{y:.0f}件<extra></extra>",
            ))
        figure.update_layout(
            height=300, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
            yaxis=dict(title="引用された自社URL数", rangemode="tozero"),
            xaxis=dict(title=None), plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
        )
        st.plotly_chart(figure, width="stretch")
        st.caption("Gemini は引用URLを解決できない形式で返すため0件が続く。")

# --- 引用元の3分類 ----------------------------------------------------------
st.divider()
st.subheader("引用元ドメインの3分類")
result = citation_gap.classify(raw_records, citation_gap.mention_map(obs_rows))
rows = result["rows"]

if not rows:
    common.empty_state(
        "分類できる引用がありません。llm_observations が未接続だと"
        "「自社が言及されたか」が判定できないため分類できません。"
    )
    st.stop()

counts = {c: sum(1 for r in rows if r["category"] == c)
          for c in (citation_gap.CATEGORY_SELF, citation_gap.CATEGORY_SHARED,
                    citation_gap.CATEGORY_ABSENT)}
cards = st.columns(3)
for col, (category, note) in zip(cards, [
    (citation_gap.CATEGORY_SELF, "自社ドメイン"),
    (citation_gap.CATEGORY_SHARED, "自社言及ありの回答にも出る外部"),
    (citation_gap.CATEGORY_ABSENT, "自社不在の回答にのみ出る外部"),
]):
    board.metric_card(col, category, f"{counts[category]} 件", None, note=note)

absent = [r for r in rows if r["category"] == citation_gap.CATEGORY_ABSENT]
if absent:
    st.markdown("#### 掲載依頼先の候補")
    st.caption(
        "自社が言及されていない回答でのみ引用されている情報源。"
        "AIはこの場所を見て答えているが、そこに自社が載っていない。"
    )
    frame = pd.DataFrame([
        {"ドメイン": r["domain"], "引用回数": r["cited_count"],
         "登場プロンプト": r["prompts"]}
        for r in absent[:15]
    ])
    st.dataframe(frame, width="stretch", hide_index=True,
                 column_config={"ドメイン": st.column_config.TextColumn(width="medium")})

with st.expander("すべての引用元(分類別)"):
    st.dataframe(
        pd.DataFrame([
            {"ドメイン": r["domain"], "分類": r["category"], "引用回数": r["cited_count"],
             "自社言及あり": r["cited_with_self"], "自社不在": r["cited_without_self"],
             "登場プロンプト": r["prompts"]}
            for r in rows
        ]),
        width="stretch", hide_index=True,
    )
st.caption(
    f"評価できた観測 {result['evaluated_observations']}件 / "
    f"解決できない引用 {result['unresolved_citations']}件(Geminiのリダイレクト)。"
)

self_rows = [r for r in rows if r["category"] == citation_gap.CATEGORY_SELF]
board.verdict_panel("R6", board.build_context(
    "R6",
    absent_domains=len(absent),
    top_absent_domain=absent[0]["domain"] if absent else "—",
    top_absent_count=absent[0]["cited_count"] if absent else 0,
    self_domain_count=sum(r["cited_count"] for r in self_rows),
))
