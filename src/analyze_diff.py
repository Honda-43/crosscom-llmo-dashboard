"""analyze_diff.py — change detection against the previous observation (Phase 1 §3).

Compares today's extraction records with the most recent *earlier* day already
stored in the ``llm_observations`` tab, per ``prompt_id × model``, and emits one
row per detected change into the approved ``changes`` schema:
``date | prompt_id | model | change_type | before | after | detail``

The previous day is read from Sheets (a single read of the tab — see §8 on API
call budget). When there is no earlier day at all — first run, or a fresh
spreadsheet — the module returns no changes and exits normally (§3).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from normalize import resolve_entity

# change_type vocabulary (§3) — do not rename, the sheet is keyed on these.
MENTION_GAINED = "mention_gained"
MENTION_LOST = "mention_lost"
RANK_UP = "rank_up"
RANK_DOWN = "rank_down"
COMPETITOR_ADDED = "competitor_added"
COMPETITOR_REMOVED = "competitor_removed"
URL_ADDED = "crosscom_url_added"
URL_REMOVED = "crosscom_url_removed"
NEGATIVE_ON = "negative_flag_on"
NEGATIVE_OFF = "negative_flag_off"

_OUT_OF_LIST = "圏外"


# --------------------------------------------------------------------------
# Parsing helpers — the sheet stores everything as text
# --------------------------------------------------------------------------
def parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().upper()
    if text in ("TRUE", "1", "YES"):
        return True
    if text in ("FALSE", "0", "NO"):
        return False
    return None


def parse_rank(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def split_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = str(value or "").split(",")
    return [item.strip() for item in items if item and item.strip()]


def _entity_set(values: Any) -> Set[str]:
    """Normalised competitor set. Generic phrases are dropped here too, so a
    stop-listed phrase appearing on only one of the two days is not reported as
    a competitor_added/removed change."""
    return {e for e in (resolve_entity(v) for v in split_list(values)) if e}


def _url_set(values: Any) -> Set[str]:
    # Trailing slashes are not a meaningful difference between two citations.
    return {u.rstrip("/") for u in split_list(values)}


def _observation(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a sheet row *or* an extraction record into a comparable shape.

    Returns ``None`` for rows that carry no usable observation (extraction
    errors, blank rows) — there is nothing meaningful to diff against.
    """
    if raw.get("error"):
        return None
    mention = parse_bool(raw.get("mention"))
    if mention is None:
        return None
    return {
        "mention": mention,
        "rank": parse_rank(raw.get("rank")),
        "competitors": _entity_set(raw.get("competitors_mentioned")),
        "urls": _url_set(raw.get("cited_crosscom_urls")),
        "negative": bool(parse_bool(raw.get("negative_or_outdated"))),
        "negative_detail": str(raw.get("negative_detail") or "").strip(),
    }


def _key(raw: Dict[str, Any]) -> tuple:
    return (str(raw.get("prompt_id") or ""), str(raw.get("model") or ""))


def _index(rows: Iterable[Dict[str, Any]]) -> Dict[tuple, Dict[str, Any]]:
    index: Dict[tuple, Dict[str, Any]] = {}
    for raw in rows:
        observation = _observation(raw)
        if observation is not None:
            index[_key(raw)] = observation
    return index


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------
def _rank_label(rank: Optional[int]) -> str:
    return _OUT_OF_LIST if rank is None else str(rank)


def diff_observation(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, str]]:
    """All changes between two observations of the same prompt_id × model."""
    changes: List[Dict[str, str]] = []

    def add(change_type: str, before_value: Any, after_value: Any, detail: str = "") -> None:
        changes.append({
            "change_type": change_type,
            "before": "" if before_value is None else str(before_value),
            "after": "" if after_value is None else str(after_value),
            "detail": detail,
        })

    # mention
    if before["mention"] != after["mention"]:
        add(
            MENTION_GAINED if after["mention"] else MENTION_LOST,
            "TRUE" if before["mention"] else "FALSE",
            "TRUE" if after["mention"] else "FALSE",
        )

    # rank — smaller is better. Entering / leaving the recommendation list is
    # reported as a move against "圏外" so a null never hides a real change.
    if before["rank"] != after["rank"]:
        before_rank, after_rank = before["rank"], after["rank"]
        if before_rank is None and after_rank is not None:
            direction = RANK_UP
        elif before_rank is not None and after_rank is None:
            direction = RANK_DOWN
        else:
            direction = RANK_UP if after_rank < before_rank else RANK_DOWN
        add(
            direction,
            _rank_label(before_rank),
            _rank_label(after_rank),
            f"順位 {_rank_label(before_rank)} → {_rank_label(after_rank)}",
        )

    # competitors (normalised sets)
    for entity in sorted(after["competitors"] - before["competitors"]):
        add(COMPETITOR_ADDED, "", entity, entity)
    for entity in sorted(before["competitors"] - after["competitors"]):
        add(COMPETITOR_REMOVED, entity, "", entity)

    # cited crosscom URLs
    for url in sorted(after["urls"] - before["urls"]):
        add(URL_ADDED, "", url, url)
    for url in sorted(before["urls"] - after["urls"]):
        add(URL_REMOVED, url, "", url)

    # negative / outdated flag
    if before["negative"] != after["negative"]:
        if after["negative"]:
            add(NEGATIVE_ON, "FALSE", "TRUE", after["negative_detail"])
        else:
            add(NEGATIVE_OFF, "TRUE", "FALSE", before["negative_detail"])

    return changes


def previous_date(rows: Sequence[Dict[str, Any]], date: str) -> Optional[str]:
    """Most recent observation date strictly before ``date``."""
    dates = {str(r.get("date") or "").strip() for r in rows}
    earlier = sorted(d for d in dates if d and d < date)
    return earlier[-1] if earlier else None


def analyze(
    extractions: Sequence[Dict[str, Any]],
    date: str,
    previous_rows: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build the ``changes`` rows for ``date``.

    ``previous_rows`` is the full ``llm_observations`` tab; when omitted it is
    read from Sheets once. Passing it in keeps this function pure for tests and
    lets a caller share a single read.
    """
    if previous_rows is None:
        import sheets_writer

        previous_rows = sheets_writer.read_llm_observations()

    prev_date = previous_date(previous_rows, date)
    if not prev_date:
        print(f"[ok] analyze_diff {date}: no earlier observation date — no changes")
        return []

    before_index = _index(
        r for r in previous_rows if str(r.get("date") or "").strip() == prev_date
    )
    after_index = _index(extractions)

    rows: List[Dict[str, Any]] = []
    for key in sorted(before_index.keys() & after_index.keys()):
        prompt_id, model = key
        for change in diff_observation(before_index[key], after_index[key]):
            rows.append({
                "date": date,
                "prompt_id": prompt_id,
                "model": model,
                **change,
            })

    print(f"[ok] analyze_diff {date} vs {prev_date}: {len(rows)} changes")
    return rows
