"""意図的な反復測定ペア(2026-10-10)の食い違いの数え方。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import repeat_pairs  # noqa: E402


def _put(raw, sub, day, pid, model, answer, error=None):
    d = raw / sub / day if sub else raw / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}_{model}.json").write_text(json.dumps(
        {"prompt_id": pid, "model": model, "answer": answer, "error": error}, ensure_ascii=False), encoding="utf-8")


def test_the_four_groups_are_the_agreed_pairs():
    pairs = dict(repeat_pairs.REPEAT_PAIRS)
    assert set(pairs) == {"G1", "G2", "G3", "G4"}
    assert set(pairs["G1"]) == {("A-1", "M-10"), ("M-10", "PM-L0-01"), ("A-1", "PM-L0-01")}
    assert pairs["G2"] == (("M-12", "PM-L2-05"),)
    assert pairs["G3"] == (("M-3", "PM-BS-02"),)
    assert pairs["G4"] == (("M-4", "PM-BS-10"),)


def test_the_pairs_still_exist_in_the_prompt_files():
    text = "".join((ROOT / "config" / f).read_text(encoding="utf-8")
                   for f in ("prompts.yaml", "prompts_monthly.yaml", "prompts_marketing.csv"))
    for _, pairs in repeat_pairs.REPEAT_PAIRS:
        for a, b in pairs:
            assert a in text and b in text


def test_a_disagreement_is_counted_per_model(tmp_path):
    _put(tmp_path, "monthly", "2026-10-01", "M-12", "claude", "クロスコムがおすすめです")
    _put(tmp_path, "marketing", "2026-10-02", "PM-L2-05", "claude", "A社とB社です")
    _put(tmp_path, "monthly", "2026-10-01", "M-12", "gemini", "CrossCom")
    _put(tmp_path, "marketing", "2026-10-02", "PM-L2-05", "gemini", "合同会社クロスコム")
    line = repeat_pairs.weekly_line("2026-10-12", tmp_path)
    assert "2回中1回" in line and "G2 1/2" in line


def test_errors_and_far_apart_dates_are_not_compared(tmp_path):
    _put(tmp_path, "monthly", "2026-09-20", "M-3", "gemini", "クロスコム")
    _put(tmp_path, "marketing", "2026-10-02", "PM-BS-02", "gemini", "なし")       # 12日離れている
    _put(tmp_path, "monthly", "2026-10-01", "M-4", "gemini", "クロスコム")
    _put(tmp_path, "marketing", "2026-10-02", "PM-BS-10", "gemini", "", error="503 UNAVAILABLE")
    line = repeat_pairs.weekly_line("2026-10-12", tmp_path)
    assert "比べられる回なし" in line


def test_the_daily_member_is_matched_to_the_nearest_day(tmp_path):
    _put(tmp_path, "", "2026-09-29", "A-1", "gemini", "なし")
    _put(tmp_path, "", "2026-10-01", "A-1", "gemini", "クロスコム")
    _put(tmp_path, "monthly", "2026-10-01", "M-10", "gemini", "クロスコム")
    line = repeat_pairs.weekly_line("2026-10-12", tmp_path)
    assert "1回中0回" in line and "G1 0/1" in line


def test_the_window_is_the_28_days_before_the_run():
    start, end = repeat_pairs.window("2026-10-12")
    assert (str(start), str(end)) == ("2026-09-14", "2026-10-11")
