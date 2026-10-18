"""46本の組の正本は experiment_2x2/allocation_v1.csv(9/28 の割付)。2026-10-18 に確認して固定する。

experiment_2x2/targets.csv(seo-agent の編集禁止リスト)には、9/14 の48本版の仮の振り分けの名残の group 列があった
(46本中37本が allocation_v1 と違う)。dashboard はこの列を読まない(公開日の published 列と URL だけ)。
seo-agent 側でこの列を消した(2026-10-18・ef5ff40)。ここのテストは **group 列がある場合・無い場合のどちらでも通る**
ように targets.csv の group 列には触れない。確かめるのは、判定・感度分析・再ランダム化検定・欠測の組別集計・
ピラーの偏りが allocation_v1 の組で数えることだけ(割付表と違う組を別に与えても、結果がそちらに動かないことで確かめる)。
"""
import ast
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import experiment_weekly  # noqa: E402
import imbalance_check  # noqa: E402
import llmo_probe  # noqa: E402
import pillar  # noqa: E402
import pool  # noqa: E402
import probe_summary  # noqa: E402
import rerandomize  # noqa: E402
import summarize  # noqa: E402

ALLOCATION = ROOT / "experiment_2x2" / "allocation_v1.csv"
TARGETS = ROOT / "experiment_2x2" / "targets.csv"
CODE_DIRS = ("src", "experiment_2x2", "app")


def _rows(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


def _by_slug(path):
    return {pool.slug(r["url"]): r["group"] for r in _rows(path)}


def _code_strings(path):
    """docstring を除いた、コードの中の文字列定数。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _other(group):
    """割付表と必ず違う組(1つずらす)。古い割付の代わりに使う。"""
    return rerandomize.GROUPS[(rerandomize.GROUPS.index(group) + 1) % len(rerandomize.GROUPS)]


# seo-agent 側で 2026-10-18 に targets.csv の group 列を削除した(ef5ff40)。列が戻っていないことを確かめる
def test_targets_csv_has_no_group_column():
    with io.open(TARGETS, encoding="utf-8-sig") as fh:
        header = next(csv.reader(line for line in fh if not line.startswith("#")))
    assert "group" not in header, header


def test_targets_csv_still_lists_the_same_46_with_their_published_dates():
    """group 列の有無にかかわらず、targets.csv は46本の URL と公開日を持つ(dashboard が読むのはこの2列だけ)。"""
    rows = _rows(TARGETS)
    assert {pool.slug(r["url"]) for r in rows} == set(_by_slug(ALLOCATION))
    assert all(r.get("published") for r in rows)


def test_only_allocate_47_opens_targets_csv_and_it_reads_the_published_date_only():
    """コード(コメント・docstring を除く)で targets.csv を開くのは allocate_47.load_articles だけ。
    凍結の一覧(experiment_freeze)は config の edit_ban_file から URL だけを読む。"""
    users = sorted(str(p.relative_to(ROOT)).replace("\\", "/")
                   for d in CODE_DIRS for p in (ROOT / d).rglob("*.py")
                   if any("targets.csv" in s for s in _code_strings(p)))
    assert users == ["experiment_2x2/allocate_47.py"], users
    import inspect
    import allocate_47
    import experiment_freeze
    src = inspect.getsource(allocate_47.load_articles)
    assert "r.get('published'" in src and "group" not in src
    assert "group" not in inspect.getsource(experiment_freeze._read_slugs)
    arts, _ = allocate_47.load_articles()
    assert len(arts) == 46 and all(a["published"] for a in arts)


def test_every_judgement_path_reads_the_groups_from_allocation_v1():
    assert Path(pool.load_allocation.__defaults__[0]).resolve() == ALLOCATION.resolve()
    assert Path(experiment_weekly.ALLOCATION_FILE).resolve() == ALLOCATION.resolve()
    # 判定・感度分析(summarize)・再ランダム化検定(rerandomize)・不均衡の確認・参考の引用プローブは同じ関数
    for module in (summarize, rerandomize, imbalance_check, probe_summary):
        assert module.load_allocation is pool.load_allocation, module.__name__
    assert pool.load_allocation() == _by_slug(ALLOCATION)
    # 欠測の組別集計(実験の週次集計)は記事IDで引く。同じ表の同じ組
    by_id = {r["id"]: r["group"] for r in _rows(ALLOCATION)}
    assert experiment_weekly.load_allocation() == by_id
    # 引用プローブの対象(llmo_probe.load_targets)の組も割付表から
    assert {pool.slug(t["url"]): t["group"] for t in llmo_probe.load_targets()} == _by_slug(ALLOCATION)


def test_the_judgement_counts_by_the_allocation_not_by_the_old_groups():
    """summarize.period(主指標の集計・感度分析の元)は渡された割付で組を決める。main は load_allocation() を渡す。"""
    import inspect
    alloc = pool.load_allocation()
    s = "agentforce-rag"
    rows = [{"date": "2026-10-06", "model": "gemini", "target_url": f"https://cross-com.jp/{s}/",
             "cited_article": "1", "error": "", "experiment_flag": "pool", "group": _other(alloc[s])}]
    got = summarize.period(rows, ("2026-10-06", "2026-10-06"), "gemini", alloc, {s})
    assert got == {s: (alloc[s], 1)}, "行に別の組が書いてあっても割付表の組"
    main_src = inspect.getsource(summarize.main)
    assert "groups = load_allocation()" in main_src and "groups, pool" in main_src.replace("groups,pool", "groups, pool")


def test_the_rerandomization_uses_the_allocation_for_the_actual_assignment(monkeypatch):
    """summarize.randomization の「実際の割付」は allocation_v1 から作る。"""
    import allocate_47
    seen = {}
    monkeypatch.setattr(rerandomize, "load", lambda *a, **k: [{"x": 1}] * rerandomize.POOL_MIN)
    monkeypatch.setattr(rerandomize, "outcomes_for", lambda arts, cited, exclude: [0] * len(arts))
    monkeypatch.setattr(rerandomize, "p_values",
                        lambda pool_rows, actual, outcomes: seen.setdefault("actual", actual) and {"ok": True})
    summarize.randomization({})
    arts, _ = allocate_47.load_articles()
    alloc = pool.load_allocation()
    assert seen["actual"] == [rerandomize.GROUPS.index(alloc[a["slug"]]) for a in arts]
    # 割付が変われば実際の割付も変わる(= 割付表から作っている)
    seen.clear()
    monkeypatch.setattr(summarize, "load_allocation", lambda: {k: _other(v) for k, v in alloc.items()})
    summarize.randomization({})
    assert seen["actual"] == [rerandomize.GROUPS.index(_other(alloc[a["slug"]])) for a in arts]


def test_the_missing_counts_by_group_follow_the_allocation():
    """欠測の組別集計(experiment_weekly)は割付表の組で数える(行に別の組が書いてあっても使わない)。"""
    import datetime as dt
    by_id = experiment_weekly.load_allocation()
    row = next(r for r in _rows(ALLOCATION) if pool.slug(r["url"]) == "agentforce-rag")
    eid, group = row["id"], by_id[row["id"]]
    rows = [{"date": "2026-10-16", "model": "gemini", "experiment_id": eid, "error": "503 UNAVAILABLE",
             "group": _other(group)}]
    day = dt.date(2026, 10, 16)
    counts = experiment_weekly.gemini_misses_by_group(rows, day, day, by_id)
    assert counts[group] == 1 and sum(counts.values()) == 1


def test_the_pillar_bias_takes_the_group_from_the_allocation_even_if_the_table_is_stale(tmp_path):
    """ピラーの偏り(判定レポートの冒頭・感度分析の6つ目)は表の group 列でなく割付表の組で数える(2026-10-18)。"""
    alloc = pool.load_allocation()
    s = "agentforce-rag"
    right, stale = alloc[s], _other(alloc[s])      # 表には割付表と違う組が書いてある
    path = tmp_path / "pillar_existing_links_x.csv"
    path.write_text(f"pillar,slug,group,links\nagentforce-guide,{s},{stale},1\n", encoding="utf-8")
    counts = pillar.balance(str(path))[0][1]
    assert counts[right] == 1 and counts[stale] == 0
    over = tmp_path / "pillar_strong_overlap_x.csv"
    over.write_text(f"orphan,pillar,prompt_slug,group\norphan-x,agentforce-guide,{s},{stale}\n", encoding="utf-8")
    got = pillar.poaching({"targets": ["orphan-x"]}, str(over))
    assert got["linked"] == [("orphan-x", s, right)]
