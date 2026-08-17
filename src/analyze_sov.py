"""analyze_sov.py — competitor Share of Voice aggregation (Phase 1 §2).

Takes the day's extraction records, expands ``competitors_mentioned`` (plus our
own company when ``mention`` is TRUE) into normalised entities and counts how
many observations each entity appeared in, per pillar.

Output rows follow the approved ``sov_daily`` schema:
``date | pillar | entity | mention_count | observed_total``

``observed_total`` is the number of observations behind the pillar that day, so
the share itself (mention_count / observed_total) is computed downstream in
Looker Studio / the app rather than baked into the sheet (§2).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence

from normalize import resolve_entity
from settings import SELF_ENTITY

# Pillars aggregated, in output order. "all" = A + B combined.
# The E-1 entity prompt is excluded everywhere (§2): it always mentions us and
# would inflate every rate.
PILLARS = ("A", "B", "all")


def _observations(extractions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Valid, non-entity observations — the population SoV is measured over."""
    return [
        r
        for r in extractions
        if not r.get("error")
        and r.get("prompt_id") != "E-1"
        and r.get("pillar") != "entity"
    ]


def _entities_in(record: Dict[str, Any]) -> set:
    """Normalised entity set for one observation.

    A set, not a list: two different spellings of the same company inside one
    answer must count once, otherwise normalisation would *inflate* the winner.
    Generic phrases and leftover fragments are dropped by ``resolve_entity``.
    """
    entities = set()
    for raw in record.get("competitors_mentioned") or []:
        entity = resolve_entity(raw)
        if entity:
            entities.add(entity)
    if record.get("mention") is True:
        entities.add(SELF_ENTITY)
    return entities


def analyze(extractions: Sequence[Dict[str, Any]], date: str) -> List[Dict[str, Any]]:
    """Build the ``sov_daily`` rows for ``date``."""
    population = _observations(extractions)
    rows: List[Dict[str, Any]] = []

    for pillar in PILLARS:
        observations = (
            population if pillar == "all"
            else [r for r in population if r.get("pillar") == pillar]
        )
        if not observations:
            continue

        counts: Counter = Counter()
        for record in observations:
            counts.update(_entities_in(record))
        # Always emit our own row, even at zero, so the self-SoV series stays
        # continuous instead of gapping on days we are not mentioned at all.
        counts.setdefault(SELF_ENTITY, 0)

        for entity, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            rows.append({
                "date": date,
                "pillar": pillar,
                "entity": entity,
                "mention_count": count,
                "observed_total": len(observations),
            })

    print(f"[ok] analyze_sov {date}: {len(rows)} rows over {len(population)} observations")
    return rows
