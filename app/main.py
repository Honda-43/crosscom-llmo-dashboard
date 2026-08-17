"""main.py — entry point for the local LLMO analysis dashboard (Phase 4).

Read-only: the app never writes to Sheets, never calls an LLM API, and never
touches the daily/weekly pipeline. Launch with ``run_dashboard.bat`` (or
``streamlit run app/main.py``).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402

import data_source  # noqa: E402

st.set_page_config(
    page_title="LLMO 分析ダッシュボード", page_icon="📊", layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = [
    st.Page("views/p1_overview.py", title="P1 概況", icon="📈", default=True),
    st.Page("views/p2_sov.py", title="P2 SoV分析", icon="🥧"),
    st.Page("views/p3_prompt.py", title="P3 プロンプト詳細", icon="🔍"),
    st.Page("views/p4_answers.py", title="P4 回答ビューア・差分", icon="📝"),
    st.Page("views/p5_weekly.py", title="P5 週次所見", icon="🗒️"),
]

with st.sidebar:
    st.markdown("### LLMO 分析ダッシュボード")
    st.caption("cross-com.jp / ローカル専用・読み取り専用")

    status = data_source.credentials_status()
    if status["sample_mode"]:
        st.warning("サンプルデータ表示中", icon="⚠️")
    elif status["service_account"] and status["spreadsheet_id"]:
        st.success("Google Sheets 接続済み", icon="✅")
    else:
        st.error("Google Sheets 未接続", icon="🔌")
        if not status["service_account"]:
            st.caption("`credentials/service_account.json` が未配置")
        if not status["spreadsheet_id"]:
            st.caption("スプレッドシートIDが未設定")

    span = data_source.raw_data_span()
    if span:
        st.caption(f"data/raw: {span[0]} 〜 {span[1]}")
    else:
        st.caption("data/raw: なし")

    st.divider()
    if st.button("キャッシュを更新", width="stretch",
                 help="Sheets の読み取りキャッシュ(10分)を破棄して再取得します"):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "回答全文は `data/raw` を読みます。最新化するには "
        "`git pull`(run_dashboard.bat は起動時に自動実行)。"
    )

st.navigation(PAGES).run()
