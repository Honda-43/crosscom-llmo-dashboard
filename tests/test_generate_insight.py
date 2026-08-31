"""Unit tests for generate_insight (Phase 2 §3, DoD 3 & 4)."""
import generate_insight
import insight_style
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


# --- 記述ルール(§B)がプロンプトに載っているか -------------------------------
def test_system_prompt_states_the_number_rules():
    system = generate_insight.build_system_prompt(playbook="x")
    assert "率は%で書く" in system
    assert "ポイント" in system
    assert "横ばい" in system


def test_system_prompt_fixes_the_three_line_format():
    system = generate_insight.build_system_prompt(playbook="x")
    for label in ("状態:", "原因仮説:", "推奨アクション:"):
        assert label in system


def test_system_prompt_bans_the_arrow_everywhere_not_just_in_the_bullets():
    """矢印は3行の箇条書きの外(ウォッチ項目の「前週0→今週0」)でも出る。"""
    system = generate_insight.build_system_prompt(playbook="x")
    assert "本文のどこでも矢印記法(→)を使わない" in system


def test_system_prompt_no_longer_teaches_the_arrow_notation():
    """矢印を禁じながらテンプレートが矢印で例示していると守られない。"""
    system = generate_insight.build_system_prompt(playbook="x")
    assert "状態 → 原因仮説" not in system


def test_system_prompt_lists_every_banned_word():
    system = generate_insight.build_system_prompt(playbook="x")
    for word in insight_style.BANNED_WORDS:
        assert word in system, word


def test_system_prompt_requires_an_explicit_subject():
    system = generate_insight.build_system_prompt(playbook="x")
    assert "主語を明示" in system


def test_system_prompt_uses_the_configured_flat_threshold():
    system = generate_insight.build_system_prompt(
        playbook="x", thresholds={"insight": {"flat_delta_points": 9}})
    assert "±9ポイント以内" in system


# --- 実施済み施策(§A) ------------------------------------------------------
SETTLED = [
    {"action_id": "A-003", "内容": "/btob-marketing-strategy/ 過去形化改修",
     "対象": "E-1", "根拠rule_id": "R-P8", "状態": "実施済み・効果測定中",
     "提案日": "2026-08-24", "実施日": "2026-08-24"},
]


def test_user_prompt_lists_the_settled_actions():
    user = generate_insight.build_user_prompt(STATS, SETTLED)
    assert "A-003" in user
    assert "再提案しないでください" in user


def test_user_prompt_says_so_when_nothing_is_settled():
    user = generate_insight.build_user_prompt(STATS, [])
    assert "まだ着手済みの施策はありません" in user


def test_user_prompt_carries_the_display_numbers():
    """小数を写させないため、書いてよい表記を渡す。"""
    user = generate_insight.build_user_prompt(STATS)
    assert "言及率(全体): 42%" in user


def test_every_kgi_metric_gets_a_display_form():
    """プロンプトに無い指標は、モデルが stats.json の生値(0.0)から写すしかない。"""
    stats = dict(STATS, kgi=dict(
        STATS["kgi"],
        ai_key_events={"this_week": 0.0, "prev_week": 0.0, "delta": 0.0},
        branded_impressions={"this_week": 120.0, "prev_week": 98.0, "delta": 22.0},
    ))
    user = generate_insight.build_user_prompt(stats)
    assert "AI経由キーイベント: 0件" in user
    assert "指名検索表示: 120回" in user


def test_generate_reads_the_action_log_when_not_given(monkeypatch):
    seen = {}
    monkeypatch.setattr(generate_insight, "_load_actions",
                        lambda: seen.setdefault("read", True) or SETTLED)
    monkeypatch.setattr(generate_insight, "_call_model",
                        lambda *a, **k: "## 1. 今週のサマリ\n順調")
    generate_insight.generate(STATS, playbook="x")
    assert seen["read"] is True


def test_a_settled_action_is_replaced_in_the_report(monkeypatch):
    report = (
        "## 3. 発火パターンと推奨アクション\n\n"
        "**R-P8(旧事業URLの引用)**\n"
        "状態: E-1で旧パスが2件引用されている。\n"
        "原因仮説: 旧記事が残っている。\n"
        "推奨アクション: 担当者が来週末までに /btob-marketing-strategy/ を301統合する。\n"
    )
    monkeypatch.setattr(generate_insight, "_call_model", lambda *a, **k: report)
    result = generate_insight.generate(STATS, playbook="x", actions=SETTLED)
    assert "実施済み(A-003・2026-08-24)。効果測定中" in result["report_md"]
    assert "301統合" not in result["report_md"]
    assert result["suppressed"]


def test_an_unrelated_action_is_left_alone(monkeypatch):
    report = (
        "## 3. 発火パターンと推奨アクション\n\n"
        "**R-P7(ネガティブ)**\n"
        "状態: B-3で終了事業の記述がある。\n"
        "推奨アクション: 担当者が来週末までにページを修正する。\n"
    )
    monkeypatch.setattr(generate_insight, "_call_model", lambda *a, **k: report)
    result = generate_insight.generate(STATS, playbook="x", actions=SETTLED)
    assert "ページを修正する" in result["report_md"]
    assert not result["suppressed"]


# --- 応答の打ち切り(§C) ----------------------------------------------------
def test_a_truncated_response_is_retried_with_a_bigger_budget(monkeypatch):
    calls = []

    def call(system, user, model, max_tokens=generate_insight.INSIGHT_MAX_TOKENS):
        calls.append(max_tokens)
        if len(calls) == 1:
            raise generate_insight.TruncatedResponse("max_tokens で打ち切り")
        return "## 1. 今週のサマリ\n順調"

    monkeypatch.setattr(generate_insight, "_call_model", call)
    result = generate_insight.generate(STATS, playbook="x", actions=[])
    assert result["source"] == "llm"
    assert calls[1] > calls[0], "2回目は枠を広げて呼び直す"


def test_a_still_truncated_response_falls_back(monkeypatch):
    def boom(*a, **k):
        raise generate_insight.TruncatedResponse("max_tokens で打ち切り")

    monkeypatch.setattr(generate_insight, "_call_model", boom)
    result = generate_insight.generate(STATS, playbook="x", actions=[])
    assert result["source"] == "fallback"
    assert "max_tokens" in result["error"]


def test_missing_sections_are_reported_as_a_warning(monkeypatch):
    """末尾が切れた所見を黙って配信しない(2026-08 の欠陥)。"""
    monkeypatch.setattr(generate_insight, "_call_model",
                        lambda *a, **k: "## 1. 今週のサマリ\n順調")
    result = generate_insight.generate(STATS, playbook="x", actions=[])
    assert any("セクションが欠落" in w for w in result["warnings"])


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
    """§B: 率は%、率の差分はポイント。小数の生値は出さない。"""
    report = generate_insight.fallback_report(STATS)
    assert "42%" in report and "+8ポイント" in report
    assert "0.42" not in report and "0.08" not in report
    assert "船井総合研究所" in report
    assert "31" in report and "12" in report
    assert "R-P7" in report
    assert "R-P5" in report  # insufficient は明示する


def test_fallback_report_calls_a_small_move_flat():
    """§B: 前週比が±5ポイント以内は「横ばい」。実数は括弧で残す。"""
    report = generate_insight.fallback_report(STATS)
    assert "横ばい(-5ポイント)" in report


def test_fallback_report_uses_counts_not_points_for_kgi():
    """成果指標は率ではないので、差分に「ポイント」を使わない。"""
    report = generate_insight.fallback_report(STATS)
    assert "+7セッション" in report
    assert "-3クリック" in report


def test_fallback_report_glosses_the_fired_pattern():
    """§B: 発火パターンは初出時に日本語の説明を併記する。"""
    report = generate_insight.fallback_report(STATS)
    assert "R-P7(ネガティブ・古い情報:" in report


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
