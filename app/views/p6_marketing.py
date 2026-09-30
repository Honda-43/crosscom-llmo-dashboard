"""P6 第3観測層 prompt_marketing — 層 × モデル の月次の率(2026-10-01).

54本を月1回だけ観測する層なので、1本ごとの有無は偶然に大きく振れる。
**層単位の率で読む。** 1本ごとの表は参考として別のタブに置く。
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
import marketing
from settings import TAB_MARKETING

common.page_header("P6 第3観測層(購買検討・指名の観測)",
                   "54本・月1回。層 × モデル の社名の出現率と cross-com.jp の引用率")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

rows = data_source.tab(TAB_MARKETING)
rates = marketing.layer_rates(rows)
if not rates:
    common.empty_state("`llm_marketing` にまだ観測がありません(初回は 2026年10月第1週)。")
    st.stop()

months = sorted({c["month"] for c in rates}, reverse=True)
month = st.selectbox("月", months, key="p6_month")
cells = [c for c in rates if c["month"] == month]
layers = [l for l in marketing.LAYER_ORDER if any(c["layer"] == l for c in cells)]
models = [m for m in marketing.MODELS if any(c["model"] == m for c in cells)]
lookup = {(c["layer"], c["model"]): c for c in cells}


def heatmap(metric: str, title: str) -> go.Figure:
    z, text, hover = [], [], []
    for layer in layers:
        z_row, t_row, h_row = [], [], []
        for model in models:
            c = lookup.get((layer, model))
            if not c or not c["n"]:
                z_row.append(None)
                t_row.append("—")
                h_row.append(f"{layer} × {model}<br>観測なし")
                continue
            rate = c[metric] / c["n"]
            z_row.append(rate)
            t_row.append(f"{rate:.0%}<br>({c[metric]}/{c['n']})")
            h_row.append(f"{layer} × {model}<br>{title} {rate:.0%}(観測 {c['n']}本中 {c[metric]}本)")
        z.append(z_row)
        text.append(t_row)
        hover.append(h_row)
    figure = go.Figure(go.Heatmap(
        z=z, x=models, y=layers, zmin=0, zmax=1,
        colorscale=common.SEQUENTIAL, xgap=3, ygap=3,
        text=text, texttemplate="%{text}", textfont=dict(size=14),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title=dict(text=title, side="right"), tickformat=".0%",
                      thickness=14, len=0.9),
    ))
    figure.update_layout(
        height=max(260, 56 * len(layers) + 90), margin=dict(l=10, r=10, t=10, b=40),
        xaxis=dict(title="モデル", tickfont=dict(color=common.INK)),
        yaxis=dict(title=None, autorange="reversed", tickfont=dict(color=common.INK)),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return figure


by_layer, per_prompt = st.tabs(["層 × モデル", "参考:1本ごと"])
with by_layer:
    left, right = st.columns(2)
    with left:
        st.markdown("#### 社名の出現率")
        st.plotly_chart(heatmap("mentioned", "出現率"), width="stretch")
    with right:
        st.markdown("#### cross-com.jp の引用率")
        st.plotly_chart(heatmap("cited_domain", "引用率"), width="stretch")
    st.caption(
        "**1プロンプト月1回の観測のため、層単位の率で読む。** セルは その月に観測できた本数を分母にした率"
        "(欠測・枠不足で見送った分は分母に入れない)。Gemini は枠の残りでしか回さないため、月によって"
        "観測できる本数が層ごとに違う。BOFU(社名を質問に含む層)は出現率が高いのが前提。"
    )

with per_prompt:
    st.caption("参考。1本ごとの有無は月1回の観測で偶然に大きく振れるため、判断は層単位の率で行う。")
    frame = pd.DataFrame(marketing.latest_observations(rows))
    if not frame.empty:
        frame = frame[frame["date"].astype(str).str[:7] == month]
        columns = ["date", "prompt_id", "layer", "model", "mentioned", "is_first",
                   "mention_rank", "cited_domain", "prompt"]
        st.dataframe(frame[[c for c in columns if c in frame.columns]]
                     .sort_values(["prompt_id", "model"]), width="stretch", hide_index=True)
