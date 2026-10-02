"""凍結を解いたピラー2本の編集を判定に反映する(pillar.py)のテスト(2026-10-02).

固定したいのは5つ:
1. 完了が 10/5 までならアフターは分けない。10/6 以降ならアフターを編集前・編集後に分ける(完了日は入れない)
2. 偏り1(薄まり):既存リンクを受けている46本の記事数を組ごとに出し、組間の差が2本以上なら「偏りあり」
3. 偏り2(横取り):強の重なりの孤児が実際に張られていれば本数と組を出す。張られていなければ「対象外」
4. 感度分析の6通り目:ピラーの既存リンク先(27本)を全組から抜く
5. 判定レポートの冒頭に出て、分けたときは summarize が前・後の結果も並べる
"""
import csv
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import pillar  # noqa: E402
import summarize  # noqa: E402
from pool import load_allocation  # noqa: E402

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


def _added(tmp_path, rows):
    path = tmp_path / "pillar_links_added_x.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "wp_modified", "pillar", "post_id", "target_slug", "anchor"])
        w.writerows(rows)
    return str(path)


def test_the_completion_is_read_per_pillar_from_seo_agent_records(tmp_path):
    path = _added(tmp_path, [
        ["2026-10-02", "2026-10-02T13:09:58", "agentforce-guide", "6698", "quote-ai", "a"],
        ["2026-10-08", "2026-10-08T09:00:00", "agentic-crm", "6797", "agentic-crm-role-design", "b"]])
    got = pillar.pillar_edit(path)
    assert got["done"] == dt.date(2026, 10, 8) and got["count"] == 2
    assert got["by_pillar"] == {"agentforce-guide": dt.date(2026, 10, 2), "agentic-crm": dt.date(2026, 10, 8)}
    assert got["targets"] == ["quote-ai", "agentic-crm-role-design"]


# --- 2. 偏り1(薄まり) ----------------------------------------------------------------
def test_the_existing_links_copy_matches_the_allocation_and_the_report():
    groups = load_allocation()
    rows = pillar.existing_links()
    assert len(rows) == 27 and all(groups[r["slug"]] == r["group"] for r in rows)
    bal = {label: (counts, gap, biased) for label, counts, gap, biased in pillar.balance()}
    a = bal["ピラーA（agentforce-guide）"]
    assert list(a[0].values()) == [6, 7, 4, 4] and a[1] == 3 and a[2]
    assert list(bal["ピラーB（agentic-crm）"][0].values()) == [2, 0, 1, 3]
    assert list(bal["A・Bのどちらか"][0].values()) == [8, 7, 5, 7]


def test_a_gap_below_two_is_not_flagged(tmp_path):
    path = tmp_path / "pillar_existing_links_x.csv"
    path.write_text("pillar,slug,group,links\nagentforce-guide,a,①対照,1\nagentforce-guide,b,②FAQのみ,1\n"
                    "agentforce-guide,c,③リードのみ,1\n", encoding="utf-8")
    label, counts, gap, biased = pillar.balance(str(path))[0]
    assert counts == {"①対照": 1, "②FAQのみ": 1, "③リードのみ": 1, "④両方": 0} and gap == 1 and not biased


# --- 3. 偏り2(横取り) ----------------------------------------------------------------
def test_the_strong_overlap_copy_is_13_orphans_leaning_to_group_3():
    rows = pillar._rows(pillar.find("pillar_strong_overlap_*.csv"))
    groups = load_allocation()
    assert len({r["orphan"] for r in rows}) == 13
    assert all(groups[r["prompt_slug"]] == r["group"] for r in rows)
    assert sum(r["group"] == "③リードのみ" for r in rows) == 7


def test_strong_orphans_that_were_linked_are_reported(tmp_path):
    edit = pillar.pillar_edit(_added(tmp_path, [
        ["2026-10-02", "", "agentforce-guide", "6698", "slackbot", "x"],
        ["2026-10-02", "", "agentforce-guide", "6698", "quote-ai", "y"]]))
    got = pillar.poaching(edit)
    assert got["linked"] == [("slackbot", "agentforce-in-slack", "③リードのみ")]
    assert got["by_group"]["③リードのみ"] == 1 and got["total"] == 13


def test_when_no_strong_orphan_is_linked_poaching_is_out_of_scope(monkeypatch, tmp_path):
    added = _added(tmp_path, [["2026-10-02", "2026-10-02T13:00:00", "agentforce-guide", "6698", "quote-ai", "y"]])
    real = pillar.find
    monkeypatch.setattr(pillar, "find",
                        lambda name: added if name.startswith("pillar_links_added") else real(name))
    lines, _ = pillar.report_lines(AFTER)
    assert any("強の重なり13本は今回張らないため、対象外" in l for l in lines)


# --- 4. 感度分析の6通り目 -------------------------------------------------------------
def test_the_sixth_variant_drops_every_article_a_pillar_already_links_to():
    label, exclude = summarize.variants()[5]
    assert label == "ピラーの既存リンク先抜き（27本・全組）"
    assert exclude == pillar.linked_articles() and len(exclude) == 27


# --- 5. 判定レポート -----------------------------------------------------------------
def test_without_the_files_the_report_says_so(monkeypatch):
    monkeypatch.setattr(pillar, "find", lambda name: None)
    lines, parts = pillar.report_lines(AFTER)
    assert parts == []
    assert any("pillar_links_added_*.csv）はまだ無い" in l for l in lines)
    assert any("pillar_existing_links_*.csv）はまだ無い" in l for l in lines)
    assert any("pillar_strong_overlap_*.csv）はまだ無い" in l for l in lines)


def test_the_judgement_report_shows_both_biases_and_splits_a_late_edit(monkeypatch, tmp_path, capsys):
    added = _added(tmp_path, [["2026-10-09", "2026-10-09T10:00:00", "agentic-crm", "6797", "agentic-crm-role-design", "x"]])
    real = pillar.find
    monkeypatch.setattr(pillar, "find",
                        lambda name: added if name.startswith("pillar_links_added") else real(name))
    rag = "https://cross-com.jp/agentforce-rag/"
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "④両方"})
    path = tmp_path / "e.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag"])
        w.writerows([["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
                     ["2026-10-07", "E06", "gemini", rag, "0", "", "pool"],
                     ["2026-10-20", "E06", "gemini", rag, "1", "", "pool"]])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    head = out.split("#####")[0]
    assert "偏り1（薄まり）" in head and "| ピラーA（agentforce-guide） | 6 | 7 | 4 | 4 | 3 | 偏りあり |" in head
    assert "リードの効果が大きめに見える方向" in head
    assert "偏り2（横取り）" in head and "10/6 以降に完了" in head
    assert "アフター 2026-10-06〜2026-10-08・ピラー編集前" in out
    assert "アフター 2026-10-10〜2026-11-01・ピラー編集後" in out


def test_the_real_record_shows_the_strong_orphans_linked_on_1002():
    """2026-10-02 13:09 のピラーA の差し込み20本には、強の重なりの孤児が10本含まれている(決定では除外のはず)。"""
    edit = pillar.pillar_edit()
    assert edit["by_pillar"].get("agentforce-guide") == dt.date(2026, 10, 2)
    got = pillar.poaching(edit)
    assert len(got["linked"]) == 10
    assert got["by_group"] == {"①対照": 2, "②FAQのみ": 3, "③リードのみ": 5, "④両方": 0}
