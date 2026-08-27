"""R1 全体サマリ — 最重要指標カード4枚 + 今週の判定(Phase 5 §1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import board
import common
import data_source
import labels

board.face_header("R1", "全体サマリ", "今週の状態を4つの指標で確認する")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

summary = board.summary_frame()
obs = board.observations()
if summary.empty:
    common.empty_state("`daily_summary` にデータがありません。")
    st.stop()

end = board.latest_date(summary)
sov = board.sov_frame()
position = board.self_position(sov, end)
ga4, gsc = board.kgi_frames()

rate_now = board.window_mean(summary, "mention_rate_all", end)
rate_prev = board.window_mean(summary, "mention_rate_all", end - pd.Timedelta(days=7))
streak = board.negative_streak(obs, end)
week = obs[obs["date"] > end - pd.Timedelta(days=7)] if not obs.empty else obs
negatives = int(week["negative_bool"].sum()) if not week.empty else 0

ai_week = float(ga4[ga4["date"] > end - pd.Timedelta(days=7)]["sessions"].fillna(0).sum()) if not ga4.empty else 0.0
clicks_week = float(gsc[gsc["date"] > end - pd.Timedelta(days=7)]["clicks"].fillna(0).sum()) if not gsc.empty else 0.0

st.caption(f"対象日: {end:%Y-%m-%d}(直近7日 / 前週比)")

cards = st.columns(4)
# 言及率は率なので、差分もポイント表示にする(0.071 では読めない)
rate_delta = None
if rate_now is not None and rate_prev is not None:
    points = round((rate_now - rate_prev) * 100, 1)
    rate_delta = "±0" if abs(points) < 0.05 else f"{points:+.1f}ポイント"
board.metric_card(
    cards[0], "言及率(7日平均)",
    "—" if rate_now is None else f"{rate_now:.0%}", rate_delta,
    help_text="E-1を除く全プロンプト×モデルのうち、言及ありだった比率",
)
# 検知は増えるほど悪いので、色の向きを反転させる
cards[1].metric("ネガティブ検知", f"{streak}日連続" if streak else "検知なし",
                f"直近7日 {negatives}件" if negatives else None,
                delta_color="inverse")
cards[1].caption("旧事業の記述・誤情報の検知")
board.metric_card(
    cards[2], "言及シェア順位(28日)",
    "—" if position["rank"] is None else f"{position['rank']}位",
    None,
    note=f"シェア {position['share']:.0%}" if position["share"] is not None else "",
)
floor = board.noise_floor()
board.metric_card(
    cards[3], "成果指標(KGI)週計",
    f"AI {ai_week:.0f} / 指名 {clicks_week:.0f}",
    None,
    note=("母数が判断に足りない水準" if max(ai_week, clicks_week) < floor
          else "母数は判断に足る水準"),
)

st.divider()
st.subheader("実施中の施策")
actions = board.action_rows()
if actions:
    frame = pd.DataFrame(actions)
    keep = [c for c in ["action_id", "優先度", "内容", "状態", "実施日", "判断期限"]
            if c in frame.columns]
    running = frame[frame["状態"].isin(["実施済み・効果測定中", "承認", "承認待ち"])] \
        if "状態" in frame.columns else frame
    shown = running if not running.empty else frame
    st.dataframe(labels.ja_columns(shown[keep]),
                 width="stretch", hide_index=True)
else:
    st.info("`action_log` にデータがありません。R8を参照してください。")

board.verdict_panel("R1", board.build_context("R1"))
