"""Unit tests for notify_slack (Phase 1 §4 / §6-5).

日次は「状態を示す通知 + 詳細はリンク先」。3階層のフォーマットと、
negative_detail の本文を載せないことをテストで固定する。
"""
import analyze_diff
import notify_slack

DATE = "2026-08-18"


def negative_extraction(prompt_id="E-1", model="claude",
                        detail="旧MA/メール配信事業を現在の主要事業として記述している"):
    return {
        "prompt_id": prompt_id, "model": model, "error": None,
        "mention": True, "negative_or_outdated": True, "negative_detail": detail,
    }


def clean_extraction(prompt_id="A-1", model="claude", mention=True):
    return {
        "prompt_id": prompt_id, "model": model, "error": None,
        "mention": mention, "negative_or_outdated": False, "negative_detail": None,
    }


def change(change_type, prompt_id="B-2", model="gemini", detail=""):
    return {
        "date": DATE, "prompt_id": prompt_id, "model": model,
        "change_type": change_type, "before": "", "after": "", "detail": detail,
    }


def observation(date, prompt_id="E-1", model="claude", mention="TRUE",
                negative="FALSE"):
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "mention": mention, "negative_or_outdated": negative}


# --- 1行目・2行目(サマリ) ------------------------------------------------
def test_first_line_is_the_fixed_header():
    text = notify_slack.build_message(DATE)
    assert text.splitlines()[0] == f"📊 *LLMO日次* | {DATE}"


def test_summary_line_carries_rate_top_entity_and_negative_count():
    text = notify_slack.build_message(
        DATE,
        extractions=[clean_extraction("A-1"), clean_extraction("A-2", mention=False),
                     negative_extraction()],
        sov_rows=[{"date": DATE, "pillar": "all", "entity": "クロスコム",
                   "mention_count": "5"},
                  {"date": DATE, "pillar": "all", "entity": "メンバーズ",
                   "mention_count": "3"}],
    )
    line = text.splitlines()[1]
    assert "言及率 *50%*" in line       # E-1は分母から除く: A-1のみTRUE / A-1,A-2
    assert "SoV首位 *クロスコム*" in line
    assert "ネガ検知 *1件*" in line


def test_summary_line_shows_the_day_over_day_arrow():
    yesterday = [observation("2026-08-17", "A-1", mention="FALSE"),
                 observation("2026-08-17", "A-2", mention="FALSE")]
    up = notify_slack.build_message(
        DATE, extractions=[clean_extraction("A-1"), clean_extraction("A-2")],
        observations=yesterday)
    assert "↑(+100%)" in up.splitlines()[1]

    down = notify_slack.build_message(
        DATE,
        extractions=[clean_extraction("A-1", mention=False),
                     clean_extraction("A-2", mention=False)],
        observations=[observation("2026-08-17", "A-1"), observation("2026-08-17", "A-2")])
    assert "↓(-100%)" in down.splitlines()[1]

    flat = notify_slack.build_message(
        DATE, extractions=[clean_extraction("A-1")],
        observations=[observation("2026-08-17", "A-1")])
    assert "→(±0)" in flat.splitlines()[1]


def test_summary_line_omits_the_arrow_without_history():
    line = notify_slack.build_message(DATE, extractions=[clean_extraction()]).splitlines()[1]
    assert "↑" not in line and "↓" not in line and "→" not in line


def test_e1_is_excluded_from_the_rate():
    """E-1は必ず言及されるので分母に入れない(build_summaryと同じ定義)。"""
    text = notify_slack.build_message(
        DATE, extractions=[negative_extraction(), clean_extraction("A-1", mention=False)])
    assert "言及率 *0%*" in text.splitlines()[1]


# --- 3行目以降(変化イベント) ----------------------------------------------
def test_quiet_day_still_posts_with_no_change_line():
    text = notify_slack.build_message(DATE, extractions=[clean_extraction()])
    assert "変化なし" in text
    assert text.splitlines()[0].startswith("📊")


def test_mention_events_are_one_line_each():
    text = notify_slack.build_message(
        DATE,
        changes=[change(analyze_diff.MENTION_GAINED, "B-1", "gemini"),
                 change(analyze_diff.MENTION_GAINED, "B-2", "claude"),
                 change(analyze_diff.MENTION_LOST, "A-3", "claude")],
    )
    assert "📈 言及獲得: B-1(gemini), B-2(claude)" in text
    assert "📉 言及消失: A-3(claude)" in text
    assert "変化なし" not in text


def test_negative_line_hides_the_detail_body():
    """本文は載せず種別だけ。詳細はスプレッドシートで見る。"""
    body = "旧MA/メール配信事業の記述が含まれている。回答では『BtoB領域に特化して…』と記載"
    text = notify_slack.build_message(DATE, extractions=[negative_extraction(detail=body)])
    assert "旧事業(MA/メール配信)の記述" in text
    assert "BtoB領域に特化して" not in text
    assert body not in text


def test_negative_line_shows_prompt_model_and_streak():
    history = [observation(d, negative="TRUE")
               for d in ("2026-08-15", "2026-08-16", "2026-08-17")]
    text = notify_slack.build_message(
        DATE, extractions=[negative_extraction()], observations=history)
    assert "⚠️ E-1 × claude —" in text
    assert "（継続4日目）" in text  # 8/15,16,17 + 当日


def test_first_day_of_detection_says_so():
    history = [observation("2026-08-17", negative="FALSE")]
    text = notify_slack.build_message(
        DATE, extractions=[negative_extraction()], observations=history)
    assert "（本日から）" in text


def test_streak_breaks_on_a_clean_day():
    history = [observation("2026-08-14", negative="TRUE"),
               observation("2026-08-15", negative="FALSE"),
               observation("2026-08-16", negative="TRUE"),
               observation("2026-08-17", negative="TRUE")]
    assert notify_slack.negative_streak(history, "E-1", "2026-08-17") == 2


def test_streak_is_per_prompt_not_per_model():
    """片方のモデルで出ていればその日は検知ありとして数える。"""
    history = [observation("2026-08-17", model="claude", negative="TRUE"),
               observation("2026-08-17", model="gemini", negative="FALSE")]
    assert notify_slack.negative_streak(history, "E-1", "2026-08-17") == 1


def test_negative_kind_stays_within_the_character_budget():
    for detail in ["旧MA事業の記述", "誤情報が含まれる", "古い情報", "よく分からない何か", ""]:
        assert len(notify_slack.negative_kind(detail)) <= notify_slack.KIND_MAX_CHARS


def test_failures_are_reported_without_the_error_body():
    text = notify_slack.build_message(
        DATE, failures=["collect_ga4: 429 RESOURCE_EXHAUSTED quota exceeded"])
    assert "❌ パイプライン一部失敗: collect_ga4" in text
    assert "RESOURCE_EXHAUSTED" not in text


def test_long_event_lists_are_truncated():
    changes = [change(analyze_diff.MENTION_LOST, f"A-{i}", "claude") for i in range(20)]
    text = notify_slack.build_message(DATE, changes=changes)
    assert "ほか8件" in text


# --- リンク ----------------------------------------------------------------
def test_links_are_appended(monkeypatch):
    monkeypatch.setattr(notify_slack, "spreadsheet_url", lambda: "https://sheet/x")
    monkeypatch.setattr(notify_slack, "LOOKER_STUDIO_URL", "https://looker/y")
    text = notify_slack.build_message(DATE)
    assert text.endswith("<https://sheet/x|スプレッドシート>  |  <https://looker/y|Looker Studio>")


def test_looker_link_is_omitted_when_unset(monkeypatch):
    monkeypatch.setattr(notify_slack, "spreadsheet_url", lambda: "https://sheet/x")
    monkeypatch.setattr(notify_slack, "LOOKER_STUDIO_URL", "")
    text = notify_slack.build_message(DATE)
    assert "Looker" not in text
    assert "スプレッドシート" in text


# --- 送信 ------------------------------------------------------------------
def test_missing_webhook_never_raises(capsys):
    assert notify_slack.notify(DATE, [negative_extraction()], webhook="") is False
    assert "SLACK_WEBHOOK_URL is not set" in capsys.readouterr().out


def test_message_is_posted_when_configured(monkeypatch):
    posted = {}
    monkeypatch.setattr(notify_slack, "_post",
                        lambda text, webhook: posted.update(text=text, webhook=webhook))
    assert notify_slack.notify(DATE, [negative_extraction()],
                               webhook="https://hooks/x") is True
    assert posted["webhook"] == "https://hooks/x"
    assert posted["text"].startswith("📊")


def test_quiet_day_is_still_posted(monkeypatch):
    """状態を毎日出す設計。無音の日と壊れた日を区別できなくしない。"""
    posted = {}
    monkeypatch.setattr(notify_slack, "_post",
                        lambda text, webhook: posted.update(text=text))
    assert notify_slack.notify(DATE, [clean_extraction()],
                               webhook="https://hooks/x") is True
    assert "変化なし" in posted["text"]


# --- --test ----------------------------------------------------------------
def test_test_message_covers_every_line_type():
    text = notify_slack._test_message(DATE)
    assert text.startswith("📊 *LLMO日次*")
    assert "言及率" in text and "SoV首位" in text and "ネガ検知" in text
    assert "⚠️ E-1 × claude" in text and "継続" in text
    assert "📈 言及獲得" in text and "📉 言及消失" in text
    assert "❌ パイプライン一部失敗" in text
    assert "【テスト送信】旧MA/メール配信事業を現在の主要事業として" not in text


def test_quiet_test_message_shows_the_no_change_line():
    text = notify_slack._test_quiet_message(DATE)
    assert "変化なし" in text
    assert "言及率" in text


# --- 週次は現行フォーマット維持(§4) ----------------------------------------
def test_weekly_message_has_the_required_header():
    text = notify_slack.build_weekly_message("2026-08-17", "## 1. 今週のサマリ\n順調")
    assert text.startswith("*LLMO週次所見 2026-08-17*")


def test_weekly_message_converts_markdown_to_mrkdwn():
    text = notify_slack.build_weekly_message("2026-08-17", "## 見出し\n**太字**の行")
    assert "*見出し*" in text
    assert "**太字**" not in text


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


def test_notify_weekly_posts_when_configured(monkeypatch):
    posted = {}
    monkeypatch.setattr(notify_slack, "_post", lambda text, webhook: posted.update(text=text))
    assert notify_slack.notify_weekly("2026-08-17", "## 1. 今週のサマリ\n順調",
                                      webhook="https://hooks/x") is True
    assert "LLMO週次所見" in posted["text"]
