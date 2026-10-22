"""新記事公開の記録・横取りのおそれの表示・指名検索の月次記録(2026-10-22・戦略管制塔の依頼)。

判定の出力を確かめるテストは作り物の行だけを使う(本物の観測は読まない)。
"""
import csv
import datetime as dt
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import interventions  # noqa: E402
import summarize  # noqa: E402


def _row(iid, date, scope="new_article", note="", desc=None):
    return {"intervention_id": iid, "date": dt.date.fromisoformat(date), "raw_date": date, "ongoing": False,
            "description": desc or f"新記事公開：x-{iid}", "scope": scope, "executor": "seo-agent（abcd1234）",
            "touches_pool46": "no", "note": note}


def test_overlap_is_read_from_the_note():
    f = summarize.new_article_overlap
    note = ("対象：x。実験用プロンプトに答えうる：要確認（古い）。　追記：・実験用プロンプトとの重なり：強0"
            "・弱：E16（「弱」と判定済み。ChatGPT・Copilot は扱わない）・弱（本文の判定で追加）：　E22（…）　E11・E12（…）"
            "・公開：2026-09-23（E99 は公開の行なので読まない）")
    assert f({"note": note}) == ("known", [], ["E16", "E22", "E11", "E12"]), "重なりの記載が旧い書き方より優先・出てくる順"
    assert f({"note": "実験用プロンプトとの重なり：強：E05・弱：E16・公開：…"}) == ("known", ["E05"], ["E16"])
    assert f({"note": "実験用プロンプトに答えうる：E16・E24。ほか"}) == ("known", ["E16", "E24"], []), "旧い書き方の E番号は強"
    assert f({"note": "実験用プロンプトに答えうる：なし"}) == ("known", [], [])
    assert f({"note": "実験用プロンプトに答えうる：要確認（弱）"}) == ("unknown", [], [])
    assert f({"note": ""}) == ("unknown", [], []), "書いていなければ要確認として数える"
    assert summarize.overlap_text([], ["E16", "E22"]) == "強0・弱（E16・E22）"
    assert summarize.overlap_text(["E05"], []) == "強（E05）・弱0"


def test_new_article_rows_are_listed_as_confounders(capsys):
    rows = [_row("I-90", "2026-10-10", note="実験用プロンプトに答えうる：なし")]
    overlap = summarize.print_site_wide_interventions("2026-09-15:2026-09-28", "2026-10-06:2026-11-01", rows)
    out = capsys.readouterr().out
    assert overlap == rows
    assert "- new_article" in out and "I-90｜新記事公開：x-I-90｜scope=new_article｜touches_pool46=no" in out


def _three():
    return [_row("I-90", "2026-10-10", note="実験用プロンプトとの重なり：強：E16・弱：E05"),
            _row("I-91", "2026-10-11", note="実験用プロンプトに答えうる：なし"),
            _row("I-92", "2026-10-12", note="実験用プロンプトに答えうる：要確認"),
            _row("I-93", "2026-10-12", scope="site_content", note="実験用プロンプトに答えうる：E05")]


def test_poaching_before_11_02_shows_counts_and_ids_but_no_groups(capsys):
    summarize.print_new_article_poaching(_three(), blind=True, groups={})
    out = capsys.readouterr().out
    assert f"### {summarize.POACHING_HEADING}" in out
    assert "新記事 3本。46本の実験用プロンプトとの重なり：強（E16）・弱（E05）・重なりが要確認 1本（I-92）" in out
    assert "- I-90 x-I-90：強（E16）・弱（E05）" in out and "- I-91 x-I-91：強0・弱0" in out and "- I-92 x-I-92：要確認" in out
    assert "組ごとの本数は 2026-11-02 の短期判定まで出さない" in out
    assert not any(g in out for g in summarize.GROUP_ORDER)


def test_poaching_from_11_02_shows_groups(capsys):
    pool = {a["id"]: a["slug"] for a in summarize.load_pool()}
    groups = {pool["E16"]: "③リードのみ", pool["E05"]: "①対照"}            # 作り物の割付
    summarize.print_new_article_poaching(_three(), blind=False, groups=groups)
    out = capsys.readouterr().out
    assert "強の E番号の組：①対照 0本・②FAQのみ 0本・③リードのみ 1本・④両方 0本" in out
    assert "弱の E番号の組：①対照 1本・②FAQのみ 0本・③リードのみ 0本・④両方 0本" in out


def test_no_new_article(capsys):
    summarize.print_new_article_poaching([_row("I-93", "2026-10-12", scope="site_content")], blind=True)
    assert "記録なし" in capsys.readouterr().out


def test_claudeforce_row_is_recorded():
    rows = {r["intervention_id"]: r for r in interventions.load()}
    r = rows["I-53"]
    assert (r["raw_date"], r["description"], r["scope"], r["touches_pool46"]) == (
        "2026-09-23", "新記事公開：claudeforce", "new_article", "no")
    assert r["executor"].startswith("seo-agent（")
    assert r["note"].startswith("対象：https://cross-com.jp/claudeforce/")
    assert summarize.new_article_overlap(r) == ("known", [], ["E16", "E22", "E14", "E46", "E11", "E12"])
    assert r["executor"] == "seo-agent（sessionId 要確認）", "executor の列は変えない(公開のセッションは note に追記)"
    assert "セッション 5efdb82d" in r["note"] and r["note"].count("実験用プロンプトに答えうる：要確認") == 1
    assert "I-06" in rows, "D-39 等の適用の行は残っている(追記のみ)"


def test_claudeforce_line_in_the_report(capsys):
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1))
    summarize.print_new_article_poaching(overlap, blind=True)
    out = capsys.readouterr().out
    assert "46本の実験用プロンプトとの重なり：強0・弱（E16・E22・E14・E46・E11・E12）" in out
    assert "- I-53 claudeforce：強0・弱（E16・E22・E14・E46・E11・E12）" in out
    assert "組ごとの本数は 2026-11-02 の短期判定まで出さない" in out
    assert not any(g in out for g in summarize.GROUP_ORDER)


def test_claudeforce_is_in_the_judgement_window_list():
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1))
    assert "I-53" in [r["intervention_id"] for r in summarize.new_article_rows(overlap)]


def test_brand_search_monthly_csv():
    path = ROOT / "output" / "brand_search_monthly.csv"
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    assert list(rows[0]) == ["start_date", "end_date", "days", "regex_clicks", "regex_impressions",
                             "company_clicks", "company_impressions", "company_position",
                             "brand_clicks", "brand_impressions", "brand_position", "note"]
    for r in rows:
        if r["start_date"]:
            span = (dt.date.fromisoformat(r["end_date"]) - dt.date.fromisoformat(r["start_date"])).days + 1
            assert span == int(r["days"]), r
    first, second = rows[0], rows[1]
    assert (first["end_date"], first["regex_clicks"], first["regex_impressions"], first["company_clicks"]) == (
        "2026-09-18", "25", "97", "")
    assert [second[k] for k in ("regex_clicks", "regex_impressions", "company_clicks", "company_impressions",
                                "company_position", "brand_clicks", "brand_impressions", "brand_position")] == [
        "19", "97", "11", "16", "1.0", "7", "38", "2.6"]


def test_the_baseline_period_is_corrected_without_deleting_the_first_row():
    """9/18 基準の期間は 2026-08-20〜09-16(2026-10-22 本田さんが GSC で確認)。最初の行は消さず訂正の行を足す。"""
    path = ROOT / "output" / "brand_search_monthly.csv"
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    assert rows[0]["start_date"] == "2026-08-22" and "【2026-10-22 訂正】" in rows[0]["note"]
    fixed = [r for r in rows if r["start_date"] == "2026-08-20"]
    assert len(fixed) == 1
    r = fixed[0]
    assert (r["end_date"], r["days"], r["regex_clicks"], r["regex_impressions"]) == ("2026-09-16", "28", "25", "97")
    assert "クリック25・表示96" in r["note"] and "クリック24・表示101" in r["note"]


def test_i54_records_the_marketing_gemini_exemption():
    r = {x["intervention_id"]: x for x in interventions.load()}["I-54"]
    assert (r["raw_date"], r["scope"], r["executor"], r["touches_pool46"]) == ("2026-10-22", "measurement", "本田さん決定", "no")
    assert r["description"].startswith("一時停止（10/17〜・ダッシュボード作り直し）から第3観測層の Gemini のみ除外")
