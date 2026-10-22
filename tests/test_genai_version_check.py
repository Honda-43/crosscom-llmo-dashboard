"""Gemini のライブラリの版の変化と引用の取り出し(2026-10-22)。作り物の raw だけを使う(本物の観測は読まない)。"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import genai_version_check as g  # noqa: E402
import summarize  # noqa: E402

ARTICLES = [f"a{i}" for i in range(9)]
EMPTY_ARTICLES = {"a0", "a4"}                 # いつも grounding が空の記事(記事の性質)


def _write(tmp_path, step_from=None):
    """10/01〜10/30。1日3〜4本を不規則に回す。step_from 以降はすべて空(取り出しが壊れた場合)。"""
    start = dt.date(2026, 10, 1)
    k = 0
    for n in range(30):
        day = (start + dt.timedelta(days=n)).isoformat()
        folder = tmp_path / day
        folder.mkdir()
        for _ in range(3 + n % 2):
            art = ARTICLES[k % len(ARTICLES)]
            k += 1
            empty = art in EMPTY_ARTICLES or (step_from is not None and day >= step_from)
            urls = [] if empty else ["https://vertexaisearch.cloud.google.com/x", "https://vertexaisearch.cloud.google.com/y"]
            rec = {"date": day, "timestamp": f"{day}T00:30:00Z", "target_url": f"https://cross-com.jp/{art}/",
                   "error": None, "experiment_flag": "pool", "cited_urls": urls,
                   "cited_domains": [] if empty else ["example.com", "cross-com.jp"],
                   "cited_article": 1, "mentioned_v2": 1, "answer": "（読まない）"}
            (folder / f"P{k:03d}_gemini.json").write_text(json.dumps(rec), encoding="utf-8")
        # watch と欠測の行は数えない
        (folder / "E37_gemini.json").write_text(json.dumps(
            {"date": day, "timestamp": f"{day}T00:30:00Z", "target_url": "https://cross-com.jp/a1/", "error": None,
             "experiment_flag": "watch", "cited_urls": [], "cited_domains": []}), encoding="utf-8")


VERSIONS = [("2026-10-01", "1.0"), ("2026-10-16", "1.1")]


def test_reads_only_the_citation_columns(tmp_path, monkeypatch):
    _write(tmp_path)
    monkeypatch.setattr(g, "VERSION_FROM", VERSIONS)
    rows = g.load_rows(str(tmp_path), pool=set(ARTICLES))
    assert len(rows) == 105, "watch の行は数えない"
    assert set(rows[0]) == {"day", "version", "article", "has_citation", "domains_per_row", "empty_grounding"}
    assert "cited_article" not in g.READ_KEYS and not any("mention" in k for k in g.READ_KEYS)
    assert {r["version"] for r in rows if r["day"] < "2026-10-16"} == {"1.0"}


def test_no_step_when_only_the_articles_differ(tmp_path, monkeypatch):
    _write(tmp_path)
    monkeypatch.setattr(g, "VERSION_FROM", VERSIONS)
    st = g.steps(g.load_rows(str(tmp_path), pool=set(ARTICLES)))
    assert [s["day"] for s in st] == ["2026-10-16"] and st[0]["step"] == ""


def test_a_real_step_is_found(tmp_path, monkeypatch):
    _write(tmp_path, step_from="2026-10-16")
    monkeypatch.setattr(g, "VERSION_FROM", VERSIONS)
    st = g.steps(g.load_rows(str(tmp_path), pool=set(ARTICLES)))
    assert set(st[0]["step"].split("・")) == set(g.METRICS)


def test_the_versions_match_the_pin():
    """版の一覧の最後は requirements.txt で固定した版(2026-10-22 の実験ジョブ)。"""
    assert g.VERSION_FROM[-1] == ("2026-10-21", "2.32.0")
    assert "google-genai==2.32.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert len(g.VERSION_FROM) - 1 == 10, "9/15〜10/22 に10回上がった"
    assert g.version_on("2026-09-28") == "2.25.0" and g.version_on("2026-10-06") == "2.28.0"


def test_the_report_note(capsys):
    summarize.print_genai_version_note()
    out = capsys.readouterr().out
    assert f"### {summarize.GENAI_VERSION_HEADING}" in out
    assert "ビフォー（2.23.0〜2.25.0）とアフター（2.28.0〜2.32.0）で違う（2026-10-22 に 2.32.0 で固定）" in out
    assert "同じ日は4組とも同じ版のため、前後の変化を組どうしで比べる判定では打ち消される" in out
    assert "差の差" not in out, "11/2 より前の表示の見張り(test_group_blind)に掛からない言い方にする" and "段差なし" in out
    assert not any(grp in out for grp in summarize.GROUP_ORDER)
