"""main.py — 8面レポート構成のエントリポイント(Phase 5 §1).

読み取り専用。Sheetsへの書き込み経路には到達できない。
起動は run_dashboard.bat(または ``streamlit run app/main.py``)。
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
    page_title="LLMO レポート", page_icon="📊", layout="wide",
    initial_sidebar_state="expanded",
)

# 8面が意思決定の順序。詳細2面はそこからの深掘り先で、独立して見るものではない。
REPORT_PAGES = [
    st.Page("faces/r1_summary.py", title="R1 全体サマリ", icon="📋", default=True),
    st.Page("faces/r2_trend.py", title="R2 言及率トレンド", icon="📈"),
    st.Page("faces/r3_negative.py", title="R3 ネガ検知", icon="⚠️"),
    st.Page("faces/r4_coverage.py", title="R4 獲得マップ", icon="🗺️"),
    st.Page("faces/r5_position.py", title="R5 競合ポジション", icon="🎯"),
    st.Page("faces/r6_sources.py", title="R6 情報源分析", icon="🔗"),
    st.Page("faces/r7_kgi.py", title="R7 成果指標", icon="💹"),
    st.Page("faces/r8_actions.py", title="R8 アクションボード", icon="✅"),
]
DETAIL_PAGES = [
    st.Page("views/p3_prompt.py", title="詳細:プロンプト", icon="🔍"),
    st.Page("views/p4_answers.py", title="詳細:回答・差分", icon="📝"),
    st.Page("views/p5_weekly.py", title="詳細:週次所見", icon="🗒️"),
]

with st.sidebar:
    st.markdown("### LLMO レポート")
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
            st.caption("接続先のスプレッドシートが未設定")

    span = data_source.raw_data_span()
    st.caption(f"`data/raw`: {span[0]} 〜 {span[1]}" if span else "`data/raw`: なし")

    st.divider()
    if st.button("キャッシュを更新", width="stretch",
                 help="Sheets の読み取りキャッシュ(10分)を破棄して再取得します"):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "回答全文は `data/raw` を読みます。最新化するには "
        "`git pull`(`run_dashboard.bat` は起動時に自動実行)。"
    )

st.navigation({"レポート": REPORT_PAGES, "詳細": DETAIL_PAGES}).run()
