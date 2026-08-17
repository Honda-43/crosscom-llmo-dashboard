"""common.py — shared helpers for the dashboard pages (parsing, chart theme).

Parsing reuses the pipeline's own helpers (``analyze_diff`` / ``normalize``) so
that the app and the weekly rules engine agree on what a row means. If the
dashboard rolled its own parser the two would drift.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import streamlit as st

import data_source
from analyze_diff import parse_bool, parse_rank, split_list  # noqa: F401
from normalize import resolve_entity
from settings import SELF_ENTITY

# Our own colour, held constant everywhere so クロスコム is instantly findable.
SELF_COLOR = "#e45756"
PALETTE = [
    "#4c78a8", "#54a24b", "#f58518", "#72b7b2", "#b279a2",
    "#9d755d", "#eeca3b", "#bab0ac", "#ff9da6", "#79706e",
]

PILLAR_LABELS = {"all": "全体 (A+B)", "A": "Pillar A", "B": "Pillar B"}


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if data_source.sample_mode():
        st.warning(
            "**サンプルデータ表示中** — Google Sheets には接続していません。"
            "実データを見るには `credentials/service_account.json` を配置し、"
            "`LLMO_DASHBOARD_SAMPLE` を解除して再起動してください。",
            icon="⚠️",
        )


def to_num(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_frame(rows: Sequence[Dict[str, Any]], numeric: Sequence[str] = ()) -> pd.DataFrame:
    """Rows -> DataFrame with a parsed ``date`` column and numeric coercion."""
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def date_range_picker(frame: pd.DataFrame, key: str, default_days: int = 28):
    """A start/end picker bounded by the data actually present."""
    if frame.empty:
        return None, None
    lo = frame["date"].min().date()
    hi = frame["date"].max().date()
    default_lo = max(lo, hi - dt.timedelta(days=default_days - 1))
    chosen = st.date_input(
        "期間", value=(default_lo, hi), min_value=lo, max_value=hi, key=key,
    )
    if isinstance(chosen, tuple) and len(chosen) == 2:
        return chosen[0], chosen[1]
    return default_lo, hi


def slice_dates(frame: pd.DataFrame, start, end) -> pd.DataFrame:
    if frame.empty or start is None:
        return frame
    mask = (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))
    return frame[mask]


def previous_window(start, end):
    """The equally long window immediately before [start, end]."""
    span = (end - start).days + 1
    return start - dt.timedelta(days=span), start - dt.timedelta(days=1)


def delta_text(current: Optional[float], previous: Optional[float],
               digits: int = 3) -> Optional[str]:
    if current is None or previous is None:
        return None
    diff = round(current - previous, digits)
    if diff == 0:
        return "±0"
    return f"{diff:+g}"


def entity_color_map(entities: Iterable[str]) -> Dict[str, str]:
    """Stable colours, with our own entity pinned to SELF_COLOR."""
    mapping: Dict[str, str] = {}
    index = 0
    for entity in entities:
        if entity == SELF_ENTITY:
            mapping[entity] = SELF_COLOR
        else:
            mapping[entity] = PALETTE[index % len(PALETTE)]
            index += 1
    return mapping


def observations_frame(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """llm_observations as a typed frame, error rows dropped."""
    frame = to_frame(rows)
    if frame.empty:
        return frame
    frame["mention_bool"] = frame["mention"].map(parse_bool)
    frame = frame[frame["mention_bool"].notna()].copy()
    frame["rank_num"] = frame["rank"].map(parse_rank)
    frame["negative_bool"] = frame["negative_or_outdated"].map(
        lambda v: bool(parse_bool(v))
    )
    return frame


def competitor_list(value: Any) -> List[str]:
    """Normalised competitor names, self and generic phrases removed."""
    out = []
    for raw in split_list(value):
        entity = resolve_entity(raw)
        if entity and entity != SELF_ENTITY:
            out.append(entity)
    return sorted(set(out))


def empty_state(message: str) -> None:
    st.info(message)
