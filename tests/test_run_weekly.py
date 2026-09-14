"""Wiring tests for run_weekly (Phase 2 §5, DoD 2 & 4).

Everything external is stubbed. What is being checked is that the orchestrator
calls the right things in the right order and degrades the way §5 requires —
the failure mode unit tests cannot see.
"""
import json

import pytest

import action_log
import citation_gap
import collect_ahrefs
import generate_insight
import notify_slack
import rules_engine
import run_weekly
import sheets_writer

STATS = {
    "date": "2026-08-17",
    "rules": [{"rule_id": "R-P7", "status": "fired", "fired": True, "detail": "d",
               "evidence": []}],
    "fired_rules": ["R-P7"],
    "insufficient_rules": [],
    "mention_rate": {"all": {"this_week": 0.4, "prev_week": 0.3, "delta": 0.1}},
    "data_quality": {"observation_days_this_week": 7, "observation_days_prev_week": 7},
}


REAL_SYNC = action_log.sync_from_report   # fixture で差し替える前の実物


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Stub every side effect and record what the orchestrator did."""
    calls = {"posted": [], "sheet": [], "ahrefs": 0, "scatter": None}

    monkeypatch.setattr(run_weekly, "DATA_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(collect_ahrefs, "collect",
                        lambda date=None: calls.__setitem__("ahrefs", calls["ahrefs"] + 1) or
                        {"aio_keyword_count": 3})
    monkeypatch.setattr(sheets_writer, "write_ahrefs", lambda result: None)
    monkeypatch.setattr(rules_engine, "run", lambda date: dict(STATS, date=date))
    monkeypatch.setattr(
        sheets_writer, "write_weekly_report",
        lambda date, stats, report: calls["sheet"].append((date, report)),
    )
    monkeypatch.setattr(
        notify_slack, "notify_weekly",
        lambda date, report, **kw: calls["posted"].append((date, report)) or True,
    )
    # Phase 5 で追加したフェーズも外部に出ないよう塞ぐ
    monkeypatch.setattr(citation_gap, "analyze",
                        lambda date, **kw: {"rows_for_sheet": [], "rows": []})
    monkeypatch.setattr(sheets_writer, "write_citation_gap", lambda rows: None)
    monkeypatch.setattr(action_log, "sync_from_report",
                        lambda report, date, existing=None, settled_lines=(): [])
    monkeypatch.setattr(sheets_writer, "write_action_log", lambda rows: None)
    # 同日実施の記録(測定設計 2026-09-17 §4)
    calls["same_day"] = {}
    monkeypatch.setattr(sheets_writer, "read_action_log", lambda: [
        {"action_id": "A-003", "実施日": "2026-08-24", "備考": ""},
        {"action_id": "A-004", "実施日": "2026-08-24", "備考": ""},
    ])
    monkeypatch.setattr(sheets_writer, "write_action_log_column",
                        lambda values, column: calls["same_day"].update(values) or len(values))
    # Phase 6: citation_gap 更新後の lk_scatter 再集計
    monkeypatch.setattr(run_weekly, "_refresh_scatter",
                        lambda date: calls.__setitem__("scatter", date) or 0)
    return calls, tmp_path


def run(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_weekly.py"] + argv)
    with pytest.raises(SystemExit) as exc:
        run_weekly.main()
    return exc.value.code


def test_a_suppressed_recommendation_is_not_registered_end_to_end(wired, monkeypatch):
    """A-016(9/7)・A-018(9/14)の再発防止。

    部品ごとのテストは通っていたのに本番で起きた。generate() が postprocess の
    settled_lines を返し忘れ、run_weekly に届いていなかったため。
    モデル呼び出しだけを差し替え、generate → sync_from_report → 書き込みを通して確かめる。
    """
    calls, _ = wired
    settled = [{"action_id": "A-001", "内容": "外部プロフィール更新", "対象": "E-1",
                "根拠rule_id": "R-P7", "状態": "実施済み・効果測定中",
                "提案日": "2026-08-08", "実施日": "2026-08-11"}]
    report = ("## 3. 発火パターンと推奨アクション\n\n"
              "**R-P7(ネガティブ/古い情報の検知)**\n"
              "状態: E-1(会社説明)で終了事業が現在形で記述されている。\n"
              "推奨アクション: 担当者が来週末までに外部プロフィールを更新する。\n")
    monkeypatch.setattr(sheets_writer, "read_action_log", lambda: settled)
    monkeypatch.setattr(generate_insight, "_call_model", lambda *a, **k: report)
    monkeypatch.setattr(action_log, "sync_from_report", REAL_SYNC)
    written = []
    monkeypatch.setattr(sheets_writer, "write_action_log", lambda rows: written.extend(rows))

    run(["--date", "2026-09-14", "--no-slack"], monkeypatch)

    assert calls["sheet"], "所見が書き込まれていない(前提が崩れている)"
    assert "実施済み(A-001・2026-08-11)" in calls["sheet"][0][1], "差し替えが起きていない"
    assert not any("実施済み(" in r["内容"] for r in written), written


def test_same_day_actions_are_recorded_weekly(wired, monkeypatch):
    """実施日は人が入れるので、週次で読み直して同日実施を記録する。"""
    calls, _ = wired
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "本文", "source": "llm"})
    run(["--date", "2026-08-17", "--no-slack"], monkeypatch)
    assert set(calls["same_day"]) == {"A-003", "A-004"}
    assert "分離不能" in calls["same_day"]["A-003"]


def test_scatter_is_refreshed_after_citation_gap(wired, monkeypatch):
    """引用元が変わると競合の顔ぶれも変わるので、週次で取り直す(Phase 6 §2)。"""
    calls, _ = wired
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "本文", "source": "llm"})
    run(["--date", "2026-08-17"], monkeypatch)
    assert calls["scatter"] == "2026-08-17"


def test_happy_path_saves_posts_and_exits_zero(wired, monkeypatch):
    calls, tmp_path = wired
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "## 1. 今週のサマリ\n順調",
                                             "source": "llm", "error": None})

    assert run(["--date", "2026-08-17"], monkeypatch) == 0
    assert calls["ahrefs"] == 1
    assert calls["sheet"] == [("2026-08-17", "## 1. 今週のサマリ\n順調")]
    assert calls["posted"][0][0] == "2026-08-17"

    saved = tmp_path / "reports" / "2026-08-17.json"
    assert saved.exists()
    assert json.loads(saved.read_text(encoding="utf-8"))["fired_rules"] == ["R-P7"]


def test_llm_failure_still_delivers_the_numeric_report(wired, monkeypatch):
    """DoD 4: LLM障害でレポートをゼロにしない。"""
    calls, _ = wired
    monkeypatch.setattr(generate_insight, "_call_model",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("API down")))

    code = run(["--date", "2026-08-17"], monkeypatch)

    assert calls["posted"], "フォールバックでもSlackには配信される"
    assert "自動生成に失敗" in calls["posted"][0][1]
    assert calls["sheet"], "フォールバックでもweekly_reportsに保存される"
    # The run is still marked red so the failure is visible in Actions.
    assert code == 1


def test_ahrefs_failure_does_not_block_the_report(wired, monkeypatch):
    calls, _ = wired
    monkeypatch.setattr(collect_ahrefs, "collect",
                        lambda date=None: (_ for _ in ()).throw(RuntimeError("402")))
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "本文", "source": "llm", "error": None})

    # Ahrefs stays best-effort: it must not turn the run red.
    assert run(["--date", "2026-08-17"], monkeypatch) == 0
    assert calls["posted"], "Ahrefsが落ちても週次所見は配信される"


def test_rules_engine_failure_exits_non_zero(wired, monkeypatch):
    calls, _ = wired
    monkeypatch.setattr(rules_engine, "run",
                        lambda date: (_ for _ in ()).throw(RuntimeError("sheets down")))

    assert run(["--date", "2026-08-17"], monkeypatch) == 1
    assert not calls["posted"], "統計が無い状態で空レポートを送らない"


def test_skip_ahrefs_flag(wired, monkeypatch):
    calls, _ = wired
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "本文", "source": "llm", "error": None})

    run(["--date", "2026-08-17", "--skip-ahrefs"], monkeypatch)
    assert calls["ahrefs"] == 0
    assert calls["posted"]


def test_no_slack_flag_builds_without_posting(wired, monkeypatch):
    calls, _ = wired
    monkeypatch.setattr(generate_insight, "generate",
                        lambda stats, **kw: {"report_md": "本文", "source": "llm", "error": None})

    run(["--date", "2026-08-17", "--no-slack"], monkeypatch)
    assert calls["sheet"], "保存はする"
    assert not calls["posted"], "投稿はしない"
