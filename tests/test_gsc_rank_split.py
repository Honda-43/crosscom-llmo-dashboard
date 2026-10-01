"""GSC 補助分析：上位・下位の分け方の事前固定と、層別の差の差(2026-10-01).

- 表示回数20未満(とデータなし)は下位。20以上は順位の中央値以下を上位(同値は上位)
- 分類は gsc_rank_split_v1.csv に固定し、--force なしでは作り直さない
- summarize の補助分析は推定値と95%の幅だけを出し、p値・判定・再ランダム化は出さない
- 11/2 の短期判定まで実行しない
"""
import csv
import datetime as dt
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
import gsc_rank_split as rs  # noqa: E402
import pool  # noqa: E402
import summarize  # noqa: E402


def _v2(id_, imp, pos):
    return {"id": id_, "url": f"https://cross-com.jp/{id_.lower()}/", "表示回数": imp, "平均掲載順位": pos}


def test_the_split_rules():
    rows = [_v2("E01", "100", "3.00"), _v2("E02", "50", "5.00"), _v2("E03", "20", "5.00"),
            _v2("E04", "30", "9.00"), _v2("E05", "19", "1.00"), _v2("E06", "", "")]
    items, median = rs.split(rows)
    got = {x["id"]: x["rank_split"] for x in items}
    assert median == 5.0                       # 3, 5, 5, 9 の中央値
    assert got["E01"] == "上位"
    assert got["E02"] == got["E03"] == "上位", "中央値と同じ値は上位(20ちょうどは20以上)"
    assert got["E04"] == "下位"
    assert got["E05"] == "下位", "表示回数20未満は順位が良くても下位"
    assert got["E06"] == "下位", "データなしは下位"


def test_the_saved_split_is_the_registered_one():
    """2026-10-01 に事前固定した分類。v2 から作り直しても同じになること。"""
    with io.open(rs.OUT_CSV, encoding="utf-8") as f:
        saved = list(csv.DictReader(f))
    assert list(saved[0]) == ["id", "slug", "impressions", "position", "rank_split"]
    assert len(saved) == 46 and "E37" not in {r["id"] for r in saved}
    with io.open(rs.GSC_V2_CSV, encoding="utf-8-sig") as f:
        items, median = rs.split(list(csv.DictReader(f)))
    assert round(median, 2) == 7.53
    assert {x["id"]: x["rank_split"] for x in items} == {r["id"]: r["rank_split"] for r in saved}
    assert sum(r["rank_split"] == "上位" for r in saved) == 17
    assert sum(r["rank_split"] == "下位" for r in saved) == 29


def test_the_split_is_not_rebuilt_without_force(tmp_path):
    out = tmp_path / "split.csv"
    out.write_text("既存", encoding="utf-8")
    assert rs.main(["--out", str(out)]) == 3
    assert out.read_text(encoding="utf-8") == "既存"


def test_the_blind_date_matches_the_weekly_report():
    import experiment_weekly
    assert pool.GROUP_BLIND_UNTIL == experiment_weekly.GROUP_BLIND_UNTIL.isoformat()


# --------------------------------------------------------------------------
# summarize の補助分析
# --------------------------------------------------------------------------
G = {"①": "①対照", "②": "②FAQのみ", "③": "③リードのみ", "④": "④両方"}


def _data():
    """上位:リードあり(③④)だけ引用が増える / 下位:リードなし(①②)だけ増える。"""
    after, before, split = {}, {}, {}
    for layer, gain in (("上位", ("③", "④")), ("下位", ("①", "②"))):
        for g in "①②③④":
            for i in range(3):
                s = f"{layer}-{g}-{i}"
                split[s] = layer
                before[s] = (G[g], 0)
                after[s] = (G[g], 1 if g in gain else 0)
    return after, before, split


def test_it_does_not_run_before_the_short_term_verdict(capsys):
    after, before, split = _data()
    assert summarize.gsc_rank_subgroups(after, before, split=split, today=dt.date(2026, 11, 1)) is None
    text = capsys.readouterr().out
    assert "2026-11-02 の短期判定まで実行しない" in text and "差の差" not in text


def test_estimates_intervals_and_opposite_direction(capsys):
    after, before, split = _data()
    out = summarize.gsc_rank_subgroups(after, before, split=split, today=dt.date(2026, 11, 2))
    text = capsys.readouterr().out
    head = ("  探索的分析。1マスは上位で4本前後、下位で7本前後のため判定には使わない。State 項目8の参考。\n"
            "  1マスの本数が少ないため、95%の幅（ブートストラップ）は不安定で、実際より狭く出ることがある\n")
    assert head in text
    assert text.index(head) < text.index("上位（")
    assert "5〜6本" not in text
    assert out["上位"]["リード"][0] == pytest.approx(1.0)
    assert out["下位"]["リード"][0] == pytest.approx(-1.0)
    assert out["上位"]["FAQ"][0] == pytest.approx(0.0)
    est, lo, hi = out["上位"]["リード"]
    assert lo <= est <= hi
    assert "リードの効果の向き（上位と下位）：**逆**" in text
    assert "片側p" not in text and "p=" not in text and "効いた" not in text.replace("「効いた・効かない」", "")
    assert "再ランダム化検定（" not in text


def test_the_interval_is_reproducible():
    on, off = [1, 0, 1, 0, 1], [0, 0, -1, 0]
    assert summarize.did_interval(on, off) == summarize.did_interval(on, off)
    assert summarize.did_interval([], off) is None
