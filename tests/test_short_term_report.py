"""短期判定のレポートの追加分(2026-11-04)。作り物のデータだけを使う(本物の観測は読まない)。

1. 主分析の組ごとの行に、ビフォーの率と差(アフター−ビフォー)を出す
2. 主分析に、リードと FAQ の差の差の行を出す
3. 副指標 mentioned_v2 の同じ表(列を mentioned_v2 に替えて数える)
4. grounding が空になりやすい記事(10/22 までに空の行があった記事)の組ごとの本数。11/2 より前は出さない
"""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import genai_version_check as g  # noqa: E402
import summarize  # noqa: E402

G = {"a": "①対照", "b": "②FAQのみ", "c": "③リードのみ", "d": "④両方"}


def test_group_lines_show_the_before_rate_and_the_change(capsys, monkeypatch):
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): None)
    after = {"a": (G["a"], 0), "b": (G["b"], 1), "c": (G["c"], 1), "d": (G["d"], 1)}
    before = {"a": (G["a"], 1), "b": (G["b"], 0), "c": (G["c"], 0), "d": (G["d"], 1)}
    summarize.summarize(after, before, (), "t")
    out = capsys.readouterr().out
    assert "①対照: 0/1 = 0%   Δ平均 -1.00   ビフォー 1/1 = 100%・差 -100.0ポイント" in out
    assert "③リードのみ: 1/1 = 100%   Δ平均 +1.00   ビフォー 0/1 = 0%・差 +100.0ポイント" in out
    # リード：③④の差の平均 (+1+0)/2 − ①②の差の平均 (-1+1)/2 = +50。FAQ：②④ (+1+0)/2 − ①③ (-1+1)/2 = +50
    assert "差の差（組ごとの差＝アフター−ビフォーの平均を、あり側となし側で引いた値）：" \
           "リード（③＋④ 対 ①＋②） +50.0ポイント／FAQ（②＋④ 対 ①＋③） +50.0ポイント" in out


def test_an_article_without_before_counts_as_zero(capsys, monkeypatch):
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): None)
    summarize.summarize({"c": (G["c"], 1)}, {}, (), "t")
    out = capsys.readouterr().out
    assert "ビフォー 0/1 = 0%・差 +100.0ポイント" in out
    assert "リード（③＋④ 対 ①＋②） 計算できない" in out


def _row(day, s, cited, mentioned):
    return {"date": day, "model": "gemini", "target_url": f"https://cross-com.jp/{s}/", "error": "",
            "experiment_flag": "pool", "cited_article": cited, "mentioned_v2": mentioned, "timestamp": ""}


def test_the_sub_metric_counts_mentioned_v2(capsys, monkeypatch):
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): None)
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    rows = [_row("2026-09-20", "c", "1", "0"), _row("2026-10-10", "c", "1", "1"),
            _row("2026-09-20", "a", "0", "0"), _row("2026-10-10", "a", "1", "0")]
    span = ("2026-10-06", "2026-11-01")
    assert summarize.period(rows, span, "gemini", G, set(G), metric="mentioned_v2") == {"c": (G["c"], 1), "a": (G["a"], 0)}
    assert summarize.period(rows, span, "gemini", G, set(G)) == {"c": (G["c"], 1), "a": (G["a"], 1)}
    summarize.print_sub_metric(rows, ("2026-09-15", "2026-09-28"), span, G, set(G))
    out = capsys.readouterr().out
    assert f"## {summarize.SUB_METRIC_HEADING}" in out
    assert "③リードのみ: 1/1 = 100%   Δ平均 +1.00   ビフォー 0/1 = 0%" in out
    assert "①対照: 0/1 = 0%   Δ平均 +0.00" in out


def _grow(day, art, empty):
    return {"day": day, "article": art, "empty_grounding": int(empty)}


def test_empty_prone_articles_are_fixed_at_10_22(capsys):
    rows = [_grow("2026-10-01", "a", 1), _grow("2026-10-22", "b", 1), _grow("2026-10-25", "c", 1),
            _grow("2026-10-05", "d", 0)]
    assert g.empty_prone_articles(rows) == ["a", "b"]
    g.print_empty_prone_groups(rows, G, "2026-11-01")
    out = capsys.readouterr().out
    assert f"### {g.EMPTY_PRONE_HEADING}" in out
    assert "①対照 1本・②FAQのみ 1本・③リードのみ 0本・④両方 0本" in out
    assert "2026-11-01 までの観測にすると 3本（増えた 1本：③リードのみ 1本）" in out


def test_group_counts_wait_until_11_2(capsys, monkeypatch):
    jst = datetime.timezone(datetime.timedelta(hours=9))
    monkeypatch.setattr(summarize, "_now_jst", lambda: datetime.datetime(2026, 11, 1, 23, 59, tzinfo=jst))
    monkeypatch.setattr(g, "load_rows", lambda *a, **k: (_ for _ in ()).throw(AssertionError("読まない")))
    assert g.main(["--groups", "2026-11-01"]) == 0
    assert "短期判定まで出さない" in capsys.readouterr().out
