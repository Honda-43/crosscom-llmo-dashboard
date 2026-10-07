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
import os
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
def _outcome_rows(monkeypatch, pool_rows, multi_csv=None):
    """multi_csv を渡さなければ、複数段落回答の表は「無い」ことにする(本物の表を読まない)。"""
    import pool
    monkeypatch.setattr(pool, "MULTI_PARAGRAPH_GLOBS",
                        (str(multi_csv),) if multi_csv else ("__none__/faq_multiparagraph_*.csv",))
    # ピラーの既存リンク先(6通り目・2026-10-02)はここでは見ない(tests/test_pillar.py で確かめる)
    monkeypatch.setattr(summarize.pillar, "linked_articles", lambda path=None: None)
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


# --- 7. 5通り目：複数段落回答の記事を全組から抜く(2026-09-29) -----------------------------
# B-24 で処置群の複数段落回答6本は <br> でつないで変換した。処置群だけ抜くと組の条件が
# 崩れるので、has_multi_paragraph_answer=1 の記事は**組に関係なく**抜く。
def _multi_csv(tmp_path, multi, listed=None):
    listed = [a["slug"] for a in ARTS] if listed is None else listed
    path = tmp_path / "faq_multiparagraph_20260929.csv"
    lines = ["slug,has_multi_paragraph_answer"]
    lines += [f"{s},{1 if s in multi else 0}" for s in listed]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_fifth_variant_drops_multi_paragraph_articles_from_every_group(tmp_path, monkeypatch, capsys):
    # 各組から1本ずつ(①③の同じ性質の記事も抜く)
    multi = {a["slug"] for a in ARTS[:4]}
    after = _outcome_rows(monkeypatch, _pool(2000), _multi_csv(tmp_path, multi))
    groups = {after[s][0] for s in multi}
    assert groups == set(rerandomize.GROUPS), "全組から抜く前提のテストになっていない"
    label, exclude = summarize.variants()[4]
    assert label.startswith("複数段落回答抜き（4本") and exclude == multi

    seen = []
    real = summarize.randomization
    monkeypatch.setattr(summarize, "randomization",
                        lambda a, exclude=(): seen.append(set(exclude)) or real(a, exclude))
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    assert len(seen) == 5 and seen[4] == multi, "再ランダム化検定も同じ除外で"
    body = [ln for ln in out.splitlines() if ln.startswith("複数段落回答抜き")][0]
    assert body.split()[1] == str(len(ARTS) - 4), body
    assert "※" not in out


def test_without_the_table_the_fifth_variant_is_not_shown_and_says_why(monkeypatch, capsys):
    after = _outcome_rows(monkeypatch, _pool(2000))
    assert len(summarize.variants()) == 4
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    assert "複数段落回答抜き" in out and "faq_multiparagraph_*.csv が無い" in out


def test_articles_missing_from_the_table_are_warned(tmp_path, monkeypatch, capsys):
    listed = [a["slug"] for a in ARTS[:-2]]
    after = _outcome_rows(monkeypatch, _pool(2000),
                          _multi_csv(tmp_path, {ARTS[0]["slug"]}, listed))
    summarize.sensitivity_table(after, None, "gemini")
    out = capsys.readouterr().out
    assert "表に載っていない記事が 2本" in out and ARTS[-1]["slug"] in out


def test_the_table_can_use_urls_instead_of_slugs(tmp_path):
    import pool
    path = tmp_path / "t.csv"
    path.write_text("url,has_multi_paragraph_answer\n"
                    f"https://cross-com.jp/{ARTS[0]['slug']}/,1\n"
                    f"https://cross-com.jp/{ARTS[1]['slug']}/,0\n", encoding="utf-8")
    multi, missing = pool.multi_paragraph_slugs(str(path))
    assert multi == {ARTS[0]["slug"]} and len(missing) == len(ARTS) - 2


# --- 8. 本物の表：複数段落回答の7本(2026-09-29) --------------------------------------------
# seo-agent の faq_multiparagraph_20260929.csv の写し(experiment_2x2/)。7本は偶然すべて ②④ に入った
MULTI7 = {"agentforce-for-sales-sdr-sales-coach", "agentforce-retention", "agentforce-mcp",
          "agentforce-agent-script", "buyer-enablement", "hyper-personalization", "sfa-teichaku"}


def test_the_real_table_lists_all_46_and_marks_the_seven():
    import pool
    assert Path(pool.multi_paragraph_path()).name == "faq_multiparagraph_20260929.csv"
    assert Path(pool.multi_paragraph_path()).parent == ROOT / "experiment_2x2", "写しを優先する"
    multi, missing = pool.multi_paragraph_slugs()
    assert multi == MULTI7 and not missing


def test_the_fifth_variant_drops_exactly_the_seven():
    label, exclude = summarize.variants()[4]
    assert label == "複数段落回答抜き（7本・全組）" and exclude == MULTI7


def test_the_seven_all_sit_in_faq_groups():
    groups = summarize.load_allocation()
    assert {groups[s] for s in MULTI7} == {"②FAQのみ", "④両方"}
    assert sum(groups[s] == "②FAQのみ" for s in MULTI7) == 3
    assert sum(groups[s] == "④両方" for s in MULTI7) == 4


def _real_after(pattern_after, pattern_before):
    groups = summarize.load_allocation()
    after = {a["slug"]: (groups[a["slug"]], pattern_after(i)) for i, a in enumerate(ARTS)}
    before = {a["slug"]: (groups[a["slug"]], pattern_before(i)) for i, a in enumerate(ARTS)}
    return after, before


def test_the_stratified_faq_comparison_says_the_multi_layer_cannot_be_compared(capsys):
    after, before = _real_after(lambda i: i % 2, lambda i: i % 3 == 0)
    got = summarize.faq_by_multi_paragraph(after, before, "gemini")
    out = capsys.readouterr().out
    assert got["複数段落あり"] is None
    assert "複数段落あり（7本）：比較不能（②④ 7本／①③ 0本" in out
    none = got["複数段落なし"]
    assert none["n"] == 39 and none["on"][1] == 16 and none["off"][1] == 23
    # 「なし」の層は感度分析の5通り目(7本抜き)の FAQ 差と同じ
    groups = summarize.tally(after, before, MULTI7)
    assert none["diff"] == pytest.approx(summarize.effect(groups, summarize.FAQ_ON,
                                                          summarize.FAQ_OFF)[4])
    assert "差の差（Δ平均の差）" in out


def test_the_stratified_comparison_is_part_of_the_judgement_output(monkeypatch, capsys):
    after, before = _real_after(lambda i: i % 2, lambda i: 0)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    monkeypatch.setattr(summarize, "summarize", lambda *a, **k: None)
    summarize.both_ways(after, before, "claude ")
    out = capsys.readouterr().out
    assert "FAQ の主効果（複数段落回答で層別）（claude）" in out
    assert "複数段落なし（39本）" in out


# --- 8. 二重起動の防止(2026-10-03) -----------------------------------------------------
# 同じプールに2つのプロセスが追記すると行が混ざる。作成中は <プール>.lock を置き、
# ロックがあれば2つ目は起動しない。動いていないプロセスのロック(強制終了の残り)は置き換える
def _main_without_sheets(monkeypatch, tmp_path):
    import argparse
    monkeypatch.setattr(rerandomize.allocate_47, "load_articles", lambda: (ARTS, None))
    monkeypatch.setattr(rerandomize, "load_allocation",
                        lambda: {a["slug"]: rerandomize.GROUPS[i % 4] for i, a in enumerate(ARTS)})
    monkeypatch.setattr(rerandomize.allocate_47, "load_cited", lambda a: (CITED, "test"))
    monkeypatch.setattr(rerandomize, "fast_ok", _pure_ok)
    return ["--out", str(tmp_path / "pool.csv"), "--checkpoint", str(tmp_path / "pool.checkpoint"),
            "--target", "3"]


def test_a_second_build_does_not_start_while_the_first_is_running(monkeypatch, tmp_path):
    args = _main_without_sheets(monkeypatch, tmp_path)
    lock = tmp_path / "pool.csv.lock"
    import json as _json
    lock.write_text(_json.dumps({"pid": os.getpid(), "started": "2026-10-03 12:15:49",
                                 "argv": "rerandomize.py --resume"}), encoding="utf-8")
    called = []
    monkeypatch.setattr(rerandomize, "build_to_file", lambda *a, **k: called.append(1))
    assert rerandomize.main(["--build"] + args) == 2
    assert rerandomize.main(["--resume"] + args) == 2
    assert not called, "ロックを置いたプロセスが動いている間は作らない"
    assert lock.exists(), "他のプロセスのロックは消さない"


def test_the_lock_is_held_while_building_and_released_after(monkeypatch, tmp_path):
    args = _main_without_sheets(monkeypatch, tmp_path)
    lock = tmp_path / "pool.csv.lock"
    real = rerandomize.build_to_file
    seen = []

    def spy(*a, **k):
        seen.append(lock.exists())
        return real(*a, **k)

    monkeypatch.setattr(rerandomize, "build_to_file", spy)
    assert rerandomize.main(["--build"] + args) == 0
    assert seen == [True] and not lock.exists()
    assert len(rerandomize.load(str(tmp_path / "pool.csv"))) == 3


def test_a_lock_left_by_a_dead_process_is_replaced(monkeypatch, tmp_path):
    args = _main_without_sheets(monkeypatch, tmp_path)
    lock = tmp_path / "pool.csv.lock"
    lock.write_text('{"pid": 999999999, "started": "2026-10-01 00:00:00"}', encoding="utf-8")
    assert not rerandomize.pid_alive(999999999)
    assert rerandomize.main(["--build"] + args) == 0
    assert not lock.exists()


def test_show_is_not_blocked_by_the_lock(monkeypatch, tmp_path):
    path = rerandomize.save([(20290105, "1" * 46)], ARTS, {}, str(tmp_path / "pool.csv"))
    (tmp_path / "pool.csv.lock").write_text('{"pid": %d}' % os.getpid(), encoding="utf-8")
    assert rerandomize.main(["--show", "--out", path, "--checkpoint", str(tmp_path / "c")]) == 0


def test_the_running_process_is_seen_as_alive():
    assert rerandomize.pid_alive(os.getpid())


def test_resume_takes_condition_c_from_the_checkpoint_without_the_sheet(monkeypatch, tmp_path):
    """2026-10-07：シートが読めない日(403)でも続きを作れる。条件 c は checkpoint と同じでなければならないので、そこから読む。"""
    args = _main_without_sheets(monkeypatch, tmp_path)
    assert rerandomize.main(["--build"] + args) == 0
    monkeypatch.setattr(rerandomize.allocate_47, "load_cited",
                        lambda a: (_ for _ in ()).throw(PermissionError("403")))
    assert rerandomize.main(["--resume"] + args[:-1] + ["6"]) == 0
    assert len(rerandomize.load(str(tmp_path / "pool.csv"))) == 6

