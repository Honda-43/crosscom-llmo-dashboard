"""ビフォー期間の揺れの幅(before_stability.py)のテスト(2026-09-28).

固定したいのは2つ:
1. 判定と同じ行だけを数えること(watch・プール外・error・基準日より前は数えない)
2. 観測単位は行数、記事単位は「半期に1回でも =1 の記事」で率を出すこと
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import before_stability as bs  # noqa: E402

POOL = {"a", "b"}
GROUPS = {"a": "①対照", "b": "④両方"}


def _row(date, s, model="gemini", art="0", dom="0", flag="", error=""):
    return {"date": date, "model": model, "target_url": f"https://cross-com.jp/{s}/",
            "cited_article": art, "cited_domain": dom, "experiment_flag": flag, "error": error}


def test_only_rows_the_judgement_would_count_are_used(monkeypatch):
    monkeypatch.setattr(bs, "baseline_start", lambda s: "2026-09-18" if s == "b" else None)
    rows = [
        _row("2026-09-17", "a", art="1"),
        _row("2026-09-17", "b", art="1"),                  # b は 09-18 より前なので数えない
        _row("2026-09-18", "a", flag="watch"),
        _row("2026-09-18", "agentforce-coworker"),          # プール外
        _row("2026-09-19", "a", error="429"),
        _row("2026-09-28", "a", art="1"),                  # 期間外
        _row("2026-09-24", "b", model="claude", dom="1"),
    ]
    obs, dropped = bs.collect(rows, pool=POOL, groups=GROUPS)
    assert [(o[0], o[1], o[2], o[3]) for o in obs] == [
        ("gemini", "前半", "①対照", "a"), ("claude", "後半", "④両方", "b")]
    assert dropped == {"基準日より前": 1, "watch": 1, "プール外": 1, "error（gemini 09-19）": 1}


def test_row_and_article_rates():
    rows = [_row("2026-09-17", "a", art="1"), _row("2026-09-18", "a"),
            _row("2026-09-18", "b"), _row("2026-09-19", "b")]
    obs, _ = bs.collect(rows, pool=POOL, groups=GROUPS)
    assert bs.by_row(obs, bs.ARTICLE) == (1, 4)
    assert bs.by_article(obs, bs.ARTICLE) == (1, 2)
    assert bs.fmt(1, 4) == "25.0%（1/4）" and bs.fmt(0, 0) == "—"
