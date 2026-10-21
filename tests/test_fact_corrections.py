"""事実訂正(2026-10-20 準備)の扱い。

本田さん確認：Agentforce の顧客導入は0件。凍結46本のうち約20本に導入実績があるように読める記述があり、
事実と違う文だけを近く直す(記事制作から一覧が届き、効果測定チャットで確認してから反映)。まだ反映していない。
- 感度分析 A「事実訂正あり記事抜き」(対象の記事を全組から抜く)・B「事実訂正前で打ち切り」(アフターを最も早い訂正の時刻で切る)
- 早期解放の条件(3)・再ランダム化検定にも A・B を入れる。抜く記事の集合が既存の行と同じならまとめる
- 判定レポートの冒頭に対象の記事の組ごとの本数。組の間の差が3本以上なら「偏りあり」
- ドリフト検知：fact_corrections.csv と修正前後の文の表から、その文の変化だけを想定内にする(E33 と同じ考え方)
記録が届くまで experiment_2x2/fact_corrections.csv は見出しだけ。ここのテストは届く前も後も通る。
"""
import csv
import datetime as dt
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import drift_check  # noqa: E402
import pool  # noqa: E402
import summarize  # noqa: E402

HEAD = ["E番号", "slug", "組", "リビジョン", "時刻"]


def _by_group():
    out = {}
    for s, g in sorted(pool.load_allocation().items()):
        out.setdefault(g, []).append(s)
    return out


def _table(monkeypatch, tmp_path, rows):
    path = tmp_path / "fact_corrections.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HEAD] + rows)
    monkeypatch.setattr(pool, "FACT_CORRECTIONS_CSV", str(path))
    return path


def _no_pool(monkeypatch, seen=None):
    def fake(after, exclude=()):
        if seen is not None:
            seen.append((dict(after), set(exclude)))
        return None
    monkeypatch.setattr(summarize, "randomization", fake)


# --- 記録が届く前 --------------------------------------------------------------------------------------
def test_the_files_exist_with_the_agreed_columns():
    with io.open(pool.FACT_CORRECTIONS_CSV, encoding="utf-8") as f:
        assert next(csv.reader(f)) == list(pool.FACT_CORRECTION_COLUMNS) == HEAD
    with io.open(drift_check.FACT_SENTENCES, encoding="utf-8") as f:
        assert next(csv.reader(f)) == ["E番号", "slug", "修正前", "修正後"]
    # 表に入った記事はプール46本の中で、組は allocation_v1.csv と同じ(記録が届く前は空)
    alloc = pool.load_allocation()
    for r in pool.load_fact_corrections():
        assert r["slug"] in alloc, r
        assert not r["group"] or r["group"] == alloc[r["slug"]], r


def test_before_the_record_both_rows_say_pending(monkeypatch, tmp_path, capsys):
    _table(monkeypatch, tmp_path, [])
    _no_pool(monkeypatch)
    labels = [label for label, _ in summarize.variants()]
    assert not any(summarize.FACT_A in x for x in labels), "A は記事が届くまで variants に入れない"
    summarize.sensitivity_table({"agentforce-rag": ("①対照", 0)}, {}, cut=None)
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.startswith(("事実訂正あり記事抜き", "事実訂正前で打ち切り"))]
    assert len(rows) == 2 and all("記録待ち" in ln for ln in rows), rows
    assert "「事実訂正あり記事抜き」：記録待ち" in out and "「事実訂正前で打ち切り」：記録待ち" in out
    summarize.print_fact_correction_head()
    assert "記録待ち：experiment_2x2/fact_corrections.csv が空" in capsys.readouterr().out


def test_before_the_record_the_early_release_rule_notes_the_pending_rows(monkeypatch, tmp_path, capsys):
    _table(monkeypatch, tmp_path, [])
    after = {"agentforce-rag": ("③リードのみ", 1), "agentforce-features": ("①対照", 0)}
    rows = summarize.early_release(after, {}, {"n": 2500, "lead_p": 0.001, "faq_p": 0.001})
    assert len(rows[0]["signs"]) == len(summarize.variants()), "記録待ちの行は条件(3)に入れない"
    summarize.print_early_release(after, {}, {"n": 2500, "lead_p": 0.001, "faq_p": 0.001})
    out = capsys.readouterr().out
    assert "条件(3)の「事実訂正あり記事抜き」「事実訂正前で打ち切り」は記録待ちのため含めていない" in out


# --- A：事実訂正あり記事抜き --------------------------------------------------------------------------
def test_a_drops_the_listed_articles_from_every_group_and_is_last(monkeypatch, tmp_path):
    _table(monkeypatch, tmp_path, [])
    before = summarize.variants()
    g = _by_group()
    picked = g["①対照"][:2] + g["④両方"][:1]
    _table(monkeypatch, tmp_path, [["", s, "", "", ""] for s in picked] + [["", picked[0], "", "9100", ""]])
    after = summarize.variants()
    assert after[:-1] == before, "既存の行(番号・中身)は変えない"
    assert after[-1] == (f"事実訂正3本抜き（{'・'.join(picked)}）", set(picked)), "同じ記事が2行あっても1本"


def test_a_is_merged_when_it_equals_an_existing_row(monkeypatch, tmp_path):
    _table(monkeypatch, tmp_path, [["E23", "buyer-enablement", "④両方", "", ""],
                                   ["E27", "hyper-personalization", "④両方", "", ""]])
    rows = summarize.variants()
    sets = [frozenset(e) for _, e in rows]
    assert len(sets) == len(set(sets))
    merged = [label for label, e in rows if e == set(pool.LINK_LOSS_SLUGS)]
    assert len(merged) == 1 and "〔事実訂正2本抜き（E23・E27）と同じ記事集合〕" in merged[0]


def test_a_reports_what_is_left_and_its_randomization_uses_the_same_exclusion(monkeypatch, tmp_path, capsys):
    g = _by_group()
    picked = g["①対照"][:3]
    _table(monkeypatch, tmp_path, [["", s, "", "", ""] for s in picked])
    seen = []
    _no_pool(monkeypatch, seen)
    after = {s: (grp, 0) for grp, ss in g.items() for s in ss}
    summarize.sensitivity_table(after, {})
    out = capsys.readouterr().out
    assert set(picked) in [ex for _, ex in seen]
    n = {k: len(v) for k, v in g.items()}
    assert (f"「事実訂正3本抜き（{'・'.join(picked)}）」で抜いた後の残り：{len(after) - 3}本／{len(after)}本（①対照 {n['①対照'] - 3}本・"
            f"②FAQのみ {n['②FAQのみ']}本・③リードのみ {n['③リードのみ']}本・④両方 {n['④両方']}本）") in out


# --- 冒頭の組ごとの本数と偏り --------------------------------------------------------------------------
def test_the_head_counts_by_group_and_flags_a_gap_of_three(monkeypatch, tmp_path, capsys):
    g = _by_group()
    _table(monkeypatch, tmp_path, [["", s, "", "", ""] for s in g["①対照"][:3]])
    counts = summarize.print_fact_correction_head()
    out = capsys.readouterr().out
    assert counts == {"①対照": 3, "②FAQのみ": 0, "③リードのみ": 0, "④両方": 0}
    assert "対象 3本：①対照 3本・②FAQのみ 0本・③リードのみ 0本・④両方 0本 → **偏りあり**（組の間の差 3本。3本以上）" in out
    _table(monkeypatch, tmp_path, [["", s, "", "", ""] for s in g["①対照"][:2]])
    summarize.print_fact_correction_head()
    assert "偏りなし（組の間の差 2本）" in capsys.readouterr().out


def test_the_head_warns_about_a_wrong_group_and_shows_the_first_time(monkeypatch, tmp_path, capsys):
    g = _by_group()
    a, b = g["②FAQのみ"][0], g["③リードのみ"][0]
    _table(monkeypatch, tmp_path, [["", a, "①対照", "9101", "2026-10-25 14:03:10"],
                                   ["", b, "③リードのみ", "9102", "2026-10-24 09:00"]])
    summarize.print_fact_correction_head()
    out = capsys.readouterr().out
    assert "最も早い訂正の時刻：2026-10-24 09:00:00（時刻の入った記事 2本／2本）" in out
    assert f"表の「組」が allocation_v1.csv と違う記事（組は allocation_v1.csv を使う）：{a}" in out


# --- B：事実訂正前で打ち切り ---------------------------------------------------------------------------
URL = "https://cross-com.jp/agentforce-rag/"


def _obs(date, cited, ts=""):
    return {"date": date, "model": "gemini", "target_url": URL, "cited_article": cited, "error": "",
            "experiment_flag": "pool", "timestamp": ts}


def test_b_keeps_only_observations_before_the_first_correction():
    groups, pool46 = {"agentforce-rag": "③リードのみ"}, pool.pool_slugs()
    rows = [_obs("2026-10-10", "0", "2026-10-10T01:00:00Z"),
            _obs("2026-10-24", "0", "2026-10-23T23:30:00Z"),     # 10/24 08:30 JST：訂正(09:00)より前
            _obs("2026-10-24", "1", "2026-10-24T00:30:00Z"),     # 10/24 09:30 JST：訂正より後
            _obs("2026-10-30", "1")]                             # 時刻なし・訂正の日より後
    until = dt.datetime(2026, 10, 24, 9, 0)
    cut = summarize.fact_cut(rows, ("2026-10-06", "2026-11-01"), "gemini", groups, pool46, until)
    assert cut["status"] == "cut" and cut["label"] == "事実訂正前で打ち切り（2026-10-24 09:00 より前）"
    assert cut["after"] == {"agentforce-rag": ("③リードのみ", 0)}
    assert (cut["obs_full"], cut["days_full"], cut["obs_cut"], cut["days_cut"]) == (4, 3, 2, 2)
    line = summarize.fact_lines({}, cut)[-1]
    assert "アフター期間の観測 4回（3日）のうち使えるのは 2回（2日）" in line
    # 時刻の無い行は日付で見る：訂正の日の観測は入れない
    assert not summarize.before_cut(_obs("2026-10-24", "0"), until)
    assert summarize.before_cut(_obs("2026-10-23", "0"), until)


def test_b_states(monkeypatch, tmp_path):
    groups, pool46 = {"agentforce-rag": "③リードのみ"}, pool.pool_slugs()
    rows = [_obs("2026-10-10", "0", "2026-10-10T01:00:00Z")]
    span = ("2026-10-06", "2026-11-01")
    _table(monkeypatch, tmp_path, [])
    assert summarize.fact_cut(rows, span, "gemini", groups, pool46)["status"] == "pending"
    assert summarize.fact_cut(rows, span, "gemini", groups, pool46, dt.datetime(2026, 10, 1))["status"] == "none"
    # 短期判定の期間の後に直した → 短期判定では全期間と同じ。長期判定では打ち切る
    late = dt.datetime(2026, 11, 10, 10, 0)
    assert summarize.fact_cut(rows, span, "gemini", groups, pool46, late)["status"] == "same"
    rows.append(_obs("2026-11-20", "1", "2026-11-20T01:00:00Z"))
    assert summarize.fact_cut(rows, ("2026-10-06", "2026-12-28"), "gemini", groups, pool46, late)["status"] == "cut"
    # 時刻は fact_corrections.csv の最も早いもの
    _table(monkeypatch, tmp_path, [["", "agentforce-rag", "", "1", "2026-10-26 10:00"],
                                   ["", "agentforce-features", "", "2", "2026-10-21 15:00:00"]])
    assert summarize.fact_cut(rows, span, "gemini", groups, pool46)["at"] == dt.datetime(2026, 10, 21, 15, 0)


def test_b_same_period_is_merged_into_the_first_row(monkeypatch, tmp_path, capsys):
    _table(monkeypatch, tmp_path, [])
    _no_pool(monkeypatch)
    cut = {"status": "same", "label": "事実訂正前で打ち切り（2026-11-10 10:00 より前）", "after": {},
           "obs_full": 5, "days_full": 2, "obs_cut": 5, "days_cut": 2, "at": None}
    summarize.sensitivity_table({"agentforce-rag": ("①対照", 0)}, {}, cut=cut)
    out = capsys.readouterr().out
    assert "両方込み〔事実訂正前で打ち切り（2026-11-10 10:00 より前）と同じ観測〕" in out
    assert not [ln for ln in out.splitlines() if ln.startswith("事実訂正前で打ち切り")]


def test_b_row_its_randomization_and_the_early_release_rule(monkeypatch, tmp_path, capsys):
    """B の行は打ち切った観測で計算し、再ランダム化検定も同じ観測で。条件(3)で向きが逆なら解放しない。"""
    _table(monkeypatch, tmp_path, [])
    seen = []
    _no_pool(monkeypatch, seen)
    after = {"agentforce-rag": ("③リードのみ", 1), "agentforce-features": ("①対照", 0)}
    before = {"agentforce-rag": ("③リードのみ", 0), "agentforce-features": ("①対照", 0)}
    part = {"agentforce-rag": ("③リードのみ", 0), "agentforce-features": ("①対照", 1)}   # 打ち切ると向きが逆
    cut = {"status": "cut", "label": "事実訂正前で打ち切り（2026-10-24 09:00 より前）", "after": part,
           "obs_full": 4, "days_full": 2, "obs_cut": 2, "days_cut": 1, "at": dt.datetime(2026, 10, 24, 9)}
    summarize.sensitivity_table(after, before, cut=cut)
    out = capsys.readouterr().out
    assert [ln for ln in out.splitlines() if ln.startswith("事実訂正前で打ち切り（")]
    assert part in [a for a, _ in seen], "再ランダム化検定は打ち切った観測で"
    rr = {"n": 2500, "lead_p": 0.001, "faq_p": 0.001}
    with_b = summarize.early_release(after, before, rr, [("両方込み", set())], cut)
    lead = next(r for r in with_b if r["name"].startswith("リード"))
    assert lead["signs"][-1] == ("事実訂正前で打ち切り（2026-10-24 09:00 より前）", -100.0)
    assert lead["did_ok"] and lead["p_ok"] and not lead["signs_ok"] and lead["verdict"] == "解放不可"
    without = summarize.early_release(after, before, rr, [("両方込み", set())])
    assert next(r for r in without if r["name"].startswith("リード"))["verdict"] == "解放可"


def test_a_is_in_the_early_release_rule(monkeypatch, tmp_path):
    g = _by_group()
    _table(monkeypatch, tmp_path, [["", g["①対照"][0], "", "", ""]])
    after = {"agentforce-rag": ("③リードのみ", 1), "agentforce-features": ("①対照", 0)}
    rows = summarize.early_release(after, {}, {"n": 2500, "lead_p": 0.001, "faq_p": 0.001})
    labels = [label for label, _ in rows[0]["signs"]]
    assert labels[-1] == f"事実訂正1本抜き（{g['①対照'][0]}）" and len(labels) == len(summarize.variants())


def test_the_whole_report_shows_the_head_and_both_rows(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "③リードのみ",
                                                               "agentforce-features": "①対照"})
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    _table(monkeypatch, tmp_path, [["E06", "agentforce-rag", "③リードのみ", "9200", "2026-10-20 12:00:00"]])
    rag, feat = "https://cross-com.jp/agentforce-rag/", "https://cross-com.jp/agentforce-features/"
    path = tmp_path / "e.csv"
    head = ["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag", "timestamp"]
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([head,
                                 ["2026-09-18", "E06", "gemini", rag, "0", "", "pool", ""],
                                 ["2026-10-10", "E06", "gemini", rag, "0", "", "pool", "2026-10-10T01:00:00Z"],
                                 ["2026-10-25", "E06", "gemini", rag, "1", "", "pool", "2026-10-25T01:00:00Z"],
                                 ["2026-09-18", "E12", "gemini", feat, "0", "", "pool", ""],
                                 ["2026-10-10", "E12", "gemini", feat, "0", "", "pool", "2026-10-10T01:00:00Z"]])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01", "--csv", str(path),
                    "--model", "gemini"])
    out = capsys.readouterr().out
    assert out.index("## 事実訂正") < out.index("##### gemini"), "冒頭に出す"
    assert "対象 1本：①対照 0本・②FAQのみ 0本・③リードのみ 1本・④両方 0本" in out
    assert "事実訂正1本抜き（E06）" in out and "事実訂正前で打ち切り（2026-10-20 12:00 より前）" in out
    assert "アフター期間の観測 3回（2日）のうち使えるのは 2回（1日）" in out
    section = out.split("## 早期解放の判定")[1]
    assert "事実訂正1本抜き（E06）" in section and "事実訂正前で打ち切り（2026-10-20 12:00 より前）" in section


# --- ドリフト検知：決めた文の変化だけを想定内 --------------------------------------------------------------
_S_BEFORE = "Agentforce を導入した製造業のお客様では、問い合わせ対応が半分になりました。"
_S_AFTER = "Agentforce の導入では、問い合わせ対応を減らせる可能性があります（当社の導入実績ではありません）。"
_S2_BEFORE = "当社が支援した導入企業の多くで定着しています。"
_S2_AFTER = "定着には運用の設計が欠かせません。"


def _drift_tables(monkeypatch, tmp_path, corrections, sentences):
    _table(monkeypatch, tmp_path, corrections)
    path = tmp_path / "fact_correction_sentences.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["E番号", "slug", "修正前", "修正後"]] + sentences)
    monkeypatch.setattr(drift_check, "FACT_SENTENCES", str(path))
    monkeypatch.setattr(drift_check, "EXPECTED_EDITS", str(tmp_path / "none.json"))


def _diff(old, new):
    import difflib
    return list(difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=1))


def _texts(*paras):
    return drift_check.text_of(drift_check.body_of("<article>" + "".join(paras) + "</article>"))


def _ready(monkeypatch, tmp_path, at="2026-10-22 15:00:00"):
    _drift_tables(monkeypatch, tmp_path, [["E06", "a", "③リードのみ", "9300", at]],
                  [["E06", "a", _S_BEFORE, _S_AFTER], ["E06", "a", _S2_BEFORE, _S2_AFTER]])


def test_the_listed_sentences_only_are_expected(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    edits = drift_check.load_fact_correction_edits()
    assert [(e["slug"], e["from"], e["intervention"]) for e in edits] == [("a", "2026-10-22", "事実訂正（E06・リビジョン 9300）")]
    old = _texts("<h2>見出し</h2>", f"<p>前の文。{_S_BEFORE}後の文。</p>", f"<p>{_S2_BEFORE}</p>")
    new = _texts("<h2>見出し</h2>", f"<p>前の文。{_S_AFTER}後の文。</p>", f"<p>{_S2_AFTER}</p>")
    assert drift_check.expected_edit_for("a", _diff(old, new), "2026-10-26", edits, old, new) == edits[0]
    # 何回かに分けて直した週(1文だけ)も想定内
    half = _texts("<h2>見出し</h2>", f"<p>前の文。{_S_AFTER}後の文。</p>", f"<p>{_S2_BEFORE}</p>")
    assert drift_check.expected_edit_for("a", _diff(old, half), "2026-10-26", edits, old, half) == edits[0]
    assert drift_check.expected_edit_for("a", _diff(half, new), "2026-11-02", edits, half, new) == edits[0]


def test_other_changes_are_unexpected(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    edits = drift_check.load_fact_correction_edits()
    old = _texts("<h2>見出し</h2>", f"<p>前の文。{_S_BEFORE}後の文。</p>")
    cases = {
        "同じ段落のほかの文も変わった": _texts("<h2>見出し</h2>", f"<p>前の文を変えた。{_S_AFTER}後の文。</p>"),
        "見出しも変わった": _texts("<h2>見出しを変えた</h2>", f"<p>前の文。{_S_AFTER}後の文。</p>"),
        "決めた文と違う書き換え": _texts("<h2>見出し</h2>", "<p>前の文。別の書き換え。後の文。</p>"),
        "戻した": old,
    }
    for why, new in cases.items():
        assert drift_check.expected_edit_for("a", _diff(old, new), "2026-10-26", edits, old, new) is None, why
    new = _texts("<h2>見出し</h2>", f"<p>前の文。{_S_AFTER}後の文。</p>")
    assert drift_check.expected_edit_for("a", _diff(old, new), "2026-10-21", edits, old, new) is None, "訂正の日より前"
    assert drift_check.expected_edit_for("b", _diff(old, new), "2026-10-26", edits, old, new) is None, "ほかの記事"
    assert drift_check.expected_edit_for("a", _diff(new, old), "2026-10-26", edits, new, old) is None, "修正後→修正前"


def test_an_earlier_planned_fix_and_a_fact_correction_in_the_same_week(monkeypatch, tmp_path):
    """E33 のように段落の修正が決まっている記事に事実訂正が重なっても、合わせた形で確かめる。"""
    _ready(monkeypatch, tmp_path)
    para = {"slug": "a", "from": "2026-10-18", "intervention": "I-91",
            "paragraphs": [{"before": "<p>旧い段落。</p>", "after": "<p>新しい段落。</p>"}]}
    edits = [para] + drift_check.load_fact_correction_edits()
    old = _texts("<p>旧い段落。</p>", f"<p>{_S_BEFORE}</p>")
    new = _texts("<p>新しい段落。</p>", f"<p>{_S_AFTER}</p>")
    hit = drift_check.expected_edit_for("a", _diff(old, new), "2026-10-26", edits, old, new)
    assert hit is not None and hit["intervention"] == "I-91・事実訂正（E06・リビジョン 9300）"


def test_the_weekly_run_lists_it_as_expected_or_notes_the_missing_record(monkeypatch, tmp_path):
    import test_drift_check as t
    _ready(monkeypatch, tmp_path)
    old = {"a": t._entry(f"<h2>見出し</h2><p>{_S_BEFORE}</p>", "2026-10-19")}
    rc, rep = t._run(monkeypatch, tmp_path, {"a": f"<h2>見出し</h2><p>{_S_AFTER}</p>"}, old, None, "2026-10-26")
    assert "本文テキストが変化した記事（想定外）：**0 本" in rep
    assert "| a | 事実訂正（E06・リビジョン 9300） | 2026-10-22 |" in rep
    # 時刻が無い(記録待ち)なら想定外として注記
    _ready(monkeypatch, tmp_path, at="")
    assert drift_check.fact_correction_pending() == {"a"}
    rc, rep = t._run(monkeypatch, tmp_path / "2", {"a": f"<h2>見出し</h2><p>{_S_AFTER}</p>"}, old, None, "2026-10-26")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep
    assert "この記事は事実訂正の対象（fact_corrections.csv）。ただし訂正の時刻か修正前後の文" in rep
