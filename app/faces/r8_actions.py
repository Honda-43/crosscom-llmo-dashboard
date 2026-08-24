"""R8 アクションボード — action_log の一覧と状態(Phase 5 §4).

状態の変更はシート上で行う運用のため、アプリからは書き込まない。
ここは「いま何が動いていて、何を決める必要があるか」を読む面。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import board
import common
import data_source
import verdicts
from settings import TAB_ACTION_LOG, spreadsheet_url

board.face_header("R8", "アクションボード", "施策の状態と、次に決めること")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

rows = board.action_rows()
if not rows:
    common.empty_state(
        "action_log にデータがありません。"
        "`cd src && python action_log.py --seed` で初期データを投入してください。"
    )
    st.stop()

frame = pd.DataFrame(rows)
today = dt.date.today()

STATUS_ORDER = [
    verdicts.STATUS_MEASURING, verdicts.STATUS_APPROVED, verdicts.STATUS_AWAITING,
    verdicts.STATUS_PROPOSED, verdicts.STATUS_ON_HOLD, verdicts.STATUS_DONE,
    verdicts.STATUS_REJECTED,
]

counts = frame["状態"].value_counts().to_dict() if "状態" in frame.columns else {}
cards = st.columns(4)
board.metric_card(cards[0], "効果測定中",
                  f"{counts.get(verdicts.STATUS_MEASURING, 0)} 件", None,
                  note="実施済み。判断期限まで観測する")
board.metric_card(cards[1], "承認待ち・提案中",
                  f"{counts.get(verdicts.STATUS_AWAITING, 0) + counts.get(verdicts.STATUS_PROPOSED, 0)} 件",
                  None, note="承認するかを決める")
board.metric_card(cards[2], "保留",
                  f"{counts.get(verdicts.STATUS_ON_HOLD, 0)} 件", None,
                  note="着手時期を決める")
board.metric_card(cards[3], "完了",
                  f"{counts.get(verdicts.STATUS_DONE, 0)} 件", None)


def deadline_state(value) -> str:
    day = verdicts._date(value)
    if day is None:
        return ""
    remaining = (day - today).days
    if remaining < 0:
        return f"期限超過 {abs(remaining)}日"
    if remaining <= 7:
        return f"あと{remaining}日"
    return f"あと{remaining}日"


st.divider()
st.subheader("施策一覧")

display = frame.copy()
if "判断期限" in display.columns:
    display["期限まで"] = display["判断期限"].map(deadline_state)
if "状態" in display.columns:
    display["_order"] = display["状態"].map(
        lambda s: STATUS_ORDER.index(s) if s in STATUS_ORDER else len(STATUS_ORDER))
    display = display.sort_values(["_order", "action_id"]).drop(columns=["_order"])

columns = [c for c in ["action_id", "優先度", "内容", "対象", "根拠rule_id",
                       "状態", "提案日", "実施日", "判断期限", "期限まで"]
           if c in display.columns]


def highlight(row):
    status = str(row.get("状態", ""))
    if "期限超過" in str(row.get("期限まで", "")):
        return [f"background-color: {common.STATUS_ALERT}18"] * len(row)
    if status in (verdicts.STATUS_PROPOSED, verdicts.STATUS_AWAITING):
        return ["background-color: #fff7e6"] * len(row)
    if status == verdicts.STATUS_DONE:
        return ["color: #9aa0a6"] * len(row)
    return [""] * len(row)


st.dataframe(display[columns].style.apply(highlight, axis=1),
             width="stretch", hide_index=True)

url = spreadsheet_url()
st.caption(
    "状態の変更はスプレッドシートの `action_log` タブで直接行う"
    "(このアプリからは書き込まない)。"
    + (f" [シートを開く]({url})" if url else "")
)

with st.expander("状態の意味"):
    st.markdown(
        "- **提案中**: 週次所見が自動で追加した候補。まだ人が見ていない\n"
        "- **承認待ち**: 検討対象として残したもの\n"
        "- **承認**: やると決めたが未着手\n"
        "- **実施済み・効果測定中**: 実施済み。R2・R3に縦線が出る\n"
        "- **完了**: 効果が確認できた、または対応を終えた\n"
        "- **却下 / 保留**: やらない / 時期を待つ"
    )

board.verdict_panel("R8", board.build_context())
