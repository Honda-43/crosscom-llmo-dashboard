"""凍結を解いたピラー2本の編集を判定に反映する(pillar.py)のテスト(2026-10-02).

固定したいのは5つ:
1. 完了が 10/5 までならアフターは分けない。10/6 以降ならアフターを編集前・編集後に分ける(完了日は入れない)
2. 偏り1(薄まり):既存リンクを受けている46本の記事数を組ごとに出し、組間の差が2本以上なら「偏りあり」
3. 偏り2(横取り):強の重なりの孤児が実際に張られていれば本数と組を出す。張られていなければ「対象外」
4. 感度分析の6通り目:ピラーの既存リンク先(27本)を全組から抜く
5. 判定レポートの冒頭に出て、分けたときは summarize が前・後の結果も並べる
"""
import os
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
    assert got["targets"] == ["agentic-crm-role-design", "quote-ai"]


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
    monkeypatch.setattr(pillar, "find_all", lambda name: [added])
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
    monkeypatch.setattr(pillar, "find_all", lambda name: [])
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
    monkeypatch.setattr(pillar, "find_all", lambda name: [added])
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


def test_add_and_remove_rows_give_the_final_state_and_the_last_operation(tmp_path):
    """2026-10-02 改訂の記録(action=add/remove)。最終状態と最後の操作の日時をピラー編集の完了とする。"""
    path = tmp_path / "pillar_links_added_y.csv"
    path.write_text("applied_at_jst,pillar_slug,target_slug,action,target_group,overlap_level\n"
                    "2026-10-02 13:09:58,agentforce-guide,slackbot,add,対象外,強\n"
                    "2026-10-02 13:09:58,agentforce-guide,quote-ai,add,対象外,なし\n"
                    "2026-10-08 13:22:57,agentforce-guide,slackbot,remove,対象外,強\n", encoding="utf-8")
    got = pillar.pillar_edit(str(path))
    assert got["targets"] == ["quote-ai"] and got["final"] == {"agentforce-guide": 1}
    assert got["last"] == dt.datetime(2026, 10, 8, 13, 22, 57) and got["done"] == dt.date(2026, 10, 8)
    assert pillar.poaching(got)["linked"] == [], "外した強の孤児は横取りに数えない"
    assert pillar.split_after(AFTER, got["done"])[0] == "split", "最後の操作が 10/6 以降なら分ける"


def test_the_real_record_ends_with_19_articles_and_no_strong_orphan():
    """2026-10-02：-14 が 13:09 に強10本を含む20本を追加 → 9d が 13:22 に強10本を外し、13:24 にピラーB へ9本、
    13:34 に sales-enablement を外した(A10・B8 の18本)。
    2026-10-03 15:08：seo-agent(便QG)がピラーB に46本の外の3本へのリンクを追加(pillar_links_added_20261003.csv)。
    うち cs-handback・role-design は 10/02 にリンク済みの記事(2本目のリンク)、migration-decision だけが新しい。
    最終状態は A10・B9 の19本・強は0本・完了は 10/5 以前。日ごとのファイルを全部合わせて読む。"""
    edit = pillar.pillar_edit()
    assert [os.path.basename(p) for p in edit["paths"]][:2] == ["pillar_links_added_20261002.csv",
                                                               "pillar_links_added_20261003.csv"]
    assert edit["final"] == {"agentforce-guide": 10, "agentic-crm": 9} and len(edit["targets"]) == 19
    assert "agentic-crm-migration-decision" in edit["targets"]
    assert edit["last"] == dt.datetime(2026, 10, 3, 15, 8, 33)
    assert (edit["added"], edit["removed"]) == (32, 11)
    assert pillar.poaching(edit)["linked"] == []
    assert pillar.split_after(AFTER, edit["done"]) == ("before_after", [])


def test_records_of_several_days_are_read_together(tmp_path, monkeypatch):
    """一番新しい日のファイルだけを読むと、前の日の追加・除去が抜ける(2026-10-03 に起きた)。"""
    head = "applied_at_jst,pillar_slug,target_slug,action\n"
    (tmp_path / "pillar_links_added_20261002.csv").write_text(
        head + "2026-10-02 13:00:00,agentforce-guide,a,add\n2026-10-02 13:10:00,agentforce-guide,b,add\n",
        encoding="utf-8")
    (tmp_path / "pillar_links_added_20261003.csv").write_text(
        head + "2026-10-03 15:00:00,agentforce-guide,a,remove\n2026-10-03 15:00:00,agentic-crm,c,add\n",
        encoding="utf-8")
    monkeypatch.setattr(pillar, "SEO_AGENT", str(tmp_path / "none"))
    monkeypatch.setattr(pillar, "HERE", str(tmp_path))
    edit = pillar.pillar_edit()
    assert edit["final"] == {"agentforce-guide": 1, "agentic-crm": 1} and edit["targets"] == ["b", "c"]
    assert (edit["added"], edit["removed"]) == (3, 1) and edit["done"] == dt.date(2026, 10, 3)


def test_the_judgement_report_shows_the_edit_finished_on_20261003_with_19():
    """2026-10-03：判定レポートのピラー編集の欄は「完了 2026-10-03 15:08・最終状態 A10・B9（19本）」(interventions I-26)。"""
    lines, parts = pillar.report_lines(AFTER)
    line = next(l for l in lines if l.startswith("- ピラー編集の完了"))
    assert "2026-10-03 15:08:33" in line
    assert "ピラーA（agentforce-guide） 10本・ピラーB（agentic-crm） 9本（計19本）" in line
    assert "pillar_links_added_20261002.csv・pillar_links_added_20261003.csv" in line
    assert parts == [], "10/5 以前に完了したのでアフターは分けない"

