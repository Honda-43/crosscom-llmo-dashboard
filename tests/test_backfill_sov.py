"""Unit tests for backfill_sov — full sov_daily regeneration."""
import backfill_sov


def obs_row(date, prompt_id="A-1", pillar="A", model="claude", mention="TRUE",
            competitors=""):
    return {
        "date": date, "prompt_id": prompt_id, "pillar": pillar, "model": model,
        "mention": mention, "mention_type": "recommended_list", "rank": "1",
        "kbf_tags": "", "negative_or_outdated": "FALSE", "negative_detail": "",
        "cited_crosscom_urls": "", "competitors_mentioned": competitors,
        "raw_file": "",
    }


def test_rebuilds_every_date():
    observations = [
        obs_row("2026-08-15", competitors="株式会社100"),
        obs_row("2026-08-16", competitors="100inc"),
        obs_row("2026-08-17", competitors="100 Inc."),
    ]
    rows = backfill_sov.build_rows(observations)
    assert sorted({r["date"] for r in rows}) == ["2026-08-15", "2026-08-16", "2026-08-17"]

    # The three spellings collapse onto one entity and "100" is gone for good.
    entities = {r["entity"] for r in rows}
    assert "ゼロワングロース" in entities
    assert "100" not in entities


def test_generic_phrases_do_not_come_back():
    observations = [obs_row("2026-08-17", competitors="ブティック型DXコンサルティングファーム, 船井総研")]
    rows = backfill_sov.build_rows(observations)
    entities = {r["entity"] for r in rows}
    assert entities == {"クロスコム", "船井総合研究所"}


def test_ey_spacing_variants_merge_into_one_row():
    observations = [
        obs_row("2026-08-17", prompt_id="A-1",
                competitors="EY ストラテジー・アンド・コンサルティング株式会社"),
        obs_row("2026-08-17", prompt_id="A-2",
                competitors="EYストラテジー・アンド・コンサルティング株式会社"),
    ]
    rows = backfill_sov.build_rows(observations)
    ey = [r for r in rows if r["pillar"] == "all" and "EY" in r["entity"]]
    assert len(ey) == 1
    assert ey[0]["mention_count"] == 2


def test_error_rows_stay_out_of_observed_total():
    observations = [
        obs_row("2026-08-17", prompt_id="A-1", competitors="船井総研"),
        obs_row("2026-08-17", prompt_id="A-2", mention="", competitors=""),
    ]
    rows = backfill_sov.build_rows(observations)
    assert all(r["observed_total"] == 1 for r in rows if r["pillar"] == "all")


def test_date_range_filters():
    observations = [obs_row(d) for d in ("2026-08-15", "2026-08-16", "2026-08-17")]
    rows = backfill_sov.build_rows(observations, since="2026-08-16")
    assert sorted({r["date"] for r in rows}) == ["2026-08-16", "2026-08-17"]

    rows = backfill_sov.build_rows(observations, since="2026-08-16", until="2026-08-16")
    assert sorted({r["date"] for r in rows}) == ["2026-08-16"]


def test_rows_use_the_approved_sov_schema():
    rows = backfill_sov.build_rows([obs_row("2026-08-17", competitors="船井総研")])
    for row in rows:
        assert set(row) == {"date", "pillar", "entity", "mention_count", "observed_total"}


def test_blank_dates_are_ignored():
    assert backfill_sov.build_rows([obs_row("")]) == []


def test_excluded_report_lists_what_was_dropped():
    observations = [
        obs_row("2026-08-17", competitors="ブティック型DXコンサルティングファーム, 船井総研"),
        obs_row("2026-08-16", competitors="ブティック型DXコンサルティングファーム"),
    ]
    report = backfill_sov.excluded_report(observations)
    assert report == {"ブティック型DXコンサルティングファーム": 2}


def test_excluded_report_is_empty_when_everything_resolves():
    assert backfill_sov.excluded_report([obs_row("2026-08-17", competitors="船井総研")]) == {}
