"""Unit tests for notify_slack (Phase 1 §4 / §6-5)."""
import analyze_diff
import notify_slack

DATE = "2026-08-17"


def negative_extraction(prompt_id="A-1", model="claude", detail="旧MA事業の記述"):
    return {
        "prompt_id": prompt_id, "model": model, "error": None,
        "negative_or_outdated": True, "negative_detail": detail,
    }


def change(change_type, prompt_id="B-2", model="gemini", detail=""):
    return {
        "date": DATE, "prompt_id": prompt_id, "model": model,
        "change_type": change_type, "before": "", "after": "", "detail": detail,
    }


def test_quiet_day_sends_nothing():
    assert notify_slack.build_message(DATE, [], [], []) is None


def test_clean_observations_are_not_an_alert():
    extractions = [{"prompt_id": "A-1", "model": "claude", "negative_or_outdated": False}]
    changes = [change(analyze_diff.RANK_UP), change(analyze_diff.COMPETITOR_ADDED)]
    assert notify_slack.build_message(DATE, extractions, changes, []) is None


def test_negative_section_comes_first():
    text = notify_slack.build_message(
        DATE,
        extractions=[negative_extraction()],
        changes=[change(analyze_diff.MENTION_GAINED)],
        failures=["collect_ga4: boom"],
    )
    assert text.splitlines()[0] == f"*LLMO日次アラート — {DATE}*"
    positions = [
        text.index("⚠️ ネガティブ/誤情報検知"),
        text.index("📈 言及獲得"),
        text.index("❌ パイプライン一部失敗"),
    ]
    assert positions == sorted(positions)
    assert "A-1 / claude — 旧MA事業の記述" in text
    assert "B-2 / gemini" in text
    assert "collect_ga4: boom" in text


def test_negative_flag_on_change_alone_triggers_the_section():
    text = notify_slack.build_message(
        DATE, [], [change(analyze_diff.NEGATIVE_ON, "A-3", "claude", "古い事業説明")], []
    )
    assert "⚠️ ネガティブ/誤情報検知(1件)" in text
    assert "A-3 / claude — 古い事業説明" in text


def test_same_observation_is_not_reported_twice():
    text = notify_slack.build_message(
        DATE,
        extractions=[negative_extraction("A-1", "claude")],
        changes=[change(analyze_diff.NEGATIVE_ON, "A-1", "claude", "旧MA事業の記述")],
        failures=[],
    )
    assert "⚠️ ネガティブ/誤情報検知(1件)" in text


def test_mention_lost_section():
    text = notify_slack.build_message(
        DATE, [], [change(analyze_diff.MENTION_LOST, "A-3", "claude")], []
    )
    assert "📉 言及消失(1件)" in text
    assert "📈" not in text


def test_missing_webhook_never_raises(capsys):
    sent = notify_slack.notify(DATE, [negative_extraction()], [], [], webhook="")
    assert sent is False
    assert "SLACK_WEBHOOK_URL is not set" in capsys.readouterr().out


def test_message_is_posted_when_configured(monkeypatch):
    posted = {}
    monkeypatch.setattr(
        notify_slack, "_post", lambda text, webhook: posted.update(text=text, webhook=webhook)
    )
    sent = notify_slack.notify(DATE, [negative_extraction()], [], [], webhook="https://hooks/x")
    assert sent is True
    assert posted["webhook"] == "https://hooks/x"
    assert "⚠️" in posted["text"]


def _must_not_be_called(*args, **kwargs):
    raise AssertionError("_post must not be called on a quiet day")


def test_quiet_day_posts_nothing_even_with_a_webhook(monkeypatch):
    monkeypatch.setattr(notify_slack, "_post", _must_not_be_called)
    assert notify_slack.notify(DATE, [], [], [], webhook="https://hooks/x") is False


def test_test_flag_builds_a_message_with_every_section():
    text = notify_slack._test_message(DATE)
    for marker in ("⚠️", "📈", "📉", "❌"):
        assert marker in text


def test_spreadsheet_link_is_appended(monkeypatch):
    monkeypatch.setattr(notify_slack, "spreadsheet_url", lambda: "https://sheet/x")
    text = notify_slack.build_message(DATE, [negative_extraction()], [], [])
    assert text.endswith("<https://sheet/x|スプレッドシートを開く>")


def test_long_sections_are_truncated():
    changes = [
        change(analyze_diff.MENTION_LOST, f"A-{i}", "claude") for i in range(30)
    ]
    text = notify_slack.build_message(DATE, [], changes, [])
    assert "📉 言及消失(30件)" in text
    assert "ほか 15 件" in text
