"""11/2 より前に、本物のデータの組ごとの数字を出さない仕組み(2026-10-22・本田さん指示)。

「11/2 まで組ごとの結果を見ない」は、見た人が後の判断に引きずられないためのルール。人の注意に頼らず summarize.py で止める。
- 日付は実行した時刻(JST)で決める。引数・環境変数では前倒しできない
- 作り物のデータかどうかは、読み込むファイルの場所で決める(pytest の一時フォルダか tests/ の下だけが作り物)
ここのテストは作り物のデータだけを使う。「本物」の扱いは、場所の判定を差し替えて確かめる(本物のデータは読まない)。
"""
import csv
import datetime as dt
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import summarize  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
BEFORE = dt.datetime(2026, 11, 1, 23, 59, 59, tzinfo=JST)
AT = dt.datetime(2026, 11, 2, 0, 0, 0, tzinfo=JST)
ARGS = ["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01", "--model", "gemini"]


def test_where_the_file_is_decides_synthetic(tmp_path):
    assert summarize.is_synthetic(tmp_path / "e.csv"), "pytest の一時フォルダは作り物"
    assert summarize.is_synthetic(ROOT / "tests" / "fixtures" / "e.csv"), "tests/ の下は作り物"
    assert not summarize.is_synthetic(None) and not summarize.is_synthetic(""), "シートは本物"
    assert not summarize.is_synthetic(ROOT / "output" / "llm_experiment.csv")
    assert not summarize.is_synthetic(ROOT / "experiment_2x2" / "results" / "2026-09-17.csv")
    assert not summarize.is_synthetic(os.path.join(tempfile.gettempdir(), "export.csv")), "一時フォルダでも pytest のでなければ本物"
    assert not summarize.is_synthetic(ROOT / "tests_backup" / "e.csv"), "名前が tests で始まるだけの場所は本物"


def test_the_environment_cannot_make_real_data_synthetic(monkeypatch):
    monkeypatch.setenv("TEMP", str(ROOT / "output"))
    monkeypatch.setenv("TMP", str(ROOT / "output"))
    monkeypatch.setenv("TMPDIR", str(ROOT / "output"))
    tempfile.tempdir = None
    try:
        assert not summarize.is_synthetic(ROOT / "output" / "llm_experiment.csv")
    finally:
        tempfile.tempdir = None


@pytest.mark.parametrize("now,blind", [(BEFORE, True), (AT, False), (dt.datetime(2026, 12, 28, tzinfo=JST), False)])
def test_real_data_is_blind_until_11_02_00_00_jst(now, blind):
    assert summarize.group_blind([None], now=now) is blind
    assert summarize.group_blind([str(ROOT / "output" / "x.csv")], now=now) is blind


def test_synthetic_data_is_never_blind(tmp_path):
    assert summarize.group_blind([str(tmp_path / "e.csv")], now=BEFORE) is False
    assert summarize.group_blind([str(tmp_path / "a.csv"), str(tmp_path / "b.csv")], now=BEFORE) is False
    # 作り物と本物が混ざれば本物として扱う
    assert summarize.group_blind([str(tmp_path / "a.csv"), str(ROOT / "output" / "b.csv")], now=BEFORE) is True


def test_the_clock_is_jst_and_there_is_no_date_argument(capsys):
    now = summarize._now_jst()
    assert now.utcoffset() == dt.timedelta(hours=9)
    for flag in ("--today", "--now", "--date"):
        with pytest.raises(SystemExit):
            summarize.main(ARGS + [flag, "2026-11-02"])
    capsys.readouterr()


def _csv(tmp_path):
    groups = summarize.load_allocation()
    slugs = sorted(groups)
    path = tmp_path / "e.csv"
    head = ["date", "experiment_id", "model", "target_url", "cited_article", "mentioned_v2", "error",
            "experiment_flag", "timestamp"]
    rows = [head]
    for i, s in enumerate(slugs):
        url = f"https://cross-com.jp/{s}/"
        rows.append(["2026-09-20", "", "gemini", url, str(i % 2), "0", "", "pool", "2026-09-20T01:00:00Z"])
        if i != 0:   # 1本はアフターに観測なし(欠測)
            rows.append(["2026-10-10", "", "gemini", url, str((i // 2) % 2), "0", "", "pool", "2026-10-10T01:00:00Z"])
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path, groups, slugs


def _no_group_math(monkeypatch):
    """組ごとの数字を計算する関数が呼ばれたら落とす(表示だけでなく計算もしない)。"""
    def boom(*a, **k):
        raise AssertionError("11/2 より前に組ごとの数字を計算した")
    for name in ("both_ways", "sensitivity_table", "randomization", "effect", "tally", "early_release",
                 "print_early_release", "fact_reference", "print_fact_reference", "gsc_rank_subgroups", "fact_cut"):
        monkeypatch.setattr(summarize, name, boom)


def test_real_data_before_11_02_shows_only_headings_and_totals(monkeypatch, tmp_path, capsys):
    path, groups, slugs = _csv(tmp_path)
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)   # 本物の場所にあるファイルとして扱う
    monkeypatch.setattr(summarize, "_now_jst", lambda: BEFORE)
    _no_group_math(monkeypatch)
    assert summarize.main(ARGS + ["--csv", str(path)]) == 0
    out = capsys.readouterr().out
    assert summarize.BLIND_MESSAGE in out
    assert "## 事実訂正" in out and "## 判定期間（ビフォー〜アフター）中のサイト施策一覧（判定の交絡候補）" in out
    assert f"46本全体（組をまとめた数）：アフターに観測のある記事 {len(slugs) - 1}本／46本" in out
    g = groups[slugs[0]]
    assert "アフターに観測の無い記事（欠測）1本：" in out and f"{g} 1本" in out
    assert "2026-11-02 の短期判定まで出さない" in out
    for word in ("両方込み", "## 早期解放", "=== gemini", "リード（③＋④）", "p=", "差の差"):
        assert word not in out, word


def test_real_data_from_11_02_shows_everything(monkeypatch, tmp_path, capsys):
    path, _, _ = _csv(tmp_path)
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    monkeypatch.setattr(summarize, "_now_jst", lambda: AT)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    summarize.main(ARGS + ["--csv", str(path)])
    out = capsys.readouterr().out
    assert summarize.BLIND_MESSAGE not in out and "両方込み" in out


def test_synthetic_data_shows_everything_before_11_02(monkeypatch, tmp_path, capsys):
    path, _, _ = _csv(tmp_path)
    monkeypatch.setattr(summarize, "_now_jst", lambda: BEFORE)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    summarize.main(ARGS + ["--csv", str(path)])
    out = capsys.readouterr().out
    assert summarize.BLIND_MESSAGE not in out and "両方込み" in out


def test_the_probe_is_blind_too(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    monkeypatch.setattr(summarize, "_now_jst", lambda: BEFORE)
    _no_group_math(monkeypatch)
    monkeypatch.setattr(summarize, "load_probe", lambda p: (_ for _ in ()).throw(AssertionError("読んだ")))
    summarize.main(["--probe", str(tmp_path / "a.csv")])
    assert "※ 引用プローブ：" + summarize.BLIND_MESSAGE in capsys.readouterr().out
