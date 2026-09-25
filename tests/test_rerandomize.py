"""再ランダム化検定(条件付き並べ替え検定)のテスト(2026-09-25).

固定したいのは5つ:
1. 速い判定(fast_ok)が allocate_47.check と同じ答えを返すこと
   — 違うと、条件を満たさない割付がプールに混ざって p値が甘くなる
2. プールは条件 a〜g を満たす割付だけで、実際の割付は入らないこと
3. 保存・読み直しで同じ割付が戻ること(判定のたびに同じ p値になる)
4. 主効果と片側 p の計算
5. 判定の出力に再ランダム化とフィッシャーの p が並ぶこと。プールが無ければ「—」
"""
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import allocate_47  # noqa: E402
import rerandomize  # noqa: E402
import summarize  # noqa: E402

ARTS, _ = allocate_47.load_articles()
CITED = {"agentforce-rag", "agentforce-usage", "einstein-trust-layer"}


# --- 1. 速い判定が本物と一致する ---------------------------------------------------
def test_fast_ok_agrees_with_the_real_check():
    feats = rerandomize.features(ARTS, CITED)
    totals = [sum(f[i] for f in feats) for i in range(7)]
    agree = 0
    for seed in range(20290101, 20290101 + 3000):
        assign = allocate_47.allocate(ARTS, seed)
        labels = [rerandomize.GROUPS.index(assign[a["slug"]]) for a in ARTS]
        want, _ = allocate_47.check(ARTS, assign, CITED)
        assert rerandomize.fast_ok(labels, feats, totals) == want, seed
        agree += 1
    assert agree == 3000


def test_condition_a_holds_by_construction():
    """a(各組11〜12本)は 12/12/11/11 の組み方で必ず満たす。fast_ok は b 以降だけ見る。"""
    for seed in range(20290101, 20290101 + 200):
        assign = allocate_47.allocate(ARTS, seed)
        sizes = sorted(sum(1 for a in ARTS if assign[a["slug"]] == g)
                       for g in rerandomize.GROUPS)
        assert sizes == [11, 11, 12, 12], seed


# --- 2. プールの作り方 --------------------------------------------------------------
def test_the_pool_holds_only_allocations_that_pass_and_never_the_actual(monkeypatch):
    """実際の割付と同じものは入れない。シードは指定の番号から順に進む。"""
    feats = rerandomize.features(ARTS, CITED)
    totals = [sum(f[i] for f in feats) for i in range(7)]
    hits = []

    def every_500th(labels, _feats, _totals):
        hits.append(1)
        return len(hits) % 500 == 0

    monkeypatch.setattr(rerandomize, "fast_ok", every_500th)
    first = allocate_47.allocate(ARTS, 20290101 + 499)
    actual = rerandomize.assignment_of(ARTS, first)     # 1本目と同じものを「実際」にする
    rows, tried, last = rerandomize.build(ARTS, CITED, actual, size=3, seed_start=20290101)
    assert len(rows) == 3
    assert [r[0] for r in rows] == sorted(r[0] for r in rows), "シードは昇順"
    assert rows[0][0] > 20290101 + 499, "実際の割付と同じものを入れている"
    assert all(text != actual for _, text in rows)
    assert tried >= 2000 and last > rows[-1][0]


def test_a_real_pool_entry_satisfies_every_condition():
    """本物の条件でプールを1本だけ作り、条件 a〜g をすべて満たすことを確かめる。"""
    rows, _, _ = rerandomize.build(ARTS, CITED, actual="", size=1, seed_start=20290101)
    seed, text = rows[0]
    assign = allocate_47.allocate(ARTS, seed)
    assert rerandomize.assignment_of(ARTS, assign) == text
    ok, res = allocate_47.check(ARTS, assign, CITED)
    assert ok, [r for r in res if not r[1]]


# --- 3. 保存と読み直し --------------------------------------------------------------
def test_the_pool_round_trips(tmp_path):
    rows = [(20290105, "1" * 46), (20290110, "1234" * 11 + "12")]
    path = rerandomize.save(rows, ARTS, {"size": 2}, str(tmp_path / "pool.csv"))
    assert rerandomize.load(path) == rows
    text = Path(path).read_text(encoding="utf-8")
    assert text.startswith("#") and "size: 2" in text


def test_a_missing_pool_is_empty_not_an_error(tmp_path):
    assert rerandomize.load(str(tmp_path / "none.csv")) == []


# --- 4. 主効果と p値 ---------------------------------------------------------------
def _labels(pattern):
    """'1234...' を組番号に。記事数ぶんに伸ばす。"""
    return rerandomize.labels_of((pattern * 46)[:len(ARTS)])


def test_the_effect_is_the_difference_of_the_two_halves():
    # ①②が0、③④が1 → リード差 +100%、FAQ差は ②④=0.5 と ①③=0.5 で 0
    labels = _labels("1234")
    outcomes = [0 if g in (0, 1) else 1 for g in labels]
    lead, faq = rerandomize.effects(labels, outcomes)
    assert lead == pytest.approx(1.0)
    assert faq == pytest.approx(0.0)


def test_articles_without_an_observation_are_not_counted():
    labels = _labels("1234")
    outcomes = [None] * len(labels)
    outcomes[0], outcomes[2] = 0, 1          # ①に0、③に1 だけ
    lead, faq = rerandomize.effects(labels, outcomes)
    # リード: あり(③)1/1 − なし(①)0/1 = +1.0
    # FAQ: あり(②④)は観測0本なので 0 として扱い、なし(①③)は 1/2 → -0.5
    #      (フィッシャー側の main_effect と同じ約束)
    assert lead == pytest.approx(1.0) and faq == pytest.approx(-0.5)


def test_the_p_value_is_the_share_of_permutations_at_least_as_extreme():
    labels = _labels("1234")
    outcomes = [0 if g in (0, 1) else 1 for g in labels]
    # プール: 1本は実際と同じ並び(差が同じ)、1本は逆(差が小さい)
    same = "".join(str(g + 1) for g in labels)
    flipped = "".join(str({0: 3, 1: 4, 2: 1, 3: 2}[g]) for g in labels)
    got = rerandomize.p_values([(1, same), (2, flipped)], labels, outcomes)
    assert got["n"] == 2
    assert got["lead_diff"] == pytest.approx(1.0)
    assert got["lead_p"] == pytest.approx(0.5), "実際以上は2通り中1通り"


# --- 5. 判定の出力 -------------------------------------------------------------------
def _outcome_rows(monkeypatch, pool_rows):
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: pool_rows)
    groups = {a["slug"]: rerandomize.GROUPS[i % 4] for i, a in enumerate(ARTS)}
    monkeypatch.setattr(summarize, "load_allocation", lambda: groups)
    after = {a["slug"]: (groups[a["slug"]], i % 2) for i, a in enumerate(ARTS)}
    return after


def test_the_table_shows_both_p_values(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, [(1, "1234" * 11 + "12")])
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    assert "p(再ランダム化)" in out and "p(フィッシャー)" in out
    body = [ln for ln in out.splitlines() if ln.startswith("両方込み")][0]
    assert "—" not in body, body


def test_without_a_pool_the_randomization_column_is_a_dash(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, [])
    summarize.sensitivity_table(after, None, "gemini")
    body = [ln for ln in capsys.readouterr().out.splitlines()
            if ln.startswith("両方込み")][0]
    assert "—" in body


def test_each_variant_gets_its_own_randomization(monkeypatch, capsys):
    """感度分析の4通りそれぞれで、抜いた記事を除いて p を出す。"""
    seen = []
    after = _outcome_rows(monkeypatch, [(1, "1234" * 11 + "12")])
    real = summarize.randomization

    def spy(after_, exclude=()):
        seen.append(set(exclude))
        return real(after_, exclude)

    monkeypatch.setattr(summarize, "randomization", spy)
    summarize.sensitivity_table(after, None, "gemini")
    assert len(seen) == 4
    assert seen[0] == set() and seen[3] == set(summarize.variants()[3][1])
