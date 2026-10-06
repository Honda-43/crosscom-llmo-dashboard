"""観測の変更に伴う誤読防止の注記のテスト(2026-10-06).

1. Claude 停止中は、週次所見の §5 に R-P7 の注記を固定で入れる(モデル任せにしない)
2. 同じ文言をアプリの R3 のキャプションと Looker(lk_events)に出す
3. 言及率の母数が 2026-10-06 に 14本→7本に変わったことを、グラフ(R2)の注釈・lk_events・README に記録する
"""
import json
from pathlib import Path

import pytest

import generate_insight
import looker_tabs
import observation_notes as notes
import settings

ROOT = Path(__file__).resolve().parent.parent
R_P7 = ("R-P7(ネガティブ/古い情報)はGeminiの観測のみで判定している。2026-10-06以前の検知はすべてClaudeのE-1回答であり、"
        "Geminiでの最後の検知は2026-09-19。発火しないことを解消と読まないこと")


@pytest.fixture
def claude_stop(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text('planned_stop_from: "2026-10-06"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", cfg)


def test_the_note_is_the_agreed_wording():
    assert notes.R_P7_NOTE == R_P7


def test_section5_lines_while_claude_is_stopped(claude_stop):
    first = notes.weekly_section5_lines("2026-10-12")          # 前週比が 10/06 をまたぐ
    assert first == [f"- {R_P7}", f"- {notes.DENOMINATOR_NOTE}"]
    # 10/19 の週次は 10/13〜10/19 と前週 10/06〜10/12 の比較で、どちらも変更後。母数の注記は出さない
    assert notes.weekly_section5_lines("2026-10-19") == [f"- {R_P7}"], "またがない週は母数の注記を出さない"


def test_no_note_before_the_stop():
    assert notes.weekly_section5_lines("2026-09-28") == []


def test_ensure_section5_appends_once_at_the_end_of_section5():
    report = "## 4. ウォッチ項目\nなし\n\n## 5. 判定不能・データ不足\n- R-P5: 母数不足\n\n"
    got = notes.ensure_section5(report, [f"- {R_P7}"])
    assert got.rstrip().endswith(f"- {R_P7}") and got.index("## 4.") < got.index(R_P7)
    assert notes.ensure_section5(got, [f"- {R_P7}"]) == got, "二重に入れない"
    with_next = "## 5. 判定不能・データ不足\nなし\n\n## 6. 付録\nx\n"
    assert notes.ensure_section5(with_next, ["- 注記"]).split("## 6.")[0].rstrip().endswith("- 注記")


def test_the_llm_report_always_gets_the_note(claude_stop, monkeypatch):
    """モデルが書かなくても §5 に必ず入る。"""
    monkeypatch.setattr(generate_insight, "_call_model",
                        lambda *a, **k: "## 1. 今週のサマリ\nx\n\n## 5. 判定不能・データ不足\nなし\n")
    monkeypatch.setattr(generate_insight, "postprocess", lambda report, *a, **k: {
        "report_md": report, "suppressed": [], "frozen": [], "warnings": [], "settled_lines": []})
    monkeypatch.setattr(generate_insight.experiment_freeze, "load", lambda date: None)
    got = generate_insight.generate({"date": "2026-10-26"}, model="gemini-3.5-flash", actions=[])
    assert got["source"] == "llm" and got["report_md"].rstrip().endswith(f"- {R_P7}")


def test_the_numbers_only_report_gets_the_note(claude_stop):
    stats = json.loads((ROOT / "data" / "reports" / "2026-10-05.json").read_text(encoding="utf-8"))
    stats["date"] = "2026-10-12"
    text = generate_insight.fallback_report(stats)
    section5 = text.split("## 5.")[1]
    assert R_P7 in section5 and notes.DENOMINATOR_NOTE in section5


def test_the_app_shows_the_notes():
    r3 = (ROOT / "app" / "faces" / "r3_negative.py").read_text(encoding="utf-8")
    assert "observation_notes.R_P7_NOTE" in r3 and "r_p7_note_active()" in r3
    r2 = (ROOT / "app" / "faces" / "r2_trend.py").read_text(encoding="utf-8")
    assert "observation_notes.DENOMINATOR_CHANGE_DATE" in r2 and "add_vline" in r2
    assert "observation_notes.DENOMINATOR_NOTE" in r2


def test_looker_gets_a_measurement_change_event_on_20261006():
    rows = looker_tabs.event_rows("2026-10-06", [])
    assert [r["event_type"] for r in rows] == ["measurement_change"]
    assert notes.DENOMINATOR_SHORT in rows[0]["detail"] and R_P7 in rows[0]["detail"]
    assert looker_tabs.event_rows("2026-10-07", []) == []


def test_the_readme_records_both_notes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert R_P7 in readme and notes.DENOMINATOR_NOTE in readme
