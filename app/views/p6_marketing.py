"""P6 第3観測層 prompt_marketing — 層 × モデル の月次の率(2026-10-01).

54本を月1回だけ観測する層なので、1本ごとの有無は偶然に大きく振れる。
**層単位の率で読む。** 1本ごとの表は参考として別のタブに置く。
Gemini は月に約28本しか回らない(層ブロック順で毎月固定)ので、層によっては一部だけの観測になる。
前月との差は、**両方の月で観測できたプロンプトだけ**で出す(marketing.compare_months)。
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import data_source
import marketing
from settings import TAB_MARKETING, marketing_prompts_for

common.page_header("P6 第3観測層(購買検討・指名の観測)",
                   "54本・月1回。層 × モデル の社名の出現率と cross-com.jp の引用率")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

rows = data_source.tab(TAB_MARKETING)
# 月によって含むプロンプトが違う(2026-11 から MOFU_L1 に IT研修業界3本)ので、層の全本数は月ごとに数える
rates = marketing.layer_rates(rows, lambda m: marketing.layer_sizes(marketing_prompts_for(m)))
if not rates:
    common.empty_state("`llm_marketing` にまだ観測がありません(初回は 2026年10月第1週)。")
    st.stop()

months = sorted({c["month"] for c in rates}, reverse=True)
month = st.selectbox("月", months, key="p6_month")
cells = [c for c in rates if c["month"] == month]
sizes = marketing.layer_sizes(marketing_prompts_for(month))
layers = [l for l in marketing.LAYER_ORDER if any(c["layer"] == l for c in cells)]
models = [m for m in marketing.MODELS if any(c["model"] == m for c in cells)]
lookup = {(c["layer"], c["model"]): c for c in cells}


def heatmap(metric: str, title: str) -> go.Figure:
    z, text, hover = [], [], []
    for layer in layers:
        z_row, t_row, h_row = [], [], []
        for model in models:
            c = lookup.get((layer, model))
            total = sizes.get(layer, 0)
            if not c or not c["n"]:
                z_row.append(None)
                t_row.append(f"観測なし<br>0/{total}")
                h_row.append(f"{layer} × {model}<br>観測なし(全{total}本)")
                continue
            rate = c[metric] / c["n"]
            part = "<br>一部観測" if c["partial"] else ""
            z_row.append(rate)
            t_row.append(f"{rate:.0%}({c[metric]}/{c['n']})<br>観測 {c['n']}/{total}{part}")
            h_row.append(f"{layer} × {model}<br>{title} {rate:.0%}"
                         f"(観測 {c['n']}本中 {c[metric]}本・層の全本数 {total}本)")
        z.append(z_row)
        text.append(t_row)
        hover.append(h_row)
    figure = go.Figure(go.Heatmap(
        z=z, x=models, y=layers, zmin=0, zmax=1,
        colorscale=common.SEQUENTIAL, xgap=3, ygap=3,
        text=text, texttemplate="%{text}", textfont=dict(size=13),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title=dict(text=title, side="right"), tickformat=".0%",
                      thickness=14, len=0.9),
    ))
    figure.update_layout(
        height=max(280, 70 * len(layers) + 90), margin=dict(l=10, r=10, t=10, b=40),
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
        "**1プロンプト月1回の観測のため、層単位の率で読む。** セルは その月に観測できた本数を分母にした率と、"
        "「観測 本数/層の全本数」。全本数に満たない層は「一部観測」(欠測・枠不足で見送った分は分母に入れない)。"
        "Gemini は月に約28本しか回らず、層ブロック順(L0→BOFU単体→BOFU比較→L1→L2)で毎月固定のため、"
        "L1・L2 は観測されない月が多い(Claude は毎月全本数)。BOFU は社名を質問に含むので出現率が高いのが前提。"
        "**2026年11月から MOFU_L1 に IT研修業界3本(`PM-L1-19`〜`21`)を追加(18本→21本)。**"
        "月ごとの層の率は月によって含むプロンプトが異なる。前月との差は両月で観測したプロンプトのみで計算。"
    )

    previous = marketing.previous_month(month)
    st.markdown(f"#### 前月({previous})との差")
    diff = marketing.compare_months(rows, month, previous)
    if not diff:
        st.caption("両方の月で観測できたプロンプトがありません。")
    else:
        pct = lambda a, n: f"{a / n:.0%}"        # noqa: E731
        st.dataframe(pd.DataFrame([{
            "層": c["layer"], "モデル": c["model"], "両月で観測できた本数": c["n"],
            "出現率(前月)": pct(c["mentioned_prev"], c["n"]),
            "出現率(当月)": pct(c["mentioned_now"], c["n"]),
            "出現率の差": f"{(c['mentioned_now'] - c['mentioned_prev']) / c['n'] * 100:+.0f}pt",
            "引用率(前月)": pct(c["cited_prev"], c["n"]),
            "引用率(当月)": pct(c["cited_now"], c["n"]),
            "引用率の差": f"{(c['cited_now'] - c['cited_prev']) / c['n'] * 100:+.0f}pt",
        } for c in diff]), width="stretch", hide_index=True)
        st.caption("両方の月で観測できた(枠不足で見送った分・欠測でない)プロンプトだけで率を出している。"
                   "片方の月にしか無いプロンプトを混ぜると、観測できた本数の違いが差に見えるため。")

with per_prompt:
    st.caption("参考。1本ごとの有無は月1回の観測で偶然に大きく振れるため、判断は層単位の率で行う。")
    frame = pd.DataFrame(marketing.latest_observations(rows))
    if not frame.empty:
        frame = frame[frame["date"].astype(str).str[:7] == month]
        columns = ["date", "run_date", "prompt_id", "layer", "model", "mentioned", "is_first",
                   "mention_rank", "cited_domain", "extractor_model", "prompt"]
        st.dataframe(frame[[c for c in columns if c in frame.columns]]
                     .sort_values(["prompt_id", "model"]), width="stretch", hide_index=True)
