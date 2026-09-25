"""制作管制の全編集一覧(14列)の取り込みのテスト(2026-09-25).

固定したいのは4つ:
1. 列名・列数・並び・型が仕様と1つでも違えば、**何も書かずに止める**(推測で読まない)
2. 抽出は「pool_class=統計46 かつ links_after > links_before の行を1行以上持つ記事」
3. 17本との差分(増えた記事・消えた記事)を報告する
4. title_changed=1 の日付が 9/15 以降なら、条件 e と「9/17 以降のみ」の対象に入る
"""
import csv
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import make_strata  # noqa: E402
import pool  # noqa: E402

COLUMNS = make_strata.EDIT_COLUMNS
# slug, post_id, edited_at_jst, pool_class, edit_type, source, chars_delta,
# links_before, links_after, added_link_targets, removed_link_targets,
# title_changed, title_before, title_after
ROWS = [
    # 統計46・リンクが増えた(層に入る)
    ["agentforce-rag", "6604", "2026-09-11 17:46:35", "統計46", "link", "便GL", "120",
     "0", "1", "https://cross-com.jp/agentforce-data-library/", "", "0", "", ""],
    # 同じ記事の2行目(遅い時刻)。最初の増加を採る
    ["agentforce-rag", "6604", "2026-09-14 10:00:00", "統計46", "link", "便GL", "80",
     "1", "2", "https://cross-com.jp/agentforce-roi/", "", "0", "", ""],
    # 統計46・リンクは増えていない(層に入らない)
    ["agentforce-roi", "6647", "2026-09-12 18:59:29", "統計46", "body", "便GL", "-30",
     "2", "2", "", "", "0", "", ""],
    # 統計46・9/16 にリンク増(層に入る)
    ["agentforce-subagents", "7124", "2026-09-16 15:54:47", "統計46", "link", "便GL", "100",
     "0", "1", "https://cross-com.jp/multi-agent/", "", "0", "", ""],
    # プール外(ピラー)。リンクは増えたが層に入らない
    ["agentic-crm", "9000", "2026-09-11 18:00:00", "ピラー", "link", "便GL", "90",
     "0", "1", "https://cross-com.jp/agentforce-rag/", "", "0", "", ""],
    # タイトル変更 9/16(条件 e と「9/17 以降のみ」の対象)
    ["agentic-ai-guide", "6700", "2026-09-16 11:00:00", "統計46", "title", "便GL", "5",
     "1", "1", "", "", "1", "旧タイトル", "新タイトル"],
    # タイトル変更 9/12(対象外)
    ["agentic-crm-pipeline-stagnation-detection", "6701", "2026-09-12 09:00:00", "統計46",
     "title", "便GL", "4", "0", "0", "", "", "1", "旧", "新"],
]


def _write(path, rows, header=None):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header if header is not None else COLUMNS)
        w.writerows(rows)
    return path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """出力先とプールの参照を tmp に閉じ込める(リポジトリに書かない)。"""
    monkeypatch.setattr(make_strata, "HERE", str(tmp_path))
    monkeypatch.setattr(make_strata, "EDITS_COPY", str(tmp_path / "edits_20260911_0916.csv"))
    monkeypatch.setattr(pool, "STRATA_GLOB", str(tmp_path / "strata_backlink_*.csv"))
    monkeypatch.setattr(pool, "TITLE_CHANGE_GLOB", str(tmp_path / "title_changes_*.csv"))
    return tmp_path


def _run(sandbox, rows, header=None, args=()):
    src = _write(sandbox / "edits.csv", rows, header)
    return make_strata.main(["--from-edits", str(src),
                             "--out", "strata_backlink_20260927.csv",
                             "--title-out", "title_changes_20260927.csv", *args])


# --- 1. 検査 ---------------------------------------------------------------------
@pytest.mark.parametrize("header,why", [
    (COLUMNS[:-1], "列が足りない"),
    (COLUMNS + ["extra"], "列が余分"),
    (COLUMNS[1:] + COLUMNS[:1], "並びが違う"),
    ([c.upper() for c in COLUMNS], "名前が違う"),
])
def test_a_wrong_header_stops_the_ingest(sandbox, header, why, capsys):
    rows = [r + [""] * (len(header) - len(COLUMNS)) for r in ROWS]
    assert _run(sandbox, rows, header=header) == 2, why
    assert not list(sandbox.glob("strata_backlink_*.csv")), "止めたのに書いている"
    assert "仕様と合わない" in capsys.readouterr().err


@pytest.mark.parametrize("col,value", [
    ("post_id", "abc"), ("chars_delta", ""), ("links_before", "1.5"),
    ("links_after", "-"), ("edited_at_jst", "9月11日"), ("title_changed", "TRUE"),
])
def test_a_wrong_type_stops_the_ingest(sandbox, col, value, capsys):
    rows = [list(r) for r in ROWS]
    rows[0][COLUMNS.index(col)] = value
    assert _run(sandbox, rows) == 2
    assert not list(sandbox.glob("strata_backlink_*.csv"))
    assert col in capsys.readouterr().err


def test_an_empty_slug_stops_the_ingest(sandbox):
    rows = [list(r) for r in ROWS]
    rows[0][0] = ""
    assert _run(sandbox, rows) == 2


# --- 2・3. 抽出と差分 --------------------------------------------------------------
def test_only_pool46_rows_with_a_link_increase_become_the_stratum(sandbox, capsys):
    assert _run(sandbox, ROWS) == 0
    out = sandbox / "strata_backlink_20260927.csv"
    got = {r["slug"]: r for r in csv.DictReader(io.open(out, encoding="utf-8"))}
    assert set(got) == {"agentforce-rag", "agentforce-subagents"}
    # 同じ記事に複数行あるときは最初の増加を採る
    assert got["agentforce-rag"]["appended_at"] == "2026-09-11 17:46:35"
    assert got["agentforce-rag"]["backlinks"] == "1"
    text = capsys.readouterr().out
    assert "プール46本の外" not in text          # ピラーは pool_class が違うので出ない
    assert "増えた記事: " in text and "消えた記事: " in text


def test_the_diff_against_the_previous_stratum_is_reported(sandbox, capsys, monkeypatch):
    previous = sandbox / "strata_backlink_20260920.csv"
    _write(previous, [["agentforce-roi", "https://cross-com.jp/agentforce-roi/", "1",
                       "2026-09-12 00:00:00", "1", ""]],
           header=make_strata.STRATA_COLUMNS)
    assert _run(sandbox, ROWS) == 0
    text = capsys.readouterr().out
    assert "増えた記事: agentforce-rag、agentforce-subagents" in text
    assert "消えた記事: agentforce-roi" in text


def test_a_pool_class_row_outside_the_46_is_reported(sandbox, capsys):
    rows = list(ROWS) + [["not-in-pool", "1", "2026-09-11 10:00:00", "統計46", "link",
                          "便GL", "10", "0", "1", "", "", "0", "", ""]]
    assert _run(sandbox, rows) == 0
    assert "プール46本の外" in capsys.readouterr().out


# --- 4. タイトル変更 ---------------------------------------------------------------
def test_title_changes_are_written_and_feed_the_late_list(sandbox, capsys):
    assert _run(sandbox, ROWS) == 0
    got = {r["slug"]: r["changed_at"]
           for r in csv.DictReader(io.open(sandbox / "title_changes_20260927.csv",
                                           encoding="utf-8"))}
    assert got == {"agentic-ai-guide": "2026-09-16 11:00:00",
                   "agentic-crm-pipeline-stagnation-detection": "2026-09-12 09:00:00"}
    assert pool.title_change_dates() == got, "pool は書き出した表を読む"
    late = pool.late_appended_slugs(str(sandbox / "strata_backlink_20260927.csv"))
    assert "agentic-ai-guide" in late, "9/16 のタイトル変更は対象"
    assert "agentic-crm-pipeline-stagnation-detection" not in late, "9/12 は対象外"
    assert pool.baseline_start("agentic-ai-guide") == "2026-09-17"
    assert "9/15 以降" in capsys.readouterr().out


# --- コピー ------------------------------------------------------------------------
def test_copy_from_copies_only_a_valid_file(sandbox, capsys):
    src = _write(sandbox / "seo_agent_edits.csv", ROWS)
    assert make_strata.main(["--copy-from", str(src), "--out", "strata_backlink_20260927.csv",
                             "--title-out", "title_changes_20260927.csv"]) == 0
    copied = Path(make_strata.EDITS_COPY)
    assert copied.exists() and copied.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_copy_from_does_not_copy_a_file_that_fails_the_check(sandbox, capsys):
    bad = _write(sandbox / "bad.csv", ROWS, header=COLUMNS[:-1])
    assert make_strata.main(["--copy-from", str(bad)]) == 2
    assert not Path(make_strata.EDITS_COPY).exists(), "検査に落ちたファイルをコピーしている"


def test_a_missing_file_says_the_fallback(sandbox, capsys):
    assert make_strata.main(["--from-edits", str(sandbox / "none.csv")]) == 2
    assert "便GL の17本のまま" in capsys.readouterr().err
