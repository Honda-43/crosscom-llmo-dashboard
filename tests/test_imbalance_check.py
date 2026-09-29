"""複数段落回答の偏りの確率(imbalance_check.py)のテスト(2026-09-29).

固定したいのは2つ:
1. 「7本すべてが ②④」の数え方と、②④ に入る本数の分布
2. 条件なしのくじの参考値(超幾何)が C(23,7)/C(46,7) になること
"""
import sys
from math import comb
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import imbalance_check as ic  # noqa: E402


def test_all_in_faq_groups_is_counted_per_allocation():
    idx = [0, 1, 2]
    rows = [(1, "24" + "2" + "1" * 43),     # 3本とも ②④
            (2, "21" + "4" + "1" * 43),     # 2本
            (3, "13" + "3" + "1" * 43)]     # 0本
    hits, dist, free = ic.summarize(rows, idx, n_arts=46, n_on=23)
    assert hits == 1
    assert dist == [1, 0, 1, 1]
    assert free == pytest.approx(comb(23, 3) / comb(46, 3))


def test_the_unconditioned_reference_for_seven_of_46():
    _, _, free = ic.summarize([(1, "2" * 46)], list(range(7)), n_arts=46, n_on=23)
    assert free == pytest.approx(comb(23, 7) / comb(46, 7))
    assert 0.0045 < free < 0.0047          # 約 0.46%


# --- 途中で止まっても続きから(2026-09-29：メモリ不足で 500件超を失ったため) -----------------
def _pure_ok(labels, _feats, _totals):
    return sum((i + 1) * g for i, g in enumerate(labels)) % 13 == 0


def _run(tmp_path, n=12):
    return ic._worker((1, 3, n, 20390101, set(), "", None, str(tmp_path)))


def test_a_worker_stopped_midway_resumes_to_the_same_result(tmp_path, monkeypatch):
    monkeypatch.setattr(ic.rerandomize, "fast_ok", _pure_ok)
    whole = _run(tmp_path / "whole")

    calls = []

    def dies(labels, feats, totals):
        calls.append(1)
        if len(calls) > 60:
            raise MemoryError("killed")
        return _pure_ok(labels, feats, totals)

    monkeypatch.setattr(ic.rerandomize, "fast_ok", dies)
    with pytest.raises(MemoryError):
        _run(tmp_path / "part")
    path = ic.part_path(1, 3, str(tmp_path / "part"))
    saved = ic.read_part(path)
    assert 0 < len(saved) < 12 and saved == whole[:len(saved)], "見つけた分は残っている"
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("2039")                                    # 書きかけの最後の1行
    monkeypatch.setattr(ic.rerandomize, "fast_ok", _pure_ok)
    assert _run(tmp_path / "part") == whole
    assert ic.read_part(path) == whole
