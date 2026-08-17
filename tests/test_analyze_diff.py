"""Unit tests for analyze_diff (Phase 1 §3 / §6-2 / §6-3)."""
import analyze_diff

TODAY = "2026-08-17"
YESTERDAY = "2026-08-16"


def sheet_row(prompt_id="A-1", model="claude", date=YESTERDAY, mention="TRUE", rank="",
              competitors="", urls="", negative="FALSE", negative_detail=""):
    """A row as it comes back from the llm_observations tab (all text)."""
    return {
        "date": date,
        "prompt_id": prompt_id,
        "pillar": "A",
        "model": model,
        "mention": mention,
        "mention_type": "recommended_list",
        "rank": rank,
        "kbf_tags": "",
        "negative_or_outdated": negative,
        "negative_detail": negative_detail,
        "cited_crosscom_urls": urls,
        "competitors_mentioned": competitors,
        "raw_file": "",
    }


def extraction(prompt_id="A-1", model="claude", mention=True, rank=None,
               competitors=None, urls=None, negative=False, negative_detail=None):
    return {
        "date": TODAY,
        "prompt_id": prompt_id,
        "pillar": "A",
        "model": model,
        "mention": mention,
        "rank": rank,
        "competitors_mentioned": competitors or [],
        "cited_crosscom_urls": urls or [],
        "negative_or_outdated": negative,
        "negative_detail": negative_detail,
        "error": None,
    }


def types_of(rows):
    return [r["change_type"] for r in rows]


# --- §6-2: no previous data -------------------------------------------------
def test_no_previous_data_is_a_clean_no_op():
    rows = analyze_diff.analyze([extraction()], TODAY, previous_rows=[])
    assert rows == []


def test_only_same_day_rows_present_is_a_clean_no_op():
    """A re-run of the very first day must not diff today against itself."""
    previous = [sheet_row(date=TODAY, mention="FALSE")]
    assert analyze_diff.analyze([extraction()], TODAY, previous_rows=previous) == []


def test_previous_date_picks_the_latest_earlier_day():
    rows = [sheet_row(date="2026-08-10"), sheet_row(date=YESTERDAY), sheet_row(date=TODAY)]
    assert analyze_diff.previous_date(rows, TODAY) == YESTERDAY
    assert analyze_diff.previous_date(rows, "2026-08-01") is None


# --- §6-3: mention flips ----------------------------------------------------
def test_mention_gained():
    rows = analyze_diff.analyze(
        [extraction(mention=True)], TODAY, previous_rows=[sheet_row(mention="FALSE")]
    )
    assert types_of(rows) == [analyze_diff.MENTION_GAINED]
    assert rows[0] == {
        "date": TODAY, "prompt_id": "A-1", "model": "claude",
        "change_type": "mention_gained", "before": "FALSE", "after": "TRUE", "detail": "",
    }


def test_mention_lost():
    rows = analyze_diff.analyze(
        [extraction(mention=False)], TODAY, previous_rows=[sheet_row(mention="TRUE")]
    )
    assert types_of(rows) == [analyze_diff.MENTION_LOST]


def test_no_change_produces_no_rows():
    rows = analyze_diff.analyze(
        [extraction(mention=True, rank=2, competitors=["DCS"])],
        TODAY,
        previous_rows=[sheet_row(mention="TRUE", rank="2", competitors="三菱総研ＤＣＳ")],
    )
    assert rows == []


# --- §6-3: rank -------------------------------------------------------------
def test_rank_up_and_down():
    up = analyze_diff.analyze(
        [extraction(rank=1)], TODAY, previous_rows=[sheet_row(rank="3")]
    )
    assert types_of(up) == [analyze_diff.RANK_UP]
    assert (up[0]["before"], up[0]["after"]) == ("3", "1")

    down = analyze_diff.analyze(
        [extraction(rank=4)], TODAY, previous_rows=[sheet_row(rank="2")]
    )
    assert types_of(down) == [analyze_diff.RANK_DOWN]


def test_entering_and_leaving_the_list():
    entered = analyze_diff.analyze(
        [extraction(rank=2)], TODAY, previous_rows=[sheet_row(rank="")]
    )
    assert types_of(entered) == [analyze_diff.RANK_UP]
    assert entered[0]["before"] == "圏外"

    left = analyze_diff.analyze(
        [extraction(rank=None)], TODAY, previous_rows=[sheet_row(rank="2")]
    )
    assert types_of(left) == [analyze_diff.RANK_DOWN]
    assert left[0]["after"] == "圏外"


# --- §6-3: competitors ------------------------------------------------------
def test_competitor_added_and_removed():
    rows = analyze_diff.analyze(
        [extraction(competitors=["株式会社メンバーズ サースプラスカンパニー", "船井総研"])],
        TODAY,
        previous_rows=[sheet_row(competitors="船井総合研究所, 日立ソリューションズ")],
    )
    by_type = {r["change_type"]: r for r in rows}
    assert set(by_type) == {analyze_diff.COMPETITOR_ADDED, analyze_diff.COMPETITOR_REMOVED}
    assert by_type[analyze_diff.COMPETITOR_ADDED]["detail"] == "メンバーズ"
    assert by_type[analyze_diff.COMPETITOR_REMOVED]["detail"] == "日立ソリューションズ"


def test_competitor_spelling_change_is_not_a_change():
    """Normalisation happens before the set diff (§3), so a re-spelling is quiet."""
    rows = analyze_diff.analyze(
        [extraction(competitors=["株式会社日立ソリューションズ"])],
        TODAY,
        previous_rows=[sheet_row(competitors="日立ソリューションズ")],
    )
    assert rows == []


# --- §6-3: URLs and the negative flag --------------------------------------
def test_crosscom_url_added_and_removed():
    rows = analyze_diff.analyze(
        [extraction(urls=["https://cross-com.jp/service/"])],
        TODAY,
        previous_rows=[sheet_row(urls="https://cross-com.jp/about")],
    )
    by_type = {r["change_type"]: r for r in rows}
    assert by_type[analyze_diff.URL_ADDED]["detail"] == "https://cross-com.jp/service"
    assert by_type[analyze_diff.URL_REMOVED]["detail"] == "https://cross-com.jp/about"


def test_negative_flag_on_and_off():
    on = analyze_diff.analyze(
        [extraction(negative=True, negative_detail="旧MA事業の記述")],
        TODAY,
        previous_rows=[sheet_row(negative="FALSE")],
    )
    assert types_of(on) == [analyze_diff.NEGATIVE_ON]
    assert on[0]["detail"] == "旧MA事業の記述"

    off = analyze_diff.analyze(
        [extraction(negative=False)],
        TODAY,
        previous_rows=[sheet_row(negative="TRUE", negative_detail="旧MA事業の記述")],
    )
    assert types_of(off) == [analyze_diff.NEGATIVE_OFF]


# --- error rows -------------------------------------------------------------
def test_error_rows_on_either_side_are_skipped():
    error_extraction = {"prompt_id": "A-1", "model": "claude", "error": "timeout"}
    assert analyze_diff.analyze(
        [error_extraction], TODAY, previous_rows=[sheet_row(mention="FALSE")]
    ) == []

    blank_previous = sheet_row(mention="", negative="")
    assert analyze_diff.analyze(
        [extraction()], TODAY, previous_rows=[blank_previous]
    ) == []


def test_new_prompt_model_pair_has_nothing_to_compare():
    rows = analyze_diff.analyze(
        [extraction(model="gemini")], TODAY, previous_rows=[sheet_row(model="claude")]
    )
    assert rows == []
