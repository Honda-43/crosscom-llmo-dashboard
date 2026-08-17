"""Unit tests for generate_insight (Phase 2 §3, DoD 3 & 4)."""
import generate_insight
import notify_slack

STATS = {
    "date": "2026-08-17",
    "mention_rate": {
        "all": {"this_week": 0.42, "prev_week": 0.34, "delta": 0.08},
        "pillar_a": {"this_week": 0.5, "prev_week": 0.3, "delta": 0.2},
        "pillar_b": {"this_week": 0.33, "prev_week": 0.38, "delta": -0.05},
    },
    "sov": {"all": {"observed_total": 12, "prev_week_competitor_count": 3, "entities": [
        {"entity": "船井総合研究所", "mention_count": 7, "share": 0.58,
         "prev_week_count": 4, "delta": 3},
    ]}},
    "kgi": {
        "ai_sessions": {"this_week": 31, "prev_week": 24, "delta": 7},
        "branded_clicks": {"this_week": 12, "prev_week": 15, "delta": -3},
    },
    "changes": {"mention_gained": 2},
    "data_quality": {"observation_days_this_week": 7, "observation_days_prev_week": 6},
    "rules": [
        {"rule_id": "R-P7", "status": "fired", "fired": True,
         "detail": "ネガティブ/古い情報を1件検知", "evidence": []},
        {"rule_id": "R-P4", "status": "not_fired", "fired": False, "detail": "", "evidence": []},
        {"rule_id": "R-P5", "status": "insufficient_data", "fired": False,
         "detail": "4週分のrank中央値が揃うprompt_idがない", "evidence": []},
    ],
    "fired_rules": ["R-P7"],
    "insufficient_rules": ["R-P5"],
}


# --- prompt construction ---------------------------------------------------
def test_system_prompt_embeds_the_playbook():
    system = generate_insight.build_system_prompt(playbook="# PLAYBOOK-MARKER\nP-7の対処法")
    assert "PLAYBOOK-MARKER" in system
    assert "P-7の対処法" in system


def test_system_prompt_forbids_inventing_numbers():
    system = generate_insight.build_system_prompt(playbook="x")
    assert "stats.jsonに存在しない数値" in system
    assert "禁止" in system


def test_system_prompt_forbids_treating_noise_as_actionable():
    """レビュー指摘1: ノイズ域の増減を要対応と書かせない。"""
    system = generate_insight.build_system_prompt(playbook="x")
    assert "noise_zone" in system
    assert "要対応" in system
    assert "推奨アクションの根拠にしてはならない" in system


def test_system_prompt_warns_about_partial_coverage():
    system = generate_insight.build_system_prompt(playbook="x")
    assert "coverage" in system
    assert "問題なし" in system


def test_system_prompt_fixes_the_five_sections():
    system = generate_insight.build_system_prompt(playbook="x")
    for section in ("今週のサマリ", "数値ハイライト", "発火パターンと推奨アクション",
                    "ウォッチ項目", "判定不能・データ不足"):
        assert section in system


def test_system_prompt_states_the_character_limit():
    assert "1234字以内" in generate_insight.build_system_prompt(playbook="x", max_chars=1234)


def test_user_prompt_carries_stats_and_nothing_else():
    user = generate_insight.build_user_prompt(STATS)
    assert "船井総合研究所" in user
    assert "R-P7" in user
    # raw answers must never reach the model
    assert "answer" not in user


def test_playbook_file_is_present_and_covers_every_pattern():
    """config/playbook.md は §3 の必須ファイル。全ルールの根拠が要る。"""
    playbook = generate_insight.load_playbook()
    for pattern in ("P-2", "P-4", "P-5", "P-7", "P-8", "P-15", "DROP"):
        assert pattern in playbook, pattern


# --- fallback (DoD 4) ------------------------------------------------------
def test_fallback_report_has_all_five_sections():
    report = generate_insight.fallback_report(STATS)
    for section in generate_insight._SECTIONS:
        assert section in report


def test_fallback_report_uses_only_stats_numbers():
    report = generate_insight.fallback_report(STATS)
    assert "0.42" in report and "+0.08" in report
    assert "船井総合研究所" in report
    assert "31" in report and "12" in report
    assert "R-P7" in report
    assert "R-P5" in report  # insufficient は明示する


def test_fallback_report_flags_itself_as_degraded():
    assert "自動生成に失敗" in generate_insight.fallback_report(STATS)


def test_fallback_report_marks_noise_zone_metrics():
    noisy = dict(STATS, kgi={
        "ai_sessions": {"this_week": 2, "prev_week": 4, "delta": -2, "noise_zone": True},
        "branded_clicks": {"this_week": 4, "prev_week": 10, "delta": -6, "noise_zone": True},
        "noise_floor": 10,
        "noise_zone_metrics": ["ai_sessions", "branded_clicks"],
    })
    report = generate_insight.fallback_report(noisy)
    assert "母数が小さく判断できない水準" in report
    assert "判断材料にしない" in report


def test_fallback_report_leaves_healthy_metrics_unmarked():
    healthy = dict(STATS, kgi={
        "ai_sessions": {"this_week": 40, "prev_week": 24, "delta": 16, "noise_zone": False},
        "branded_clicks": {"this_week": 30, "prev_week": 25, "delta": 5, "noise_zone": False},
        "noise_floor": 10, "noise_zone_metrics": [],
    })
    assert "母数が小さく" not in generate_insight.fallback_report(healthy)


def test_fallback_report_survives_an_empty_stats():
    report = generate_insight.fallback_report({"date": "2026-08-17", "rules": []})
    assert "今週のサマリ" in report
    assert "発火パターンはありません" in report


def test_generate_falls_back_when_the_model_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("API 529 overloaded")

    monkeypatch.setattr(generate_insight, "_call_model", boom)
    result = generate_insight.generate(STATS, playbook="x")
    assert result["source"] == "fallback"
    assert "API 529 overloaded" in result["error"]
    assert "今週のサマリ" in result["report_md"]


def test_generate_falls_back_on_an_empty_response(monkeypatch):
    monkeypatch.setattr(generate_insight, "_call_model", lambda *a, **k: "   ")
    result = generate_insight.generate(STATS, playbook="x")
    assert result["source"] == "fallback"


def test_generate_uses_the_model_output_when_it_works(monkeypatch):
    monkeypatch.setattr(generate_insight, "_call_model", lambda *a, **k: "## 1. 今週のサマリ\n順調")
    result = generate_insight.generate(STATS, playbook="x")
    assert result["source"] == "llm"
    assert result["error"] is None
    assert "順調" in result["report_md"]


def test_generate_passes_the_configured_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        generate_insight, "_call_model",
        lambda system, user, model: seen.setdefault("model", model) or "報告",
    )
    generate_insight.generate(STATS, model="claude-sonnet-5", playbook="x")
    assert seen["model"] == "claude-sonnet-5"


# --- Slack delivery --------------------------------------------------------
def test_weekly_message_has_the_required_header():
    text = notify_slack.build_weekly_message("2026-08-17", "## 1. 今週のサマリ\n順調")
    assert text.startswith("*LLMO週次所見 2026-08-17*")


def test_weekly_message_converts_markdown_to_mrkdwn():
    text = notify_slack.build_weekly_message("2026-08-17", "## 見出し\n**太字**の行")
    assert "*見出し*" in text
    assert "**太字**" not in text
    assert "*太字*" in text


def test_weekly_message_does_not_duplicate_the_title():
    report = "# LLMO週次所見 2026-08-17\n\n## 1. 今週のサマリ\n順調"
    text = notify_slack.build_weekly_message("2026-08-17", report)
    assert text.count("LLMO週次所見 2026-08-17") == 1


def test_weekly_message_is_truncated_when_huge():
    text = notify_slack.build_weekly_message("2026-08-17", "あ" * 60_000)
    assert len(text) < 40_000
    assert "以下略" in text


def test_notify_weekly_skips_an_empty_report():
    assert notify_slack.notify_weekly("2026-08-17", "", webhook="https://hooks/x") is False


def test_notify_weekly_without_a_webhook_never_raises(capsys):
    assert notify_slack.notify_weekly("2026-08-17", "本文", webhook="") is False
    assert "SLACK_WEBHOOK_URL is not set" in capsys.readouterr().out


def test_notify_weekly_posts_when_configured(monkeypatch):
    posted = {}
    monkeypatch.setattr(notify_slack, "_post",
                        lambda text, webhook: posted.update(text=text))
    assert notify_slack.notify_weekly("2026-08-17", "## 1. 今週のサマリ\n順調",
                                      webhook="https://hooks/x") is True
    assert "LLMO週次所見" in posted["text"]
