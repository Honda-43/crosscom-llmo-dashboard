"""11/2 以降の観測を含む組ごとの数字を、長期判定(12/28 の週)まで出さない仕組み(2026-11-04 決定)。

早期解放の機会は短期判定の1回だけと事前に決めているため、途中の数字を見ても取れる行動がなく、判断がぶれる危険だけが残る。
- 本物のデータで、アフター期間の終わりが 2026-11-02 以降を含み、実行した時刻(JST)が 2026-12-28 00:00 より前なら止める
- アフター期間の終わりが 2026-11-01 以前(短期判定の再実行)は今までどおり出す
- 日付は実行した時刻で決める(11/2 前の仕組みと同じ)。作り物のデータはいつでも出す
ここのテストは作り物のデータだけを使う。「本物」の扱いは、場所の判定を差し替えて確かめる。
"""
import csv
import datetime as dt
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import summarize  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
NOV4 = dt.datetime(2026, 11, 4, 12, 0, tzinfo=JST)
LAST = dt.datetime(2026, 12, 27, 23, 59, 59, tzinfo=JST)
AT = dt.datetime(2026, 12, 28, 0, 0, 0, tzinfo=JST)
LONG = ["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-15", "--model", "gemini"]
SHORT = ["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01", "--model", "gemini"]


def _csv(tmp_path):
    groups = summarize.load_allocation()
    slugs = sorted(groups)
    path = tmp_path / "e.csv"
    rows = [["date", "experiment_id", "model", "target_url", "cited_article", "mentioned_v2", "error",
             "experiment_flag", "timestamp"]]
    for i, s in enumerate(slugs):
        url = f"https://cross-com.jp/{s}/"
        rows.append(["2026-09-20", "", "gemini", url, str(i % 2), "0", "", "pool", "2026-09-20T01:00:00Z"])
        if i != 0:
            rows.append(["2026-11-10", "", "gemini", url, str((i // 2) % 2), "0", "", "pool", "2026-11-10T01:00:00Z"])
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path, slugs


def _no_group_math(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("長期判定より前に、11/2 以降を含む組ごとの数字を計算した")
    for name in ("both_ways", "sensitivity_table", "randomization", "effect", "tally", "early_release",
                 "print_early_release", "fact_reference", "print_fact_reference", "gsc_rank_subgroups", "fact_cut",
                 "print_sub_metric", "print_weekly", "weekly_cells", "summarize", "did_of"):
        monkeypatch.setattr(summarize, name, boom)


def _real(monkeypatch, now):
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    monkeypatch.setattr(summarize, "_now_jst", lambda: now)


@pytest.mark.parametrize("now", [NOV4, LAST])
def test_real_data_with_new_weeks_shows_only_headings_and_totals(monkeypatch, tmp_path, capsys, now):
    path, slugs = _csv(tmp_path)
    _real(monkeypatch, now)
    _no_group_math(monkeypatch)
    assert summarize.main(LONG + ["--csv", str(path)]) == 0
    out = capsys.readouterr().out
    assert summarize.LONG_BLIND_MESSAGE in out and summarize.BLIND_MESSAGE not in out
    assert "長期判定（12/28 の週・2026-12-28 00:00 JST）まで出さない" in out
    assert "## 判定期間（ビフォー〜アフター）中のサイト施策一覧（判定の交絡候補）" in out
    assert "### 観測の欠測" in out
    assert f"46本全体（組をまとめた数）：アフターに観測のある記事 {len(slugs) - 1}本／46本" in out
    for word in ("両方込み", "## 早期解放", "=== gemini", "p=", "差の差（組ごとの差", summarize.WEEKLY_HEADING,
                 summarize.SUB_METRIC_HEADING, "| E22 |"):
        assert word not in out, word


def test_real_data_from_12_28_shows_everything(monkeypatch, tmp_path, capsys):
    path, _ = _csv(tmp_path)
    _real(monkeypatch, AT)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    summarize.main(LONG + ["--csv", str(path)])
    out = capsys.readouterr().out
    assert summarize.LONG_BLIND_MESSAGE not in out and "両方込み" in out and summarize.WEEKLY_HEADING in out


def test_rerunning_the_short_term_judgement_still_shows(monkeypatch, tmp_path, capsys):
    path, _ = _csv(tmp_path)
    _real(monkeypatch, NOV4)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    summarize.main(SHORT + ["--csv", str(path)])
    out = capsys.readouterr().out
    assert summarize.LONG_BLIND_MESSAGE not in out and "両方込み" in out


def test_synthetic_data_always_shows(monkeypatch, tmp_path, capsys):
    path, _ = _csv(tmp_path)
    monkeypatch.setattr(summarize, "_now_jst", lambda: NOV4)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    summarize.main(LONG + ["--csv", str(path)])
    out = capsys.readouterr().out
    assert summarize.LONG_BLIND_MESSAGE not in out and "両方込み" in out


@pytest.mark.parametrize("end,now,held", [
    ("2026-11-01", NOV4, False), ("2026-11-02", NOV4, True), ("2026-12-27", LAST, True),
    ("2026-12-27", AT, False), ("2026-11-02", AT, False)])
def test_the_rule(end, now, held):
    assert summarize.holds_until_long_term(("2026-10-06", end), [None], now=now) is held
    assert summarize.holds_until_long_term(("2026-10-06", end), [str(ROOT / "output" / "x.csv")], now=now) is held


def test_the_date_cannot_be_moved_by_arguments_or_environment(monkeypatch, tmp_path, capsys):
    for flag in ("--today", "--now", "--date"):
        with pytest.raises(SystemExit):
            summarize.main(LONG + [flag, "2026-12-28"])
    capsys.readouterr()
    for name in ("TZ", "SOURCE_DATE_EPOCH", "FAKETIME"):
        monkeypatch.setenv(name, "2026-12-28")
    path, _ = _csv(tmp_path)
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    monkeypatch.setattr(summarize, "_now_jst", lambda: NOV4)
    _no_group_math(monkeypatch)
    summarize.main(LONG + ["--csv", str(path)])
    assert summarize.LONG_BLIND_MESSAGE in capsys.readouterr().out
