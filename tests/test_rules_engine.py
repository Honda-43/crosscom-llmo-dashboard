"""Unit tests for rules_engine (Phase 2 §2, DoD 1).

Every rule is exercised in all three states: fired / not_fired /
insufficient_data. Synthetic data only — no Sheets access.
"""
import datetime as dt

import pytest

import rules_engine
from rules_engine import FIRED, INSUFFICIENT, NOT_FIRED
from settings import TAB_CHANGES, TAB_GA4, TAB_GSC, TAB_LLM, TAB_SOV, TAB_SUMMARY

TODAY = "2026-08-17"


def days_before(n, base=TODAY):
    return (dt.date.fromisoformat(base) - dt.timedelta(days=n)).isoformat()


def obs(date, prompt_id="A-1", model="claude", mention="TRUE", rank="", pillar="A",
        competitors="", negative="FALSE", negative_detail="", urls=""):
    return {
        "date": date, "prompt_id": prompt_id, "pillar": pillar, "model": model,
        "mention": mention, "mention_type": "recommended_list", "rank": rank,
        "kbf_tags": "", "negative_or_outdated": negative,
        "negative_detail": negative_detail, "cited_crosscom_urls": urls,
        "competitors_mentioned": competitors, "raw_file": "",
    }


def summary(date, all_rate="0.5", a="0.5", b="0.5"):
    return {
        "date": date, "mention_rate_all": all_rate, "mention_rate_pillar_a": a,
        "mention_rate_pillar_b": b, "negative_flag_count": "0",
        "ai_sessions": "10", "branded_clicks": "5",
    }


def sov(date, entity, count, observed=6, pillar="all"):
    return {
        "date": date, "pillar": pillar, "entity": entity,
        "mention_count": str(count), "observed_total": str(observed),
    }


def tabs(llm=None, summary_rows=None, sov_rows=None, changes=None, ga4=None, gsc=None):
    return {
        TAB_LLM: llm or [], TAB_SUMMARY: summary_rows or [], TAB_SOV: sov_rows or [],
        TAB_CHANGES: changes or [], TAB_GA4: ga4 or [], TAB_GSC: gsc or [],
    }


def verdict(stats, rule_id):
    return next(r for r in stats["rules"] if r["rule_id"] == rule_id)


def build(**kwargs):
    return rules_engine.build_stats(TODAY, tabs(**kwargs), legacy_paths=["/btob-crm/"])


# ===========================================================================
# R-P2 — mention lost
# ===========================================================================
def test_p2_fires_after_three_absent_observations():
    rows = [obs(days_before(n), mention="TRUE") for n in (10, 9, 8)]
    rows += [obs(days_before(n), mention="FALSE") for n in (2, 1, 0)]
    v = verdict(build(llm=rows), "R-P2")
    assert v["status"] == FIRED
    assert v["evidence"][0]["prompt_id"] == "A-1"
    assert v["evidence"][0]["last_mentioned"] == days_before(8)


def test_p2_does_not_fire_when_still_mentioned():
    rows = [obs(days_before(n), mention="TRUE") for n in (3, 2, 1, 0)]
    assert verdict(build(llm=rows), "R-P2")["status"] == NOT_FIRED


def test_p2_does_not_fire_when_never_mentioned():
    """一度も言及がない系列は「消失」ではない(P-15の領域)。"""
    rows = [obs(days_before(n), mention="FALSE") for n in (3, 2, 1, 0)]
    assert verdict(build(llm=rows), "R-P2")["status"] == NOT_FIRED


def test_p2_insufficient_without_enough_history():
    rows = [obs(days_before(n), mention="FALSE") for n in (1, 0)]
    assert verdict(build(llm=rows), "R-P2")["status"] == INSUFFICIENT


# ===========================================================================
# R-P4 — mention_rate improvement
# ===========================================================================
def test_p4_fires_on_ten_point_gain():
    rows = [summary(days_before(n), a="0.7") for n in range(0, 7)]
    rows += [summary(days_before(n), a="0.5") for n in range(7, 14)]
    v = verdict(build(summary_rows=rows), "R-P4")
    assert v["status"] == FIRED
    assert v["evidence"][0]["pillar"] == "A"
    assert v["evidence"][0]["delta"] == pytest.approx(0.2)


def test_p4_does_not_fire_below_threshold():
    rows = [summary(days_before(n), a="0.55") for n in range(0, 7)]
    rows += [summary(days_before(n), a="0.50") for n in range(7, 14)]
    assert verdict(build(summary_rows=rows), "R-P4")["status"] == NOT_FIRED


def test_p4_insufficient_without_a_previous_week():
    rows = [summary(days_before(n), a="0.7") for n in range(0, 7)]
    assert verdict(build(summary_rows=rows), "R-P4")["status"] == INSUFFICIENT


# ===========================================================================
# R-P5 — stuck low in the list
# ===========================================================================
def four_weeks_of_ranks(rank):
    return [obs(days_before(n), rank=str(rank)) for n in (0, 3, 7, 10, 14, 17, 21, 24)]


def test_p5_fires_when_rank_stays_poor_for_four_weeks():
    v = verdict(build(llm=four_weeks_of_ranks(7)), "R-P5")
    assert v["status"] == FIRED
    assert v["evidence"][0]["weekly_median_rank"] == [7, 7, 7, 7]


def test_p5_does_not_fire_when_rank_is_good():
    assert verdict(build(llm=four_weeks_of_ranks(2)), "R-P5")["status"] == NOT_FIRED


def test_p5_does_not_fire_when_one_week_recovered():
    rows = [obs(days_before(n), rank="7") for n in (0, 7, 21)]
    rows += [obs(days_before(14), rank="2")]
    assert verdict(build(llm=rows), "R-P5")["status"] == NOT_FIRED


def test_p5_insufficient_without_four_weeks():
    rows = [obs(days_before(n), rank="7") for n in (0, 3)]
    assert verdict(build(llm=rows), "R-P5")["status"] == INSUFFICIENT


# ===========================================================================
# R-P7 — negative / outdated
# ===========================================================================
def test_p7_fires_and_carries_the_detail():
    rows = [obs(days_before(1), negative="TRUE", negative_detail="旧MA事業の記述")]
    v = verdict(build(llm=rows), "R-P7")
    assert v["status"] == FIRED
    assert v["evidence"][0]["negative_detail"] == "旧MA事業の記述"


def test_p7_does_not_fire_when_clean():
    assert verdict(build(llm=[obs(days_before(1))]), "R-P7")["status"] == NOT_FIRED


def test_p7_insufficient_without_observations_this_week():
    assert verdict(build(llm=[obs(days_before(20))]), "R-P7")["status"] == INSUFFICIENT


# ===========================================================================
# R-P8 — legacy URLs cited for E-1
# ===========================================================================
def entity_obs(date, urls):
    return obs(date, prompt_id="E-1", pillar="entity", urls=urls)


def test_p8_fires_on_a_legacy_path():
    rows = [entity_obs(days_before(1), "https://cross-com.jp/btob-crm/what-is")]
    v = verdict(build(llm=rows), "R-P8")
    assert v["status"] == FIRED
    assert v["evidence"][0]["legacy_urls"] == ["https://cross-com.jp/btob-crm/what-is"]


def test_p8_does_not_fire_on_current_pages():
    rows = [entity_obs(days_before(1), "https://cross-com.jp/agentforce/")]
    assert verdict(build(llm=rows), "R-P8")["status"] == NOT_FIRED


def test_p8_insufficient_without_e1_observations():
    assert verdict(build(llm=[obs(days_before(1))]), "R-P8")["status"] == INSUFFICIENT


def test_p8_insufficient_when_legacy_paths_are_empty():
    rows = [entity_obs(days_before(1), "https://cross-com.jp/btob-crm/x")]
    stats = rules_engine.build_stats(TODAY, tabs(llm=rows), legacy_paths=[])
    assert verdict(stats, "R-P8")["status"] == INSUFFICIENT


# ===========================================================================
# R-P15 — competitor entrenched where we are absent
# ===========================================================================
def entrenched_rows(entity="船井総研", both_models=True, mention="FALSE"):
    rows = []
    for week_day in (0, 7, 14, 21):
        rows.append(obs(days_before(week_day), model="claude", mention=mention,
                        competitors=entity))
        if both_models:
            rows.append(obs(days_before(week_day), model="gemini", mention=mention,
                            competitors=entity))
        else:
            rows.append(obs(days_before(week_day), model="gemini", mention=mention))
    return rows


def test_p15_fires_when_a_competitor_persists_in_both_models():
    v = verdict(build(llm=entrenched_rows()), "R-P15")
    assert v["status"] == FIRED
    assert v["evidence"][0]["entity"] == "船井総合研究所"
    assert v["evidence"][0]["models"] == ["claude", "gemini"]


def test_p15_does_not_fire_when_we_are_mentioned():
    assert verdict(build(llm=entrenched_rows(mention="TRUE")), "R-P15")["status"] == NOT_FIRED


def test_p15_does_not_fire_for_a_single_model():
    assert verdict(build(llm=entrenched_rows(both_models=False)), "R-P15")["status"] == NOT_FIRED


def test_p15_insufficient_without_four_weeks():
    rows = [obs(days_before(0), model=m, mention="FALSE", competitors="船井総研")
            for m in ("claude", "gemini")]
    assert verdict(build(llm=rows), "R-P15")["status"] == INSUFFICIENT


# ===========================================================================
# R-DROP — competitive structure moved
# ===========================================================================
def test_drop_fires_when_a_top_competitor_halves():
    rows = [sov(days_before(1), "船井総合研究所", 2), sov(days_before(8), "船井総合研究所", 8)]
    v = verdict(build(sov_rows=rows), "R-DROP")
    assert v["status"] == FIRED
    assert v["evidence"][0]["kind"] == "halved"


def test_drop_fires_on_a_new_entrant():
    rows = [sov(days_before(1), "メンバーズ", 4), sov(days_before(8), "船井総合研究所", 4)]
    v = verdict(build(sov_rows=rows), "R-DROP")
    assert v["status"] == FIRED
    assert {e["kind"] for e in v["evidence"]} == {"new_entrant"}


def test_drop_does_not_fire_on_a_stable_week():
    rows = [sov(days_before(1), "船井総合研究所", 4), sov(days_before(8), "船井総合研究所", 4)]
    assert verdict(build(sov_rows=rows), "R-DROP")["status"] == NOT_FIRED


def test_drop_insufficient_without_sov_data():
    assert verdict(build(), "R-DROP")["status"] == INSUFFICIENT


def test_drop_insufficient_without_a_previous_week():
    assert verdict(build(sov_rows=[sov(days_before(1), "メンバーズ", 4)]), "R-DROP")["status"] \
        == INSUFFICIENT


def test_drop_ignores_our_own_entity():
    """自社は競合ではないので構造変化の判定対象にしない。"""
    rows = [sov(days_before(1), "クロスコム", 1), sov(days_before(8), "クロスコム", 6)]
    assert verdict(build(sov_rows=rows), "R-DROP")["status"] == INSUFFICIENT
