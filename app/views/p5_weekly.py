"""P5 週次所見 — weekly_reports の一覧と本文、stats.json の主要数値(Phase 4 §2 P5)."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import common
import data_source
import labels
from settings import TAB_WEEKLY

common.page_header("P5 週次所見", "週次レポート本文と、その根拠になった統計値")

reports = data_source.load_stats_reports()  # data/reports/*.json はローカルで常に読める

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    if reports:
        st.divider()
        st.subheader("`data/reports` のみ表示(認証不要)")
        date = st.selectbox("日付", sorted(reports, reverse=True), key="p5_local")
        st.json(reports[date], expanded=False)
    st.stop()

rows = data_source.tab(TAB_WEEKLY)
if not rows:
    common.empty_state(
        "`weekly_reports` にデータがありません。"
        "GitHub の Actions から週次のワークフローを実行してください。"
    )
    st.stop()

rows = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)
dates = [str(r.get("date", "")) for r in rows]

left, right = st.columns([1, 3])
with left:
    st.markdown("#### レポート一覧")
    selected = st.radio("日付", dates, key="p5_date", label_visibility="collapsed")
    st.caption(f"{len(dates)} 週分")

with right:
    record = next(r for r in rows if str(r.get("date", "")) == selected)
    report_md = record.get("report_md") or ""

    fired = []
    stats = None
    raw_stats = record.get("stats_json") or ""
    try:
        stats = json.loads(raw_stats) if raw_stats else None
    except json.JSONDecodeError:
        stats = None
    if stats:
        fired = stats.get("fired_rules") or []

    header = st.columns(3)
    header[0].metric("対象週", selected)
    header[1].metric("発火ルール", f"{len(fired)} 件")
    header[2].metric("判定不能", f"{len(stats.get('insufficient_rules', [])) if stats else 0} 件")
    if fired:
        st.caption("発火: " + " / ".join(f"`{r}`" for r in fired))

    st.divider()
    if report_md.strip():
        st.markdown(report_md)
    else:
        st.info("この週の本文は空です。")

st.divider()

# --- stats.json の主要数値(折りたたみ) -----------------------------------
local_stats = reports.get(selected)
source_stats = local_stats or stats

with st.expander("週次統計の主要数値", expanded=False):
    if not source_stats:
        st.info("この週の統計データが見つかりません。")
    else:
        origin = ("`data/reports`(ローカル・全文)" if local_stats
                  else "`weekly_reports` タブ")
        st.caption(f"出典: {origin}")

        rate = source_stats.get("mention_rate", {})
        cols = st.columns(3)
        for col, (key, label) in zip(cols, [
            ("all", "言及率 全体"),
            ("pillar_a", labels.pillar("A")),
            ("pillar_b", labels.pillar("B")),
        ]):
            series = rate.get(key, {})
            value = series.get("this_week")
            col.metric(label, "—" if value is None else f"{value:.0%}",
                       common.delta_text(value, series.get("prev_week")))

        kgi = source_stats.get("kgi", {})
        if kgi:
            st.markdown("**成果指標(KGI)週計**")
            kgi_rows = []
            for key in ("ai_sessions", "ai_key_events", "branded_clicks",
                        "branded_impressions"):
                series = kgi.get(key)
                if isinstance(series, dict):
                    kgi_rows.append({
                        "指標": labels.column(key), "今週": series.get("this_week"),
                        "前週": series.get("prev_week"), "差分": series.get("delta"),
                        "ノイズ域": "⚠️" if series.get("noise_zone") else "",
                    })
            if kgi_rows:
                st.dataframe(pd.DataFrame(kgi_rows), width="stretch",
                             hide_index=True)
            if kgi.get("noise_zone_metrics"):
                st.caption(
                    f"⚠️ ノイズ域(週計 {kgi.get('noise_floor')} 未満): "
                    + ", ".join(labels.column(m)
                                for m in kgi["noise_zone_metrics"])
                    + " — 増減は判断材料にしない"
                )

        rules = source_stats.get("rules") or []
        if rules:
            st.markdown("**ルール判定**")
            st.dataframe(
                pd.DataFrame([
                    {"ルール番号": r.get("rule_id"),
                     "判定": labels.status(r.get("status")),
                     "内容": r.get("detail", "")}
                    for r in rules
                ]),
                width="stretch", hide_index=True,
            )

        top = (source_stats.get("sov", {}).get("all", {}) or {}).get("entities") or []
        if top:
            st.markdown("**言及シェア上位(全体)**")
            st.dataframe(
                labels.ja_columns(
                    pd.DataFrame(top)[["entity", "mention_count", "share", "delta"]]),
                width="stretch", hide_index=True,
            )

        st.markdown("**統計データ全文**")
        st.json(source_stats, expanded=False)
