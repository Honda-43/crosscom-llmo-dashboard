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
# 17列: slug, post_id, edited_at_jst, pool_class, edit_type, source, chars_delta,
# links_before, links_after, added_link_targets, removed_link_targets,
# title_changed, title_before, title_after, links_before_all, links_after_all, note
ROWS = [
    # 統計46・内部リンクが増えた(層に入る)
    ["agentforce-rag", "6604", "2026-09-11T17:46:35+09:00", "統計46", "リンク追記", "便GL",
     "120", "0", "1", "https://cross-com.jp/agentforce-data-library/", "", "0", "", "",
     "3", "4", "便GL"],
    # 同じ記事の2行目(遅い時刻)。最初の増加を採る
    ["agentforce-rag", "6604", "2026-09-14T10:00:00+09:00", "統計46", "リンク追記", "便GL",
     "80", "1", "2", "https://cross-com.jp/agentforce-roi/", "", "0", "", "", "4", "5", "便GL"],
    # 統計46・内部リンクは増えていない(層に入らない)。外部リンクは増えているが判定に使わない
    ["agentforce-roi", "6647", "2026-09-12T18:59:29+09:00", "統計46", "本文", "便GL", "-30",
     "2", "2", "", "", "0", "", "", "5", "9", "外部リンクのみ増"],
    # 統計46・9/16 に内部リンク増(層に入る。観測開始後なので条件 e にも入る)
    ["agentforce-subagents", "7124", "2026-09-16T15:54:47+09:00", "統計46", "リンク追記",
     "便GL", "100", "0", "1", "https://cross-com.jp/multi-agent/", "", "0", "", "",
     "2", "3", "便GL"],
    # プール外(ピラー)。リンクは増えたが層に入らない
    ["agentic-crm", "9000", "2026-09-11T18:00:00+09:00", "ピラー", "リンク追記", "便GL", "90",
     "0", "1", "https://cross-com.jp/agentforce-rag/", "", "0", "", "", "1", "2", "ピラー"],
    # タイトル変更 9/16 11:00(観測開始後 → 条件 e と「9/17 以降のみ」の対象)
    ["agentic-ai-guide", "6700", "2026-09-16T11:00:00+09:00", "統計46", "タイトル", "便GL",
     "5", "1", "1", "", "", "1", "旧タイトル", "新タイトル", "3", "3", "タイトルのみ"],
    # タイトル変更 9/12(観測開始前 → 対象外)
    ["agentic-crm-pipeline-stagnation-detection", "6701", "2026-09-12T09:00:00+09:00",
     "統計46", "タイトル", "便GL", "4", "0", "0", "", "", "1", "旧", "新", "2", "2", "タイトルのみ"],
    # 9/15 01:34(観測開始 08:00 より前 → 条件 e の対象外)
    ["agentforce-einstein-difference", "6702", "2026-09-15T01:34:00+09:00", "統計46",
     "本文", "便GL", "40", "3", "3", "", "", "0", "", "", "6", "6", "観測開始前"],
    ["agentforce-service-agent", "6703", "2026-09-15T01:34:00+09:00", "統計46", "本文",
     "便GL", "40", "3", "3", "", "", "0", "", "", "6", "6", "観測開始前"],
    # 9/15 09:00(観測開始後。リンクは増えていないが条件 e には入る)
    ["agentforce-mcp", "6704", "2026-09-15T09:00:00+09:00", "統計46", "本文", "便GL", "60",
     "2", "2", "", "", "0", "", "", "4", "4", "本文のみ"],
    # edit_type=その他 かつ 観測開始後(報告の対象)
    ["buyer-enablement", "6705", "2026-09-16T10:00:00+09:00", "統計46", "その他", "手動",
     "0", "1", "1", "", "", "0", "", "", "3", "3", "スキーマ追加"],
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
    monkeypatch.setattr(pool, "LATE_CHANGE_GLOB", str(tmp_path / "late_changes_*.csv"))
    return tmp_path


def _run(sandbox, rows, header=None, args=()):
    src = _write(sandbox / "edits.csv", rows, header)
    return make_strata.main(["--from-edits", str(src),
                             "--out", "strata_backlink_20260927.csv",
                             "--title-out", "title_changes_20260927.csv",
                             "--late-out", "late_changes_20260927.csv", *args])


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
    ("links_before_all", "x"), ("links_after_all", ""), ("note", ""),
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
    rows = list(ROWS) + [["not-in-pool", "1", "2026-09-11T10:00:00+09:00", "統計46",
                          "リンク追記", "便GL", "10", "0", "1", "", "", "0", "", "",
                          "1", "2", "46本に無い"]]
    assert _run(sandbox, rows) == 0
    assert "プール46本の外" in capsys.readouterr().out


# --- 4. タイトル変更 ---------------------------------------------------------------
def test_the_late_list_is_cut_at_the_observation_start(sandbox, capsys):
    """境目は観測開始 2026-09-15 08:00 JST。日付(JST・GMT)の境目では切らない。"""
    assert _run(sandbox, ROWS) == 0
    got = {r["slug"] for r in csv.DictReader(
        io.open(sandbox / "late_changes_20260927.csv", encoding="utf-8"))}
    # 9/15 01:34 の2本は観測開始より前 → 入らない
    assert "agentforce-einstein-difference" not in got
    assert "agentforce-service-agent" not in got
    # 9/15 09:00 の本文編集・9/16 のリンク追記とタイトル変更は入る
    assert got == {"agentforce-mcp", "agentforce-subagents", "agentic-ai-guide",
                   "buyer-enablement"}
    assert pool.late_appended_slugs() == got, "pool は時刻で切った表を読む"
    assert pool.baseline_start("agentforce-mcp") == "2026-09-17"
    assert pool.baseline_start("agentforce-einstein-difference") is None


def test_external_links_do_not_make_a_stratum_row(sandbox):
    """条件 b は内部リンク(links_before/after)で決める。links_*_all は使わない。"""
    assert _run(sandbox, ROWS) == 0
    got = {r["slug"] for r in csv.DictReader(
        io.open(sandbox / "strata_backlink_20260927.csv", encoding="utf-8"))}
    assert "agentforce-roi" not in got, "外部リンクだけ増えた記事を層に入れている"


def test_other_edit_types_after_the_observation_start_are_reported(sandbox, capsys):
    assert _run(sandbox, ROWS) == 0
    text = capsys.readouterr().out
    assert "edit_type=その他 かつ 統計46 かつ 観測開始以降: 1行" in text
    assert "buyer-enablement" in text and "スキーマ追加" in text


def test_title_changes_are_written_and_feed_the_late_list(sandbox, capsys):
    assert _run(sandbox, ROWS) == 0
    got = {r["slug"]: r["changed_at"]
           for r in csv.DictReader(io.open(sandbox / "title_changes_20260927.csv",
                                           encoding="utf-8"))}
    assert got == {"agentic-ai-guide": "2026-09-16 11:00:00",
                   "agentic-crm-pipeline-stagnation-detection": "2026-09-12 09:00:00"}
    assert pool.title_change_dates() == got, "pool は書き出した表を読む"
    late = pool.late_appended_slugs()
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
