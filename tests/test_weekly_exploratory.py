"""長期判定に向けた探索的表示(週ごと・組ごとの引用・2026-11-04 事前登録)。作り物のデータだけを使う。

1. 週はアフター期間の初日(10/6)から7日ずつ。端の週は期間で切る
2. 表示1：その週に1回でも引用された記事の割合。表示2：観測1回あたりの引用の割合
3. レポートの最後に出し、「探索的な表示。判定には使わない（…登録）」と明記する
4. 11/2 以降の週の分は、本物のデータでは長期判定(12/28 00:00 JST)まで出さない。日付は実行した時刻で決める
5. 副指標 mentioned_v2 の表の見出しは「言及率」
"""
import csv
import datetime
import io
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import summarize  # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9))
G = {"a": "①対照", "c": "③リードのみ"}


def _r(day, s, cited, model="gemini", error="", flag="pool"):
    return {"date": day, "model": model, "target_url": f"https://cross-com.jp/{s}/", "cited_article": cited,
            "error": error, "experiment_flag": flag}


def _rows():
    return [
        _r("2026-10-06", "c", "1"), _r("2026-10-08", "c", "0"), _r("2026-10-07", "a", "0"),   # 10/06〜10/12
        _r("2026-10-13", "c", "0"), _r("2026-10-14", "a", "1"), _r("2026-10-15", "a", "1"),   # 10/13〜10/19
        _r("2026-10-14", "a", "", error="503 UNAVAILABLE"),                                     # 欠測は数えない
        _r("2026-10-14", "c", "1", flag="watch"),                                               # watch は数えない
        _r("2026-11-01", "c", "1"), _r("2026-11-02", "a", "1"),                                 # 10/27〜11/02
        _r("2026-11-05", "c", "1"),                                                             # 11/03〜
    ]


def test_weeks_start_on_10_6_and_count_both_ways(monkeypatch):
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    weeks = summarize.weekly_cells(_rows(), ("2026-10-06", "2026-11-08"), "gemini", G, set(G))
    assert [(lo, hi) for lo, hi, _ in weeks] == [("2026-10-06", "2026-10-12"), ("2026-10-13", "2026-10-19"),
                                                 ("2026-10-27", "2026-11-02"), ("2026-11-03", "2026-11-08")]
    first = weeks[0][2]
    assert first["③リードのみ"] == (1, 1, 1, 2), "記事1本・1回でも引用・観測2回のうち引用1回"
    assert first["①対照"] == (0, 1, 0, 1)
    assert weeks[1][2]["①対照"] == (1, 1, 2, 2), "欠測の行は数えない"
    assert weeks[1][2]["③リードのみ"] == (0, 1, 0, 1), "watch の行は数えない"
    assert first["②FAQのみ"] == (0, 0, 0, 0)


def test_held_weeks_stop_at_11_1(monkeypatch):
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    weeks = summarize.weekly_cells(_rows(), ("2026-10-06", "2026-11-08"), "gemini", G, set(G), held=True)
    assert [(lo, hi) for lo, hi, _ in weeks][-1] == ("2026-10-27", "2026-11-01"), "11/2 以降の観測は使わない"
    assert weeks[-1][2]["①対照"] == (0, 0, 0, 0) and weeks[-1][2]["③リードのみ"] == (1, 1, 1, 1)


def test_the_display_says_it_is_exploratory(monkeypatch, capsys):
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    summarize.print_weekly(_rows(), ("2026-10-06", "2026-11-01"), G, set(G))
    out = capsys.readouterr().out
    assert summarize.WEEKLY_NOTE == "探索的な表示。判定には使わない（2026-11-04 に、短期判定の結果を見た後で登録）"
    assert out.count(summarize.WEEKLY_NOTE) == 2, "見出しの直後と最後"
    assert "### 表示1：その週に1回でも引用された記事の割合" in out
    assert "### 表示2：観測1回あたりの引用の割合（引用された観測の数 ÷ 観測の数）" in out
    assert "| 10/06〜10/12 | 0/1（0%） | — | 1/1（100%） | — |" in out
    assert "| 10/06〜10/12 | 0/1（0%） | — | 1/2（50%） | — |" in out
    assert "| 10/27〜11/01（6日） |" in out


def test_long_term_blind_depends_on_the_clock_and_the_file_place(tmp_path):
    real = str(ROOT / "data" / "llm_experiment.csv")
    before = datetime.datetime(2026, 12, 27, 23, 59, tzinfo=JST)
    after = datetime.datetime(2026, 12, 28, 0, 0, tzinfo=JST)
    assert summarize.long_term_blind([real], now=before) is True
    assert summarize.long_term_blind([None], now=before) is True, "シートは本物"
    assert summarize.long_term_blind([real], now=after) is False
    assert summarize.long_term_blind([str(tmp_path / "x.csv")], now=before) is False, "作り物は出す"
    assert list(inspect.signature(summarize.long_term_blind).parameters) == ["paths", "now"], "引数で前倒しできない"
    assert "long_term_blind([a.csv])" in inspect.getsource(summarize.main), "main は時計(now の既定)で決める"


def _main(monkeypatch, tmp_path, now, real):
    rag, roi = "agentforce-rag", "agentforce-roi"
    monkeypatch.setattr(summarize, "load_allocation", lambda: {rag: "③リードのみ", roi: "①対照"})
    monkeypatch.setattr(summarize, "_now_jst", lambda: now)
    if real:
        monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    path = tmp_path / "llm_experiment.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag"])
        for day, s, c in [("2026-09-20", rag, "0"), ("2026-09-20", roi, "0"), ("2026-10-07", rag, "1"),
                          ("2026-10-08", roi, "0"), ("2026-11-03", rag, "1"), ("2026-11-04", roi, "1")]:
            w.writerow([day, "E00", "gemini", f"https://cross-com.jp/{s}/", c, "", "pool"])
    assert summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-08",
                           "--csv", str(path), "--model", "gemini"]) == 0


def test_main_prints_the_weeks_last(monkeypatch, tmp_path, capsys):
    _main(monkeypatch, tmp_path, datetime.datetime(2026, 12, 28, 9, 0, tzinfo=JST), real=False)
    out = capsys.readouterr().out
    tail = out[out.index(f"## {summarize.WEEKLY_HEADING}"):]
    assert out.index("判定: 差が +25pt") < out.index(f"## {summarize.WEEKLY_HEADING}"), "レポートの最後"
    assert "| 11/03〜11/08（6日） |" in tail and summarize.WEEKLY_HELD not in tail


def test_main_holds_the_new_weeks_on_real_data_until_12_28(monkeypatch, tmp_path, capsys):
    """2026-11-04 決定：11/2 以降を含むアフター期間では、週ごとの表示ごと長期判定まで出さない(主分析と同じ)。"""
    _main(monkeypatch, tmp_path, datetime.datetime(2026, 11, 4, 12, 0, tzinfo=JST), real=True)
    out = capsys.readouterr().out
    assert summarize.WEEKLY_HEADING not in out and summarize.LONG_BLIND_MESSAGE in out


def test_the_held_cut_still_guards_the_weeks(monkeypatch):
    """週ごとの表の計算そのものも、held なら 11/01 で切る(二重の止め)。"""
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    weeks = summarize.weekly_cells(_rows(), ("2026-10-06", "2026-11-30"), "gemini", G, set(G), held=True)
    assert max(hi for _, hi, _ in weeks) == "2026-11-01"


def test_no_weekly_display_before_11_2(monkeypatch, tmp_path, capsys):
    _main(monkeypatch, tmp_path, datetime.datetime(2026, 11, 1, 12, 0, tzinfo=JST), real=True)
    assert summarize.WEEKLY_HEADING not in capsys.readouterr().out


def test_the_sub_metric_table_says_mention_rate(monkeypatch, capsys):
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): None)
    monkeypatch.setattr(summarize, "baseline_start", lambda s: None)
    rows = [{**_r("2026-10-10", "c", "1"), "mentioned_v2": "1"}, {**_r("2026-09-20", "c", "0"), "mentioned_v2": "0"}]
    summarize.print_sub_metric(rows, ("2026-09-15", "2026-09-28"), ("2026-10-06", "2026-11-01"), G, set(G))
    out = capsys.readouterr().out
    assert "組別 言及率（アフター） / 平均変化（差の差用）" in out and "引用率" not in out
