"""lk_* バックフィルのテスト(Phase 6 §4-2/§4-3).

過去分を作るのは日次と同じ関数で、違うのは日付を回す点だけ。
「全期間入ること」と「二度実行しても増えないこと」を固定する。
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_looker  # noqa: E402
import looker_tabs  # noqa: E402
import sheets_writer  # noqa: E402
from settings import SELF_ENTITY  # noqa: E402

END = "2026-08-24"
DAYS = 12


def observations():
    rows = []
    end = dt.date.fromisoformat(END)
    for offset in range(DAYS):
        date = (end - dt.timedelta(days=offset)).isoformat()
        for model in ("claude", "gemini"):
            rows.append({
                "date": date, "prompt_id": "A-1", "pillar": "A", "model": model,
                "mention": "TRUE", "rank": "2", "negative_or_outdated": "FALSE",
                "negative_detail": "", "competitors_mentioned": "メンバーズ, ウフル",
                "cited_crosscom_urls": "", "kbf_tags": "", "mention_type": "",
                "raw_file": "",
            })
            rows.append({
                "date": date, "prompt_id": "E-1", "pillar": "entity", "model": model,
                "mention": "TRUE", "rank": "", "negative_or_outdated":
                    "TRUE" if offset < 4 else "FALSE",
                "negative_detail": "旧MA事業を現在の主要事業として記述している",
                "competitors_mentioned": "", "cited_crosscom_urls": "",
                "kbf_tags": "", "mention_type": "", "raw_file": "",
            })
    return rows


@pytest.fixture
def rows():
    return observations()


def test_every_observed_day_is_covered(rows):
    payload = backfill_looker.build(rows)
    for tab in ("lk_sov_trend", "lk_negative", "lk_verdicts"):
        assert {r["date"] for r in payload[tab]} == set(
            backfill_looker.observation_dates(rows)), tab
        assert len({r["date"] for r in payload[tab]}) == DAYS, tab


def test_the_trend_keeps_one_stable_set_of_series(rows):
    """系列を日ごとに選び直すと線が入れ替わり、推移として読めなくなる。"""
    payload = backfill_looker.build(rows, tabs=("lk_sov_trend",))
    by_date = {}
    for row in payload["lk_sov_trend"]:
        by_date.setdefault(row["date"], set()).add(row["entity"])
    assert len({frozenset(v) for v in by_date.values()}) == 1
    assert SELF_ENTITY in next(iter(by_date.values()))


def test_negative_history_marks_the_days_that_fired(rows):
    payload = backfill_looker.build(rows, tabs=("lk_negative",))
    fired = sorted({r["date"] for r in payload["lk_negative"] if r["detected"] == 1})
    end = dt.date.fromisoformat(END)
    assert fired == sorted((end - dt.timedelta(days=o)).isoformat() for o in range(4))


def test_running_twice_produces_the_same_rows(rows):
    assert backfill_looker.build(rows) == backfill_looker.build(rows)


def test_rows_match_the_tab_schema(rows):
    payload = backfill_looker.build(rows)
    for tab, built in payload.items():
        headers, keys = sheets_writer.LOOKER_TABS[tab]
        assert built, tab
        for row in built:
            assert list(row.keys()) == headers, tab
        seen = [tuple(str(r[k]) for k in keys) for r in built]
        assert len(seen) == len(set(seen)), tab


def test_the_range_can_be_narrowed(rows):
    payload = backfill_looker.build(rows, since="2026-08-20", until="2026-08-22",
                                    tabs=("lk_negative",))
    assert sorted({r["date"] for r in payload["lk_negative"]}) == [
        "2026-08-20", "2026-08-21", "2026-08-22"]


def test_only_the_backfillable_tabs_are_offered():
    """日次だけで足りるタブ(lk_answers 等)は過去分を作らない。"""
    assert set(backfill_looker.BACKFILLABLE) <= set(sheets_writer.LOOKER_TABS)
    assert "lk_answers" not in backfill_looker.BACKFILLABLE
    assert "lk_heatgrid" not in backfill_looker.BACKFILLABLE


def test_an_empty_history_builds_nothing():
    assert backfill_looker.build([]) == {t: [] for t in backfill_looker.BACKFILLABLE}


def test_verdicts_cover_all_eight_faces_per_day(rows):
    payload = backfill_looker.build(rows, tabs=("lk_verdicts",))
    per_day = {}
    for row in payload["lk_verdicts"]:
        per_day.setdefault(row["date"], []).append(row["face"])
    assert all(faces == list(looker_tabs.FACE_NAMES) for faces in per_day.values())


# --- 過去日の判定 ------------------------------------------------------------
# 施策は現在の action_log にしか残っていない。過去日の判定を作るとき、その日
# にはまだ提案も実施もされていない施策を「直近の施策」に選ぶと、経過日数が
# 負になるなど意味の通らない文が並ぶ。
LATE_ACTION = [{
    "action_id": "A-009", "優先度": "高", "内容": "外部プロフィール更新", "対象": "E-1",
    "根拠rule_id": "R-P7", "状態": "実施済み・効果測定中",
    "提案日": "2026-08-22", "実施日": "2026-08-23", "判断期限": "2026-09-07",
}]


def test_past_verdicts_never_show_a_negative_or_missing_day_count(rows):
    payload = backfill_looker.build(rows, action_rows=LATE_ACTION,
                                    tabs=("lk_verdicts",))
    for row in payload["lk_verdicts"]:
        text = row["verdict_text"]
        assert text, row            # 該当分岐なしで空欄にならないこと
        assert "None" not in text, row
        assert "-1日" not in text and "-2日" not in text, row


def test_a_later_action_is_invisible_on_earlier_days(rows):
    payload = backfill_looker.build(rows, action_rows=LATE_ACTION,
                                    tabs=("lk_verdicts",))
    by_day = {}
    for row in payload["lk_verdicts"]:
        if row["face"] == "R3":
            by_day[row["date"]] = row["verdict_text"]
    # 実施日 8/23 より前の判定には出てこない
    assert "外部プロフィール更新" not in by_day["2026-08-22"]
    assert "実施記録がない" in by_day["2026-08-22"]
    # 実施後は出てくる
    assert "外部プロフィール更新" in by_day["2026-08-24"]


def test_actions_as_of_does_not_mutate_the_input():
    before = [dict(r) for r in LATE_ACTION]
    looker_tabs.actions_as_of(LATE_ACTION, "2026-08-20")
    assert LATE_ACTION == before


def test_actions_as_of_hides_the_execution_date_until_it_happens():
    early = looker_tabs.actions_as_of(LATE_ACTION, "2026-08-22")
    assert early[0]["実施日"] == ""          # 提案済みだが未実施
    assert looker_tabs.actions_as_of(LATE_ACTION, "2026-08-21") == []  # 未提案
    assert looker_tabs.actions_as_of(LATE_ACTION, "2026-08-24")[0]["実施日"] == "2026-08-23"
