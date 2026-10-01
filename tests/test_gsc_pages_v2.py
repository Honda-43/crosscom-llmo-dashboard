"""GSC の # 付きURLの寄せ方(2026-10-01).

- # を含むURLは # より前で本体に寄せる
- 表示回数・平均掲載順位は本体の行のみ。クリック数は本体とアンカーの合計
- 本体の行が無い記事は、表示回数・順位を「データなし」とし備考に書く
- 判定時の補助分析(summarize)は v2 を読む
"""
import csv
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
import gsc_pages_v2 as v2  # noqa: E402
import summarize  # noqa: E402

HEAD = ["上位のページ", "クリック数", "表示回数", "CTR", "掲載順位"]
POOL = [{"id": "E01", "layer": "古", "url": "https://cross-com.jp/a/"},
        {"id": "E02", "layer": "中", "url": "https://cross-com.jp/b/"},
        {"id": "E03", "layer": "新", "url": "https://cross-com.jp/c/"}]


def _rows(*rows):
    return [dict(zip(HEAD, r)) for r in rows]


def test_anchor_rows_add_clicks_but_not_impressions_or_position():
    export = _rows(["https://cross-com.jp/a/", "3", "100", "3%", "6.00"],
                   ["https://cross-com.jp/a/#arkb-toc-1", "2", "40", "5%", "2.00"],
                   ["https://cross-com.jp/a/#arkb-toc-2", "1", "30", "3%", "3.00"])
    row = v2.build(export, POOL[:1])[0]
    assert row["表示回数"] == "100", "アンカーの表示回数は足さない(同じ検索結果での二重計上)"
    assert row["平均掲載順位"] == "6.00", "順位は本体の行のみ(加重平均しない)"
    assert row["クリック数"] == "6", "クリックは本体とアンカーの合計"
    assert "2行" in row["備考"]


def test_an_article_with_only_anchor_rows_has_no_impressions_or_position():
    export = _rows(["https://cross-com.jp/b/#arkb-toc-3", "1", "50", "2%", "4.00"])
    row = v2.build(export, POOL[1:2])[0]
    assert row["表示回数"] == "" and row["平均掲載順位"] == ""
    assert row["クリック数"] == "1"
    assert "本体の行なし" in row["備考"] and "データなし" in row["備考"]


def test_an_article_without_rows_and_unrelated_pages_are_handled():
    export = _rows(["https://cross-com.jp/download-paper/x/", "0", "133", "0%", "41.68"],
                   ["https://cross-com.jp/wp-content/uploads/2026/06/x.pdf", "4", "71", "5.6%", "6.54"])
    rows = v2.build(export, POOL)
    assert [r["id"] for r in rows] == ["E01", "E02", "E03"], "PDF・資料DLページは46本に入らない"
    assert all("GSC に行なし" in r["備考"] for r in rows)


def test_the_v2_file_has_the_46_articles_without_e37():
    with io.open(summarize.GSC_PAGES_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    with io.open(ROOT / "config" / "prompts_experiment.csv", encoding="utf-8") as f:
        pool = [r["id"] for r in csv.DictReader(f)]
    assert [r["id"] for r in rows] == pool and len(rows) == 46
    assert "E37" not in {r["id"] for r in rows}


def test_the_v2_file_matches_a_rebuild_from_the_source():
    with io.open(v2.SOURCE_CSV, encoding="utf-8-sig") as f:
        export = list(csv.DictReader(f))
    with io.open(v2.POOL_CSV, encoding="utf-8") as f:
        pool = list(csv.DictReader(f))
    with io.open(summarize.GSC_PAGES_CSV, encoding="utf-8-sig") as f:
        saved = list(csv.DictReader(f))
    assert v2.build(export, pool) == saved


def test_summarize_reads_v2():
    assert os.path.basename(summarize.GSC_PAGES_CSV) == "experiment46_gsc_pages_20260914_v2.csv"
    got = summarize.read_gsc_pages()
    assert got["E04"]["impressions"] == 97 and got["E04"]["position"] == 6.03


def test_an_existing_v2_is_not_overwritten(tmp_path):
    out = tmp_path / "v2.csv"
    out.write_text("既存", encoding="utf-8")
    assert v2.write([], str(out)) is False
    assert out.read_text(encoding="utf-8") == "既存"
