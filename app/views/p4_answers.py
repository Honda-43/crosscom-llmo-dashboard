"""P4 回答ビューア・差分 — data/raw の回答全文と2日付のdiff(Phase 4 §2 P4).

Sheets 認証がなくても動く唯一のページ(§3)。回答全文は data/raw から読むため、
changes タブの併記だけが認証を必要とする。
"""
from __future__ import annotations

import difflib
import html
from typing import List

import pandas as pd
import streamlit as st

import common
import data_source
import labels
from settings import TAB_CHANGES

common.page_header("P4 回答ビューア・差分", "回答全文の閲覧と、2日付間の差分")

index = data_source.load_raw_index()
if not index:
    common.empty_state(
        "`data/raw` に回答がありません。`git pull` で最新データを取得してください。"
    )
    st.stop()

frame = pd.DataFrame(index)

# --- 選択 ------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    prompt_id = st.selectbox("プロンプト", sorted(frame["prompt_id"].unique()))
scoped = frame[frame["prompt_id"] == prompt_id]
with c2:
    model = st.selectbox("モデル", sorted(scoped["model"].unique()))
scoped = scoped[scoped["model"] == model].sort_values("date")
dates = list(scoped["date"])

if not dates:
    common.empty_state("該当する回答がありません。")
    st.stop()


def load(date: str) -> dict:
    path = scoped[scoped["date"] == date]["path"].iloc[0]
    return data_source.load_raw_answer(path)


view_tab, diff_tab = st.tabs(["回答全文", "差分(2日付を比較)"])

# --- 回答全文 --------------------------------------------------------------
with view_tab:
    date = st.selectbox("日付", dates, index=len(dates) - 1,
                        key=f"p4_view_date_{prompt_id}_{model}")
    record = load(date)

    meta = st.columns(4)
    meta[0].metric("日付", record.get("date", date))
    meta[1].metric("モデル", record.get("model_name") or record.get("model", model))
    meta[2].metric("引用URL", len(record.get("cited_urls") or []))
    meta[3].metric("文字数", len(record.get("answer") or ""))

    if record.get("error"):
        st.error(f"この観測はエラーで記録されています: {record['error']}")

    st.caption(f"**質問**: {record.get('question', '')}")
    if record.get("cep"):
        st.caption(f"**CEP**: {record['cep']}")

    st.markdown("#### 回答全文")
    st.markdown(
        f"<div style='background:#00000008;border:1px solid #00000018;"
        f"border-radius:8px;padding:16px 20px;max-height:560px;overflow:auto;"
        f"white-space:pre-wrap;line-height:1.7'>"
        f"{html.escape(record.get('answer') or '(空)')}</div>",
        unsafe_allow_html=True,
    )

    urls = record.get("cited_urls") or []
    with st.expander(f"引用URL({len(urls)}件)"):
        if urls:
            st.dataframe(
                pd.DataFrame({"URL": urls}), width="stretch", hide_index=True,
                column_config={"URL": st.column_config.LinkColumn("URL")},
            )
        else:
            st.info("引用URLの記録がありません。")

# --- 差分 ------------------------------------------------------------------
with diff_tab:
    d1, d2 = st.columns(2)
    with d1:
        left_date = st.selectbox("比較元(古い方)", dates,
                                 index=max(0, len(dates) - 8),
                                 key=f"p4_left_{prompt_id}_{model}")
    with d2:
        right_date = st.selectbox("比較先(新しい方)", dates,
                                  index=len(dates) - 1,
                                  key=f"p4_right_{prompt_id}_{model}")

    left_text = (load(left_date).get("answer") or "").splitlines()
    right_text = (load(right_date).get("answer") or "").splitlines()

    diff = list(difflib.unified_diff(left_text, right_text, lineterm="", n=2))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    ratio = difflib.SequenceMatcher(None, "\n".join(left_text), "\n".join(right_text)).ratio()

    stats = st.columns(3)
    stats[0].metric("追加行", added)
    stats[1].metric("削除行", removed)
    stats[2].metric("類似度", f"{ratio:.0%}")

    if not diff:
        st.success("2つの回答は完全に一致しています。")
    else:
        rows: List[str] = []
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                continue
            escaped = html.escape(line)
            if line.startswith("@@"):
                rows.append(
                    f"<div style='color:#6b7280;background:#6b728015;padding:2px 8px'>{escaped}</div>")
            elif line.startswith("+"):
                rows.append(
                    f"<div style='background:#22c55e26;padding:2px 8px'>{escaped}</div>")
            elif line.startswith("-"):
                rows.append(
                    f"<div style='background:#ef444426;padding:2px 8px'>{escaped}</div>")
            else:
                rows.append(f"<div style='padding:2px 8px;opacity:.6'>{escaped}</div>")
        st.markdown(
            "<div style='border:1px solid #00000018;border-radius:8px;"
            "max-height:520px;overflow:auto;font-family:ui-monospace,monospace;"
            "font-size:12.5px;white-space:pre-wrap'>" + "".join(rows) + "</div>",
            unsafe_allow_html=True,
        )

    # --- 同日の changes 行 --------------------------------------------------
    st.markdown("#### 同日の変化(比較先の日付)")
    if not data_source.sheets_available():
        st.info(
            "Google Sheets に未接続のため変化の記録は表示できません。"
            "回答全文と差分は認証なしで利用できます。"
        )
    else:
        changes = data_source.tab(TAB_CHANGES)
        matching = [
            row for row in changes
            if str(row.get("date", "")).strip() == right_date
            and str(row.get("prompt_id", "")).strip() == prompt_id
            and str(row.get("model", "")).strip() == model
        ]
        if matching:
            st.dataframe(
                labels.ja_columns(pd.DataFrame(labels.change_rows(matching))[
                    ["change_type", "before", "after", "detail"]
                ]),
                width="stretch", hide_index=True,
            )
        else:
            st.info(f"{right_date} の {prompt_id} × {model} に記録された変化はありません。")
