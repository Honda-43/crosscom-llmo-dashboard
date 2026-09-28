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


def _pool(n):
    return [(i, "1234" * 11 + "12") for i in range(n)]


def test_the_table_shows_both_p_values(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, _pool(2000))
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    assert "p(再ランダム化)" in out and "p(フィッシャー)" in out
    body = [ln for ln in out.splitlines() if ln.startswith("両方込み")][0]
    assert "—" not in body, body
    assert "使用した割付数：2,000" in out


# --- 5b. プールの下限(2026-09-28)：2,000 未満なら再ランダム化の p を出さない ---------------
def test_the_pool_minimum_is_2000_and_the_target_stays_5000():
    assert rerandomize.POOL_MIN == 2000 and rerandomize.POOL_SIZE == 5000


def test_a_short_pool_is_not_tested_but_fisher_is_still_shown(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, _pool(1999))
    assert summarize.randomization(after) == {"n": 1999, "short": True}
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    body = [ln for ln in out.splitlines() if ln.startswith("両方込み")][0]
    cols = body.split()
    assert cols[-5] == "—" and cols[-2] == "—", body     # 再ランダム化の p は出さない
    assert cols[-4] != "—" and cols[-1] != "—", body     # フィッシャーは参考として出す
    assert "プール不足（1,999件／下限2,000）" in out
    assert "使用した割付数" not in out


def test_the_per_variant_summary_shows_the_count_or_the_shortage(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, _pool(2000))
    summarize.summarize(after, None, (), "gemini 両方込み")
    assert "使用した割付数：2,000" in capsys.readouterr().out
    after = _outcome_rows(monkeypatch, _pool(10))
    summarize.summarize(after, None, (), "gemini 両方込み")
    out = capsys.readouterr().out
    assert "プール不足（10件／下限2,000）" in out and "片側p=" in out   # フィッシャーは出る


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


# --- 6. 1行ずつ追記・途中再開(2026-09-28) ---------------------------------------------
# 9/28 に一気に作ろうとしてメモリ不足で止められた。見つけるたびに追記し、止まっても
# --resume で続きから作れること。**再開した結果が、一気に作った結果と同じ**であること。
def _pure_ok(labels, _feats, _totals):
    """割付だけで決まる速い合否(約 1/13)。本物の条件は 1/9,200 で遅すぎるため。"""
    return sum((i + 1) * g for i, g in enumerate(labels)) % 13 == 0


def _stop_after(n, exc):
    calls = []

    def ok(labels, feats, totals):
        calls.append(1)
        if len(calls) > n:
            raise exc
        return _pure_ok(labels, feats, totals)
    return ok


def _build(tmp_path, name, resume=False, target=30, **kw):
    kw.setdefault("log", lambda *a, **k: None)
    return rerandomize.build_to_file(
        ARTS, CITED, actual="", out=str(tmp_path / f"{name}.csv"),
        checkpoint=str(tmp_path / f"{name}.checkpoint"), target=target,
        seed_start=20290101, resume=resume, meta={"target": target}, **kw)


def _one_shot(tmp_path, monkeypatch, target=30):
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    _build(tmp_path, "whole", target=target)
    return (tmp_path / "whole.csv").read_bytes()


def test_resume_after_ctrl_c_matches_a_single_run(tmp_path, monkeypatch):
    whole = _one_shot(tmp_path, monkeypatch)
    for stop in (57, 100, 60):                 # 3回止めて、そのたびに続きから
        monkeypatch.setattr(rerandomize, "fast_ok", _stop_after(stop, KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            _build(tmp_path, "part", resume=(tmp_path / "part.checkpoint").exists())
        assert 0 < len(rerandomize.load(str(tmp_path / "part.csv"))) < 30
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    state = _build(tmp_path, "part", resume=True)
    assert state["done"] and state["count"] == 30
    assert (tmp_path / "part.csv").read_bytes() == whole


def test_resume_after_a_hard_kill_matches_a_single_run(tmp_path, monkeypatch):
    """強制終了(メモリ不足など)：checkpoint が最後の行より古く、最後の行が書きかけでも同じになる。"""
    whole = _one_shot(tmp_path, monkeypatch)
    monkeypatch.setattr(rerandomize, "fast_ok", _stop_after(200, RuntimeError("killed")))
    with pytest.raises(RuntimeError):
        _build(tmp_path, "part", checkpoint_every=10 ** 9)
    ck = tmp_path / "part.checkpoint"
    stale = rerandomize.read_checkpoint(str(ck))
    stale.update(next_seed=20290101 + 5, count=0)       # 保存の間に落ちた状態を作る
    rerandomize.write_checkpoint(stale, str(ck))
    with open(tmp_path / "part.csv", "a", encoding="utf-8", newline="") as f:
        f.write("99,2029")                              # 書きかけの最後の1行
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    _build(tmp_path, "part", resume=True)
    assert (tmp_path / "part.csv").read_bytes() == whole


def test_rows_found_before_a_stop_are_valid(tmp_path, monkeypatch):
    _one_shot(tmp_path, monkeypatch)
    monkeypatch.setattr(rerandomize, "fast_ok", _stop_after(150, KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _build(tmp_path, "part")
    part = rerandomize.load(str(tmp_path / "part.csv"))
    assert part == rerandomize.load(str(tmp_path / "whole.csv"))[:len(part)]
    state = rerandomize.read_checkpoint(str(tmp_path / "part.checkpoint"))
    assert state["count"] == len(part) and not state["done"]
    assert state["last_tried_seed"] >= part[-1][0]


def test_it_stops_at_the_target_and_resuming_a_finished_pool_adds_nothing(tmp_path, monkeypatch):
    _one_shot(tmp_path, monkeypatch, target=20)
    before = (tmp_path / "whole.csv").read_bytes()
    assert len(rerandomize.load(str(tmp_path / "whole.csv"))) == 20
    state = _build(tmp_path, "whole", resume=True, target=20)
    assert state["done"] and (tmp_path / "whole.csv").read_bytes() == before
    # 目標を増やして再開すれば、続きの行が足される(一気に 25 作ったのと同じ)
    _build(tmp_path, "whole", resume=True, target=25)
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    _build(tmp_path, "whole25", target=25)
    assert (rerandomize.load(str(tmp_path / "whole.csv"))
            == rerandomize.load(str(tmp_path / "whole25.csv")))


def test_progress_reports_count_elapsed_and_seed(tmp_path, monkeypatch):
    assert rerandomize.PROGRESS_EVERY == 100
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    lines, ticks = [], iter(range(0, 10 ** 6, 7))
    _build(tmp_path, "p", target=20, progress=10, clock=lambda: next(ticks),
           log=lambda msg, **k: lines.append(msg))
    assert len(lines) == 2
    assert "10/20 件" in lines[0] and "経過 0:" in lines[0] and "現在のシード 2029" in lines[0]


def test_resume_refuses_a_different_condition(tmp_path, monkeypatch):
    monkeypatch.setattr(rerandomize, "fast_ok", _stop_after(100, KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _build(tmp_path, "part")
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    with pytest.raises(rerandomize.ResumeError, match="cited"):
        rerandomize.build_to_file(
            ARTS, CITED | {"agentforce-roi"}, actual="", out=str(tmp_path / "part.csv"),
            checkpoint=str(tmp_path / "part.checkpoint"), target=30, seed_start=20290101,
            resume=True, log=lambda *a, **k: None)


def test_build_does_not_overwrite_an_existing_pool(tmp_path):
    out = tmp_path / "pool.csv"
    out.write_text("keep", encoding="utf-8")
    assert rerandomize.main(["--build", "--out", str(out),
                             "--checkpoint", str(tmp_path / "c")]) == 2
    assert out.read_text(encoding="utf-8") == "keep"


def test_load_skips_a_half_written_last_line(tmp_path):
    path = rerandomize.save([(20290105, "1" * 46)], ARTS, {}, str(tmp_path / "pool.csv"))
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("2,2029011")
    assert rerandomize.load(path) == [(20290105, "1" * 46)]
