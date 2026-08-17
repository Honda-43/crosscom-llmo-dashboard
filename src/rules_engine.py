"""rules_engine.py — stage 1 of the weekly insight engine (Phase 2 §2).

Everything that counts as a *judgement* happens here, in deterministic Python
that can be unit-tested. The LLM in stage 2 only writes prose over this output;
it never sees raw answers and never decides whether something fired.

Input : the stored tabs (daily_summary / llm_observations / sov_daily /
        changes / ga4_ai_traffic / gsc_branded), last 28 days.
Output: a stats dict (serialised as stats.json) holding the weekly statistics
        (§2-1) and the rule verdicts (§2-2).

Every rule reports one of three states — ``fired``, ``not_fired`` or
``insufficient_data``. The third is not a failure: it says the data cannot
answer the question this week, which is itself something the report must say
out loud rather than paper over.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from analyze_diff import parse_bool, parse_rank, split_list
from normalize import resolve_entity
from settings import (
    LEGACY_PATHS_FILE,
    RULES_THRESHOLDS_FILE,
    SELF_ENTITY,
    TAB_CHANGES,
    TAB_GA4,
    TAB_GSC,
    TAB_LLM,
    TAB_SOV,
    TAB_SUMMARY,
    load_yaml,
)

FIRED = "fired"
NOT_FIRED = "not_fired"
INSUFFICIENT = "insufficient_data"

ENTITY_PROMPT_ID = "E-1"


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def load_thresholds() -> Dict[str, Any]:
    data = load_yaml(RULES_THRESHOLDS_FILE) or {}
    return data


def load_legacy_paths() -> List[str]:
    data = load_yaml(LEGACY_PATHS_FILE) or {}
    return [str(p).strip() for p in (data.get("paths") or []) if str(p).strip()]


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def _d(date: str) -> dt.date:
    return dt.date.fromisoformat(date)


def week_window(date: str, weeks_ago: int = 0, days: int = 7) -> Tuple[str, str]:
    """Inclusive [start, end] of the ``weeks_ago``-th week ending at ``date``.

    ``weeks_ago=0`` is the most recent ``days``-day window ending on ``date``;
    ``weeks_ago=1`` is the ``days`` days immediately before it.
    """
    end = _d(date) - dt.timedelta(days=days * weeks_ago)
    start = end - dt.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _in_window(value: Any, window: Tuple[str, str]) -> bool:
    text = str(value or "").strip()
    return bool(text) and window[0] <= text <= window[1]


def _rows_in(rows: Iterable[Dict[str, Any]], window: Tuple[str, str]) -> List[Dict[str, Any]]:
    return [r for r in rows if _in_window(r.get("date"), window)]


def _num(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _sum(rows: Iterable[Dict[str, Any]], field: str) -> float:
    return sum(_num(r.get(field)) or 0.0 for r in rows)


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 4) if values else None


def _delta(this: Optional[float], prev: Optional[float]) -> Optional[float]:
    if this is None or prev is None:
        return None
    return round(this - prev, 4)


def _comparison(this: Optional[float], prev: Optional[float]) -> Dict[str, Any]:
    return {"this_week": this, "prev_week": prev, "delta": _delta(this, prev)}


# --------------------------------------------------------------------------
# Observation helpers
# --------------------------------------------------------------------------
def _observations(llm_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Valid observations only — extraction errors carry no signal."""
    out = []
    for row in llm_rows:
        mention = parse_bool(row.get("mention"))
        if mention is None:
            continue
        out.append({
            "date": str(row.get("date") or "").strip(),
            "prompt_id": str(row.get("prompt_id") or "").strip(),
            "pillar": str(row.get("pillar") or "").strip(),
            "model": str(row.get("model") or "").strip(),
            "mention": mention,
            "rank": parse_rank(row.get("rank")),
            "negative": bool(parse_bool(row.get("negative_or_outdated"))),
            "negative_detail": str(row.get("negative_detail") or "").strip(),
            "crosscom_urls": split_list(row.get("cited_crosscom_urls")),
            "competitors": sorted({
                e for e in (resolve_entity(c) for c in split_list(row.get("competitors_mentioned")))
                if e and e != SELF_ENTITY
            }),
        })
    return out


def _non_entity(observations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [o for o in observations if o["prompt_id"] != ENTITY_PROMPT_ID]


# --------------------------------------------------------------------------
# §2-1 Weekly statistics
# --------------------------------------------------------------------------
def _mention_rates(summary_rows: List[Dict[str, Any]], date: str, days: int) -> Dict[str, Any]:
    """mention_rate 3 series, this week vs last, from daily_summary.

    daily_summary is used rather than recomputing from llm_observations so the
    report always agrees with the number on the dashboard.
    """
    fields = {
        "all": "mention_rate_all",
        "pillar_a": "mention_rate_pillar_a",
        "pillar_b": "mention_rate_pillar_b",
    }
    this_rows = _rows_in(summary_rows, week_window(date, 0, days))
    prev_rows = _rows_in(summary_rows, week_window(date, 1, days))

    out: Dict[str, Any] = {}
    for key, field in fields.items():
        this_values = [v for v in (_num(r.get(field)) for r in this_rows) if v is not None]
        prev_values = [v for v in (_num(r.get(field)) for r in prev_rows) if v is not None]
        out[key] = _comparison(_mean(this_values), _mean(prev_values))
    out["days_observed"] = {"this_week": len(this_rows), "prev_week": len(prev_rows)}
    return out


def _prompt_model_matrix(observations: List[Dict[str, Any]], date: str, days: int) -> List[Dict[str, Any]]:
    """Per prompt_id × model: days mentioned / days observed, last 7 days."""
    window = week_window(date, 0, days)
    buckets: Dict[Tuple[str, str], Dict[str, set]] = defaultdict(
        lambda: {"observed": set(), "mentioned": set()}
    )
    for obs in _rows_in(observations, window):
        bucket = buckets[(obs["prompt_id"], obs["model"])]
        bucket["observed"].add(obs["date"])
        if obs["mention"]:
            bucket["mentioned"].add(obs["date"])

    return [
        {
            "prompt_id": prompt_id,
            "model": model,
            "mentioned_days": len(bucket["mentioned"]),
            "observed_days": len(bucket["observed"]),
        }
        for (prompt_id, model), bucket in sorted(buckets.items())
    ]


def _rank_trend(observations: List[Dict[str, Any]], date: str, days: int) -> List[Dict[str, Any]]:
    """Median rank per prompt_id × model, this week vs last."""
    def medians(window: Tuple[str, str]) -> Dict[Tuple[str, str], float]:
        ranks: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for obs in _rows_in(observations, window):
            if obs["rank"] is not None:
                ranks[(obs["prompt_id"], obs["model"])].append(obs["rank"])
        return {k: round(statistics.median(v), 2) for k, v in ranks.items()}

    this = medians(week_window(date, 0, days))
    prev = medians(week_window(date, 1, days))
    out = []
    for key in sorted(this.keys() | prev.keys()):
        this_value, prev_value = this.get(key), prev.get(key)
        out.append({
            "prompt_id": key[0],
            "model": key[1],
            "median_this_week": this_value,
            "median_prev_week": prev_value,
            # Negative delta = the number went down = the rank improved.
            "delta": _delta(this_value, prev_value),
        })
    return out


def _sov_top(sov_rows: List[Dict[str, Any]], date: str, days: int, top_n: int = 10) -> Dict[str, Any]:
    """Top-N entities per pillar over the window, with the week-over-week move."""
    def totals(window: Tuple[str, str]) -> Dict[str, Dict[str, float]]:
        counts: Dict[str, Counter] = defaultdict(Counter)
        observed: Dict[str, Dict[str, float]] = defaultdict(dict)
        for row in _rows_in(sov_rows, window):
            pillar = str(row.get("pillar") or "").strip()
            entity = str(row.get("entity") or "").strip()
            if not pillar or not entity:
                continue
            counts[pillar][entity] += _num(row.get("mention_count")) or 0.0
            # observed_total is repeated on every row of a date+pillar.
            observed[pillar][str(row.get("date"))] = _num(row.get("observed_total")) or 0.0
        return {
            pillar: {
                "counts": dict(counts[pillar]),
                "observed_total": sum(observed[pillar].values()),
            }
            for pillar in counts
        }

    this = totals(week_window(date, 0, days))
    prev = totals(week_window(date, 1, days))

    out: Dict[str, Any] = {}
    for pillar in sorted(set(this) | set(prev)):
        this_counts = this.get(pillar, {}).get("counts", {})
        prev_counts = prev.get(pillar, {}).get("counts", {})
        observed_total = this.get(pillar, {}).get("observed_total", 0.0)
        ranked = sorted(this_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        out[pillar] = {
            "observed_total": observed_total,
            # How much competitor data last week held at all — distinct from
            # "this week's entities happened to score 0 last week", which is
            # what a newcomer looks like.
            "prev_week_competitor_count": len(
                [e for e in prev_counts if e != SELF_ENTITY]
            ),
            "entities": [
                {
                    "entity": entity,
                    "mention_count": count,
                    "share": round(count / observed_total, 4) if observed_total else None,
                    "prev_week_count": prev_counts.get(entity, 0.0),
                    "delta": round(count - prev_counts.get(entity, 0.0), 2),
                }
                for entity, count in ranked
            ],
        }
    return out


def _change_counts(change_rows: List[Dict[str, Any]], date: str, days: int) -> Dict[str, int]:
    window = week_window(date, 0, days)
    counter = Counter(
        str(r.get("change_type") or "").strip()
        for r in _rows_in(change_rows, window)
        if str(r.get("change_type") or "").strip()
    )
    return dict(sorted(counter.items()))


def _kgi(ga4_rows: List[Dict[str, Any]], gsc_rows: List[Dict[str, Any]],
         date: str, days: int, noise_floor: float = 10.0) -> Dict[str, Any]:
    """KGI weekly totals vs the previous week, with a noise guard.

    At these volumes a week-over-week move is often meaningless: 4 sessions
    down to 2 is "-50%" and also nothing at all. A metric whose *current* week
    sits below ``noise_floor`` is flagged ``noise_zone`` so the report is told
    not to dress the swing up as a result.

    The test is on this week alone, not on both weeks: at 4 clicks the level is
    unactionable regardless of what last week was. A genuine collapse (20 -> 2)
    is therefore flagged too — but the prose still prints both raw numbers, so
    the fall stays visible while losing only the "requires action" framing.
    """
    this_window, prev_window = week_window(date, 0, days), week_window(date, 1, days)

    def series(this_value: float, prev_value: float) -> Dict[str, Any]:
        entry = _comparison(this_value, prev_value)
        entry["noise_zone"] = this_value < noise_floor
        return entry

    kgi = {
        "ai_sessions": series(
            _sum(_rows_in(ga4_rows, this_window), "sessions"),
            _sum(_rows_in(ga4_rows, prev_window), "sessions"),
        ),
        "ai_key_events": series(
            _sum(_rows_in(ga4_rows, this_window), "key_events"),
            _sum(_rows_in(ga4_rows, prev_window), "key_events"),
        ),
        "branded_clicks": series(
            _sum(_rows_in(gsc_rows, this_window), "clicks"),
            _sum(_rows_in(gsc_rows, prev_window), "clicks"),
        ),
        "branded_impressions": series(
            _sum(_rows_in(gsc_rows, this_window), "impressions"),
            _sum(_rows_in(gsc_rows, prev_window), "impressions"),
        ),
    }
    kgi["noise_floor"] = noise_floor
    kgi["noise_zone_metrics"] = sorted(
        k for k, v in kgi.items() if isinstance(v, dict) and v.get("noise_zone")
    )
    return kgi


# --------------------------------------------------------------------------
# §2-2 Rules
# --------------------------------------------------------------------------
def _verdict(rule_id: str, state: str, detail: str, evidence: Optional[List[Any]] = None,
             coverage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One rule's result.

    ``coverage`` records how much of the data the rule could actually see. A
    ``not_fired`` produced from partial data is a weaker statement than one
    produced from complete data, and the report must be able to tell them apart.
    """
    verdict = {
        "rule_id": rule_id,
        "status": state,
        "fired": state == FIRED,
        "detail": detail,
        "evidence": evidence or [],
    }
    if coverage:
        verdict["coverage"] = coverage
    return verdict


def rule_p2(observations: List[Dict[str, Any]], date: str, cfg: Dict[str, Any],
            days: int) -> Dict[str, Any]:
    """Mention lost: previously mentioned, now absent N observation days running."""
    need = int(cfg.get("consecutive_absent_observations", 3))
    by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for obs in _non_entity(observations):
        by_key[(obs["prompt_id"], obs["model"])].append(obs)

    evidence, comparable = [], 0
    for (prompt_id, model), rows in sorted(by_key.items()):
        rows.sort(key=lambda o: o["date"])
        if len(rows) < need + 1:
            continue
        comparable += 1

        # The *actual* absence streak, walking back from the newest observation.
        # Reporting the last `need` observations instead would understate a long
        # absence and contradict last_mentioned in the write-up.
        streak: List[Dict[str, Any]] = []
        for obs in reversed(rows):
            if obs["mention"]:
                break
            streak.append(obs)
        streak.reverse()

        if len(streak) < need:
            continue
        mentioned = [o for o in rows if o["mention"]]
        if not mentioned:
            continue  # never mentioned here — that is P-15 territory, not a loss

        evidence.append({
            "prompt_id": prompt_id,
            "model": model,
            "absent_since": streak[0]["date"],
            "absent_observations": len(streak),
            "last_mentioned": mentioned[-1]["date"],
            "threshold_observations": need,
        })

    if not comparable:
        return _verdict("R-P2", INSUFFICIENT,
                        f"言及実績と直近{need}観測日を比較できる系列がない")
    if not evidence:
        return _verdict("R-P2", NOT_FIRED, f"直近{need}観測日連続で言及を失った系列はない")
    longest = max(e["absent_observations"] for e in evidence)
    return _verdict(
        "R-P2", FIRED,
        f"{len(evidence)}系列で言及消失(最長{longest}観測日連続。閾値は{need})",
        evidence,
    )


def rule_p4(mention_rate: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pillar mention_rate improved by at least the configured delta."""
    threshold = float(cfg.get("mention_rate_delta", 0.10))
    evidence, comparable = [], 0
    for key, label in (("pillar_a", "A"), ("pillar_b", "B")):
        series = mention_rate.get(key, {})
        if series.get("delta") is None:
            continue
        comparable += 1
        if series["delta"] >= threshold:
            evidence.append({
                "pillar": label,
                "this_week": series["this_week"],
                "prev_week": series["prev_week"],
                "delta": series["delta"],
            })

    if not comparable:
        return _verdict("R-P4", INSUFFICIENT, "前週と比較できるmention_rateがない")
    if not evidence:
        return _verdict("R-P4", NOT_FIRED, f"前週比+{threshold}以上のpillarはない")
    return _verdict("R-P4", FIRED,
                    f"{len(evidence)}pillarでmention_rateが前週比+{threshold}以上", evidence)


def rule_p5(observations: List[Dict[str, Any]], date: str, cfg: Dict[str, Any],
            days: int) -> Dict[str, Any]:
    """Stuck low in the list: median rank at/below the threshold for N weeks.

    ``rank`` is 1-best, so "worse" means a *larger* number: the rule fires when
    the median is >= rank_threshold (spec §2-2 "6位以上悪い").
    """
    threshold = float(cfg.get("rank_threshold", 6))
    weeks_needed = int(cfg.get("consecutive_weeks", 4))

    prompt_ids = sorted({o["prompt_id"] for o in _non_entity(observations)})
    evidence, comparable = [], 0
    for prompt_id in prompt_ids:
        medians: List[Optional[float]] = []
        for week in range(weeks_needed):
            ranks = [
                o["rank"] for o in _rows_in(observations, week_window(date, week, days))
                if o["prompt_id"] == prompt_id and o["rank"] is not None
            ]
            medians.append(round(statistics.median(ranks), 2) if ranks else None)
        if any(m is None for m in medians):
            continue  # a week without a rank cannot support a 4-week claim
        comparable += 1
        if all(m >= threshold for m in medians):
            evidence.append({
                "prompt_id": prompt_id,
                "weekly_median_rank": medians,  # index 0 = most recent week
                "threshold": threshold,
            })

    if not comparable:
        return _verdict("R-P5", INSUFFICIENT,
                        f"{weeks_needed}週分のrank中央値が揃うprompt_idがない")
    if not evidence:
        return _verdict("R-P5", NOT_FIRED,
                        f"rank中央値が{weeks_needed}週連続で{threshold}以上のprompt_idはない")
    return _verdict("R-P5", FIRED,
                    f"{len(evidence)}件のprompt_idが{weeks_needed}週連続で下位定着", evidence)


def rule_p7(observations: List[Dict[str, Any]], date: str, cfg: Dict[str, Any],
            days: int) -> Dict[str, Any]:
    """Negative / outdated information detected this week."""
    minimum = int(cfg.get("min_negative_count", 1))
    window = week_window(date, 0, days)
    rows = _rows_in(observations, window)
    if not rows:
        return _verdict("R-P7", INSUFFICIENT, "直近7日の観測がない")

    evidence = [
        {
            "date": o["date"],
            "prompt_id": o["prompt_id"],
            "model": o["model"],
            "negative_detail": o["negative_detail"],
        }
        for o in sorted(rows, key=lambda o: (o["date"], o["prompt_id"])) if o["negative"]
    ]
    if len(evidence) < minimum:
        return _verdict("R-P7", NOT_FIRED, "直近7日にネガティブ/古い情報の検知なし")
    return _verdict("R-P7", FIRED, f"ネガティブ/古い情報を{len(evidence)}件検知", evidence)


def rule_p8(observations: List[Dict[str, Any]], date: str, cfg: Dict[str, Any],
            days: int, legacy_paths: Sequence[str]) -> Dict[str, Any]:
    """E-1 cites a legacy-business URL."""
    minimum = int(cfg.get("min_legacy_url_count", 1))
    window = week_window(date, 0, days)
    entity_rows = [o for o in _rows_in(observations, window) if o["prompt_id"] == ENTITY_PROMPT_ID]
    if not entity_rows:
        return _verdict("R-P8", INSUFFICIENT, "直近7日にE-1の観測がない")
    if not legacy_paths:
        return _verdict("R-P8", INSUFFICIENT, "config/legacy_paths.yaml が空")

    # Not every model reports resolvable citation URLs — Gemini returns grounding
    # redirects, which never contain our domain, so those observations carry no
    # URL evidence at all. Without this, a model-shaped blind spot would be
    # reported as a clean "not_fired".
    with_urls = [o for o in entity_rows if o["crosscom_urls"]]
    coverage = {
        "e1_observations": len(entity_rows),
        "observations_with_crosscom_urls": len(with_urls),
        "models_with_urls": sorted({o["model"] for o in with_urls}),
        "models_without_urls": sorted(
            {o["model"] for o in entity_rows if not o["crosscom_urls"]}
        ),
    }
    if not with_urls:
        return _verdict(
            "R-P8", INSUFFICIENT,
            "E-1の観測はあるが、自社URLの引用が1件も記録されていない(引用URLを解決できないモデルのみ)",
            coverage=coverage,
        )

    evidence = []
    for obs in sorted(with_urls, key=lambda o: (o["date"], o["model"])):
        hits = [
            url for url in obs["crosscom_urls"]
            if any(path.lower() in url.lower() for path in legacy_paths)
        ]
        if hits:
            evidence.append({
                "date": obs["date"], "model": obs["model"], "legacy_urls": hits,
            })

    if len(evidence) < minimum:
        return _verdict(
            "R-P8", NOT_FIRED,
            f"E-1の引用に旧事業パスは含まれない"
            f"(URL評価できた観測 {len(with_urls)}/{len(entity_rows)}件)",
            coverage=coverage,
        )
    return _verdict("R-P8", FIRED, f"E-1の引用に旧事業パスが{len(evidence)}件",
                    evidence, coverage=coverage)


def rule_p15(observations: List[Dict[str, Any]], date: str, cfg: Dict[str, Any],
             days: int) -> Dict[str, Any]:
    """A competitor is entrenched where we are absent."""
    weeks_needed = int(cfg.get("consecutive_weeks", 4))
    require_both = bool(cfg.get("require_both_models", True))

    window = week_window(date, 0, days)
    this_week = _non_entity(_rows_in(observations, window))
    if not this_week:
        return _verdict("R-P15", INSUFFICIENT, "直近7日の観測がない")

    weekly = [
        _non_entity(_rows_in(observations, week_window(date, week, days)))
        for week in range(weeks_needed)
    ]
    if any(not rows for rows in weekly):
        return _verdict("R-P15", INSUFFICIENT, f"{weeks_needed}週分の観測が揃っていない")

    by_prompt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for obs in this_week:
        by_prompt[obs["prompt_id"]].append(obs)

    evidence = []
    for prompt_id, rows in sorted(by_prompt.items()):
        if any(o["mention"] for o in rows):
            continue  # we are present here — not this pattern
        models_by_entity: Dict[str, set] = defaultdict(set)
        for obs in rows:
            for entity in obs["competitors"]:
                models_by_entity[entity].add(obs["model"])
        models_seen = {o["model"] for o in rows}

        for entity, models in sorted(models_by_entity.items()):
            if require_both and (len(models_seen) < 2 or models != models_seen):
                continue
            weeks_present = [
                any(entity in o["competitors"] for o in week_rows if o["prompt_id"] == prompt_id)
                for week_rows in weekly
            ]
            if all(weeks_present):
                evidence.append({
                    "prompt_id": prompt_id,
                    "entity": entity,
                    "models": sorted(models),
                    "consecutive_weeks": weeks_needed,
                })

    if not evidence:
        return _verdict("R-P15", NOT_FIRED, "自社不在プロンプトで定着している競合はない")
    return _verdict("R-P15", FIRED,
                    f"自社不在プロンプトで{len(evidence)}件の競合が定着", evidence)


def rule_drop(sov: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The competitive structure moved: a top-5 halved, or a newcomer arrived."""
    top_n = int(cfg.get("top_n", 5))
    ratio = float(cfg.get("halved_ratio", 0.5))

    pillar = sov.get("all")
    if not pillar or not pillar.get("entities"):
        return _verdict("R-DROP", INSUFFICIENT, "直近7日のSoVデータがない")

    entities = [e for e in pillar["entities"] if e["entity"] != SELF_ENTITY]
    if not entities:
        return _verdict("R-DROP", INSUFFICIENT, "直近7日に競合エンティティの記録がない")
    if not pillar.get("prev_week_competitor_count"):
        return _verdict("R-DROP", INSUFFICIENT, "前週のSoVデータがない")

    top = entities[:top_n]
    evidence = []
    for entry in top:
        prev = entry["prev_week_count"]
        if prev and entry["mention_count"] <= prev * ratio:
            evidence.append({
                "kind": "halved", "entity": entry["entity"],
                "this_week": entry["mention_count"], "prev_week": prev,
            })
        elif not prev:
            evidence.append({
                "kind": "new_entrant", "entity": entry["entity"],
                "this_week": entry["mention_count"], "prev_week": 0.0,
            })

    if not evidence:
        return _verdict("R-DROP", NOT_FIRED, f"SoV上位{top_n}に半減・新規入りはない")
    return _verdict("R-DROP", FIRED, f"SoV上位{top_n}に{len(evidence)}件の構造変化", evidence)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------
def build_stats(date: str, tabs: Dict[str, List[Dict[str, Any]]],
                thresholds: Optional[Dict[str, Any]] = None,
                legacy_paths: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Compute §2-1 statistics and §2-2 rule verdicts for the week ending ``date``."""
    thresholds = thresholds if thresholds is not None else load_thresholds()
    legacy_paths = legacy_paths if legacy_paths is not None else load_legacy_paths()

    window_cfg = thresholds.get("window") or {}
    days = int(window_cfg.get("days", 7))
    lookback = int(window_cfg.get("lookback_days", 28))
    rules_cfg = thresholds.get("rules") or {}

    lookback_window = (
        (_d(date) - dt.timedelta(days=lookback - 1)).isoformat(),
        date,
    )
    scoped = {name: _rows_in(rows, lookback_window) for name, rows in tabs.items()}

    observations = _observations(scoped.get(TAB_LLM, []))
    mention_rate = _mention_rates(scoped.get(TAB_SUMMARY, []), date, days)
    sov = _sov_top(scoped.get(TAB_SOV, []), date, days)

    stats: Dict[str, Any] = {
        "date": date,
        "generated_for_week": {
            "this_week": list(week_window(date, 0, days)),
            "prev_week": list(week_window(date, 1, days)),
            "lookback_days": lookback,
        },
        "mention_rate": mention_rate,
        "prompt_model_matrix": _prompt_model_matrix(observations, date, days),
        "rank_trend": _rank_trend(observations, date, days),
        "sov": sov,
        "changes": _change_counts(scoped.get(TAB_CHANGES, []), date, days),
        "kgi": _kgi(
            scoped.get(TAB_GA4, []), scoped.get(TAB_GSC, []), date, days,
            noise_floor=float((thresholds.get("kgi") or {}).get("noise_floor", 10)),
        ),
        "data_quality": {
            "observations_in_lookback": len(observations),
            "observation_days_this_week": len(
                {o["date"] for o in _rows_in(observations, week_window(date, 0, days))}
            ),
            "observation_days_prev_week": len(
                {o["date"] for o in _rows_in(observations, week_window(date, 1, days))}
            ),
            "weeks_with_observations": sum(
                1 for w in range(4) if _rows_in(observations, week_window(date, w, days))
            ),
        },
    }

    stats["rules"] = [
        rule_p7(observations, date, rules_cfg.get("R-P7") or {}, days),
        rule_p8(observations, date, rules_cfg.get("R-P8") or {}, days, legacy_paths),
        rule_p2(observations, date, rules_cfg.get("R-P2") or {}, days),
        rule_p4(mention_rate, rules_cfg.get("R-P4") or {}),
        rule_p5(observations, date, rules_cfg.get("R-P5") or {}, days),
        rule_p15(observations, date, rules_cfg.get("R-P15") or {}, days),
        rule_drop(sov, rules_cfg.get("R-DROP") or {}),
    ]
    stats["fired_rules"] = [r["rule_id"] for r in stats["rules"] if r["fired"]]
    stats["insufficient_rules"] = [
        r["rule_id"] for r in stats["rules"] if r["status"] == INSUFFICIENT
    ]
    return stats


def run(date: str) -> Dict[str, Any]:
    """Read the tabs once each and compute the stats for ``date``."""
    import sheets_writer

    tabs = sheets_writer.read_for_rules()
    stats = build_stats(date, tabs)
    print(
        f"[ok] rules_engine {date}: fired={stats['fired_rules'] or 'none'} "
        f"insufficient={stats['insufficient_rules'] or 'none'}"
    )
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly rule engine (stage 1)")
    ap.add_argument("--date", required=True, help="week ending date, YYYY-MM-DD")
    ap.add_argument("--out", help="write stats.json here instead of stdout")
    args = ap.parse_args()

    stats = run(args.date)
    text = json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"[ok] wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
