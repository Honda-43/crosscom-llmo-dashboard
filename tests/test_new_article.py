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


def test_answerable_is_read_from_the_note():
    assert summarize.new_article_answerable({"note": "実験用プロンプトに答えうる：E16・E24。ほか"}) == ("yes", ["E16", "E24"])
    assert summarize.new_article_answerable({"note": "実験用プロンプトに答えうる：なし"}) == ("no", [])
    assert summarize.new_article_answerable({"note": "実験用プロンプトに答えうる：要確認（弱）"}) == ("unknown", [])
    assert summarize.new_article_answerable({"note": ""}) == ("unknown", []), "書いていなければ要確認として数える"


def test_new_article_rows_are_listed_as_confounders(capsys):
    rows = [_row("I-90", "2026-10-10", note="実験用プロンプトに答えうる：なし")]
    overlap = summarize.print_site_wide_interventions("2026-09-15:2026-09-28", "2026-10-06:2026-11-01", rows)
    out = capsys.readouterr().out
    assert overlap == rows
    assert "- new_article" in out and "I-90｜新記事公開：x-I-90｜scope=new_article｜touches_pool46=no" in out


def _three():
    return [_row("I-90", "2026-10-10", note="実験用プロンプトに答えうる：E16"),
            _row("I-91", "2026-10-11", note="実験用プロンプトに答えうる：なし"),
            _row("I-92", "2026-10-12", note="実験用プロンプトに答えうる：要確認"),
            _row("I-93", "2026-10-12", scope="site_content", note="実験用プロンプトに答えうる：E05")]


def test_poaching_before_11_02_shows_counts_and_ids_but_no_groups(capsys):
    summarize.print_new_article_poaching(_three(), blind=True, groups={})
    out = capsys.readouterr().out
    assert f"### {summarize.POACHING_HEADING}" in out
    assert "新記事 3本のうち、46本の実験用プロンプトに答えうる 1本（E16）・答えうるか要確認 1本（I-92）" in out
    assert "組ごとの本数は 2026-11-02 の短期判定まで出さない" in out
    assert not any(g in out for g in summarize.GROUP_ORDER)


def test_poaching_from_11_02_shows_groups(capsys):
    pool = {a["id"]: a["slug"] for a in summarize.load_pool()}
    groups = {pool["E16"]: "③リードのみ"}            # 作り物の割付
    summarize.print_new_article_poaching(_three(), blind=False, groups=groups)
    out = capsys.readouterr().out
    assert "答えうる E番号の組：①対照 0本・②FAQのみ 0本・③リードのみ 1本・④両方 0本" in out


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
    assert summarize.new_article_answerable(r) == ("unknown", []), "E番号の記録が届くまで要確認"
    assert "I-06" in rows, "D-39 等の適用の行は残っている(追記のみ)"


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
