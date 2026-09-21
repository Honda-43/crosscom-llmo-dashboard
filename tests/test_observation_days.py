"""週次所見の「観測日数」の読み方(2026-09-21).

2026-09-14(d18af8e)で日次LLM観測を火・木・土の週3日にした。固定したいのは3つ:

1. 週3日は正常。3日を「観測日数不足」と書かせない(不足は3日未満のときだけ)。
2. 前週比は観測の方式と日数が同じ週どうしでだけ比べる。9/14 の変更をまたぐ週
   (今週が週3日・前週が毎日)は「観測方式の変更週のため前週比は参考値」。
3. rules_thresholds.yaml と generate_insight のプロンプトの両方に反映されている。
"""
import generate_insight
import rules_engine

CFG = rules_engine.load_thresholds().get("observation") or {}


def test_the_thresholds_file_declares_the_weekly_schedule():
    assert CFG["expected_days_per_week"] == 3
    assert CFG["legacy_days_per_week"] == 7
    assert CFG["new_schedule_from"] == "2026-09-15"


def test_three_days_is_normal_not_short():
    got = rules_engine.observation_quality("2026-09-28", 3, 3, CFG)
    assert got["expected_days_per_week"] == 3
    assert got["observation_days_short"] is False
    assert got["comparable_with_prev_week"] is True and got["comparison_note"] == ""


def test_fewer_than_three_days_is_short():
    got = rules_engine.observation_quality("2026-09-28", 2, 3, CFG)
    assert got["observation_days_short"] is True
    assert got["comparable_with_prev_week"] is False
    assert "今週2日・前週3日" in got["comparison_note"]


def test_the_week_of_the_change_is_a_reference_only_comparison():
    """9/15〜21(週3日)と 9/8〜14(毎日)は比べない。"""
    got = rules_engine.observation_quality("2026-09-21", 3, 7, CFG)
    assert got["observation_days_short"] is False
    assert got["comparable_with_prev_week"] is False
    assert got["comparison_note"] == "観測方式の変更週のため前週比は参考値"


def test_a_week_that_straddles_the_change_is_also_reference_only():
    got = rules_engine.observation_quality("2026-09-17", 2, 7, CFG)
    assert got["comparison_note"] == "観測方式の変更週のため前週比は参考値"


def test_weeks_before_the_change_expect_seven_days():
    got = rules_engine.observation_quality("2026-09-14", 7, 7, CFG)
    assert got["expected_days_per_week"] == 7 and got["comparable_with_prev_week"]


def test_build_stats_carries_the_new_fields():
    stats = rules_engine.build_stats("2026-09-21", {}, thresholds=rules_engine.load_thresholds(),
                                     legacy_paths=[])
    quality = stats["data_quality"]
    for key in ("expected_days_per_week", "observation_days_short",
                "comparable_with_prev_week", "comparison_note"):
        assert key in quality, quality


def _stats(comparable, note="", short=False, days=3):
    series = {"this_week": 0.39, "prev_week": 0.46, "delta": -0.07}
    return {
        "date": "2026-09-21",
        "mention_rate": {"all": series, "pillar_a": series, "pillar_b": series},
        "sov": {"all": {"entities": [{"entity": "クロスコム", "share": 0.39,
                                      "mention_count": 14, "delta": -24}]}},
        "kgi": {"ai_sessions": {"this_week": 0, "prev_week": 2, "delta": -2}},
        "rules": [], "fired_rules": [], "insufficient_rules": [],
        "data_quality": {"observation_days_this_week": days, "observation_days_prev_week": 7,
                         "expected_days_per_week": 3, "observation_days_short": short,
                         "comparable_with_prev_week": comparable, "comparison_note": note},
    }


def test_the_prompt_tells_the_model_three_days_is_normal():
    system = generate_insight.build_system_prompt(playbook="(playbook)")
    assert "火・木・土の週3日が正常" in system
    assert "observation_days_short が true のときだけ" in system
    assert "comparable_with_prev_week が false" in system
    assert "(参考値)" in system


def test_reference_only_weeks_mark_the_observation_numbers():
    text = generate_insight._formatted_numbers(
        _stats(False, "観測方式の変更週のため前週比は参考値"), flat=5)
    assert "観測方式の変更週のため前週比は参考値" in text
    rate_lines = [l for l in text.splitlines() if l.startswith("- 言及")]
    assert rate_lines and all("(参考値)" in l for l in rate_lines), rate_lines
    kgi_lines = [l for l in text.splitlines() if "成果指標" in l]
    assert kgi_lines and not any("(参考値)" in l for l in kgi_lines), "KGIは対象外"


def test_comparable_weeks_are_not_marked():
    text = generate_insight._formatted_numbers(_stats(True), flat=5)
    assert "(参考値)" not in text and "前週比の扱い" not in text


def test_the_fallback_report_does_not_call_three_days_short():
    report = generate_insight.fallback_report(
        _stats(False, "観測方式の変更週のため前週比は参考値"), thresholds={})
    assert "観測日数不足" not in report
    assert "(週3日が正常)" in report
    assert "観測方式の変更週のため前週比は参考値" in report


def test_the_fallback_report_flags_a_real_shortfall():
    report = generate_insight.fallback_report(
        _stats(False, "観測日数が前週と異なる(今週2日・前週3日)ため前週比は参考値",
               short=True, days=2), thresholds={})
    assert "観測日数不足" in report
