"""凍結を解いたピラー2本の編集を判定に反映する(pillar.py)のテスト(2026-10-02).

固定したいのは3つ:
1. 完了が 10/5 までならアフターは分けない。10/6 以降ならアフターを編集前・編集後に分ける(完了日は入れない)
2. 釣り合いの表は組ごとの本数を転記し、組間の差が2本以上の列を「偏りあり」にする
3. 判定レポートの冒頭に出て、分けたときは summarize が前・後の結果も並べる
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import datetime as dt  # noqa: E402

import pillar  # noqa: E402
import summarize  # noqa: E402

AFTER = ("2026-10-06", "2026-11-01")


# --- 1. アフターの切り分け -----------------------------------------------------------
@pytest.mark.parametrize("done,mode", [
    (dt.date(2026, 10, 3), "before_after"), (dt.date(2026, 10, 5), "before_after"),
    (dt.date(2026, 11, 5), "after_end"), (None, "none"),
])
def test_edits_done_by_1005_or_after_the_period_are_not_split(done, mode):
    assert pillar.split_after(AFTER, done) == (mode, [])


def test_edits_done_after_1006_split_the_after_period_without_the_day_itself():
    mode, parts = pillar.split_after(AFTER, dt.date(2026, 10, 9))
    assert mode == "split"
    assert parts == [("ピラー編集前", ("2026-10-06", "2026-10-08")),
                     ("ピラー編集後", ("2026-10-10", "2026-11-01"))]
    assert pillar.split_after(AFTER, dt.date(2026, 10, 6))[1] == [
        ("ピラー編集後", ("2026-10-07", "2026-11-01"))]


def test_the_completion_is_the_last_time_a_link_was_added(tmp_path):
    path = tmp_path / "pillar_links_added_20261003.csv"
    path.write_text("applied_at,pillar,target\n2026-10-02 18:00,agentforce-guide,a\n"
                    "2026-10-08 09:12,agentic-crm,b\n2026-10-04T10:00:00,agentforce-guide,c\n",
                    encoding="utf-8")
    assert pillar.pillar_edit(str(path)) == {"done": dt.date(2026, 10, 8), "count": 3, "path": str(path)}


# --- 2. 釣り合い ---------------------------------------------------------------------
def test_a_gap_of_two_or_more_between_groups_is_flagged(tmp_path):
    path = tmp_path / "pillar_release_balance_20261003.csv"
    path.write_text("group,existing_links,orphan_topic_overlap,note\n"
                    "①対照,6,1,a\n②FAQのみ,7,2,b\n③リードのみ,4,1,c\n④両方,4,2,d\n", encoding="utf-8")
    got = pillar.balance(str(path))
    assert got["groups"] == ["①対照", "②FAQのみ", "③リードのみ", "④両方"]
    assert [(m[0], m[2], m[3]) for m in got["metrics"]] == [
        ("existing_links", 3.0, True), ("orphan_topic_overlap", 1.0, False)]


# --- 3. 判定レポート -----------------------------------------------------------------
def test_without_the_files_the_report_says_so(monkeypatch):
    monkeypatch.setattr(pillar, "find", lambda name: None)
    lines, parts = pillar.report_lines(AFTER)
    assert parts == [] and any("pillar_links_added_*.csv）はまだ無い" in l for l in lines)
    assert any("pillar_release_balance_*.csv）はまだ無い" in l for l in lines)


def _files(tmp_path, done):
    added = tmp_path / "pillar_links_added_x.csv"
    added.write_text(f"applied_at,pillar,target\n{done} 10:00,agentforce-guide,a\n", encoding="utf-8")
    bal = tmp_path / "pillar_release_balance_x.csv"
    bal.write_text("group,existing_links\n①対照,9\n②FAQのみ,7\n③リードのみ,4\n④両方,4\n", encoding="utf-8")
    return {"pillar_links_added_*.csv": str(added), "pillar_release_balance_*.csv": str(bal)}


def test_the_judgement_report_lists_the_balance_and_splits_the_after_period(monkeypatch, tmp_path, capsys):
    files = _files(tmp_path, "2026-10-09")
    monkeypatch.setattr(pillar, "find", lambda name: files[name])
    rag = "https://cross-com.jp/agentforce-rag/"
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "①対照"})
    import csv
    path = tmp_path / "e.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag"])
        for row in (["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
                    ["2026-10-07", "E06", "gemini", rag, "0", "", "pool"],
                    ["2026-10-20", "E06", "gemini", rag, "1", "", "pool"]):
            w.writerow(row)
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    head = out.split("#####")[0]
    assert "ピラー編集の完了：2026-10-09" in head and "10/6 以降に完了" in head
    assert "| existing_links | 9 | 7 | 4 | 4 | 5 | 偏りあり |" in head
    assert "アフター 2026-10-06〜2026-10-08・ピラー編集前" in out
    assert "アフター 2026-10-10〜2026-11-01・ピラー編集後" in out


def test_an_edit_before_the_after_period_only_adds_a_note(monkeypatch, tmp_path):
    files = _files(tmp_path, "2026-10-03")
    monkeypatch.setattr(pillar, "find", lambda name: files[name])
    lines, parts = pillar.report_lines(AFTER)
    assert parts == [] and any("追加の切り分けはしない" in l for l in lines)
