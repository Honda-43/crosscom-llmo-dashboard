"""実験期間中に誤情報を直す1本(2026-10-18・本田さん決定・案C)の扱い。

架空事例のうち、Perplexity が当社の実績として誤って紹介した「防災設備」の記事1本だけを直す
(数字のある段落に架空の事例である旨の断りを足し、数字を幅のある表現にする2点のみ)。
- 感度分析に「誤情報修正1本抜き」を足す。早期解放の条件(3)・再ランダム化検定も同じ除外
- 判定レポートの交絡候補一覧に載る(interventions.csv の行・scope=プール46本・touches_pool46=yes)
- 週次のドリフト検知は、その記事のその段落だけの変化を想定内にする(tests/test_drift_check.py)
seo-agent から記録(slug・組・適用日時)が届くまで pool.MISINFO_FIX_SLUGS は空。ここのテストは届く前も後も通る。
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import drift_check  # noqa: E402
import pillar  # noqa: E402
import pool  # noqa: E402
import summarize  # noqa: E402

LABEL = "誤情報修正1本抜き"


def _existing_sets():
    multi = pool.multi_paragraph_slugs()
    linked = pillar.linked_articles()
    return [set(pool.late_appended_slugs()), set(pool.APPLIED_CORRECTION_SLUGS),
            set(multi[0]) if multi else set(), set(linked or ()), set(pool.LINK_LOSS_SLUGS)]


def _outside_every_set():
    """既存の感度分析のどの行にも入っていない記事(試しに「直す1本」にする)。"""
    used = set().union(*_existing_sets())
    return sorted(s for s in pool.load_allocation() if s not in used)[0]


def _fix(monkeypatch, s, eid="E99"):
    monkeypatch.setattr(summarize, "MISINFO_FIX_SLUGS", (s,))
    monkeypatch.setattr(summarize, "MISINFO_FIX_IDS", (eid,))


def test_the_record_and_the_paragraph_file_agree():
    """pool の1本・記事ID・drift/expected_edits.json は同じ記事を指す(記録が届く前はどれも空)。"""
    assert len(pool.MISINFO_FIX_SLUGS) == len(pool.MISINFO_FIX_IDS) <= 1
    alloc = pool.load_allocation()
    assert set(pool.MISINFO_FIX_SLUGS) <= set(alloc)
    import csv
    import io
    with io.open(pool.ALLOCATION_CSV, encoding="utf-8") as fh:
        ids = {pool.slug(r["url"]): r["id"] for r in csv.DictReader(fh)}
    assert tuple(ids[s] for s in pool.MISINFO_FIX_SLUGS) == pool.MISINFO_FIX_IDS
    assert {e["slug"] for e in drift_check.load_expected_edits()} == set(pool.MISINFO_FIX_SLUGS)


def test_before_the_record_the_variant_is_not_shown_and_the_table_says_why(monkeypatch, capsys):
    monkeypatch.setattr(summarize, "MISINFO_FIX_SLUGS", ())
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): None)
    assert not any(LABEL in label for label, _ in summarize.variants())
    summarize.sensitivity_table({"agentforce-rag": ("①対照", 0)}, {})
    assert "「誤情報修正1本抜き」は出していない：seo-agent からの記録（slug・組・適用日時）待ち" in capsys.readouterr().out


def test_the_variant_drops_only_that_article_and_is_last(monkeypatch):
    monkeypatch.setattr(summarize, "MISINFO_FIX_SLUGS", ())
    before = summarize.variants()
    s = _outside_every_set()
    _fix(monkeypatch, s)
    after = summarize.variants()
    assert after[:-1] == before, "既存の行(番号・中身)は変えない"
    assert after[-1] == ("誤情報修正1本抜き（E99）", {s})
    over = summarize.misinfo_fix_overlap()
    assert [label for label, _ in over] == ["9本（9/15〜16 追記）", "features（訂正対象）", "複数段落回答",
                                            "ピラーの既存リンク先", "リンク減2本"]
    assert not any(hit for _, hit in over)
    assert summarize.misinfo_fix_note().endswith("既存の感度分析のどの行にも含まれない")


def test_if_the_article_is_features_the_two_rows_are_merged(monkeypatch):
    """1本だけの集合が既存の行と同じになるのは features 抜きだけ。そのときは1行にまとめて注記する。"""
    _fix(monkeypatch, "agentforce-features", "E12")
    rows = summarize.variants()
    sets = [frozenset(e) for _, e in rows]
    assert len(sets) == len(set(sets))
    merged = [label for label, e in rows if e == {"agentforce-features"}]
    assert merged == ["features 抜き（訂正対象）〔誤情報修正1本抜き（E12）と同じ記事集合〕"]
    note = summarize.misinfo_fix_note()
    assert "features（訂正対象）" in note and note.endswith("にも含まれる")


def test_the_overlap_is_reported_when_the_article_is_in_other_rows(monkeypatch):
    s = sorted(pool.LINK_LOSS_SLUGS)[0]          # 9本・複数段落・リンク減2本に含まれる記事
    _fix(monkeypatch, s)
    hits = [label for label, hit in summarize.misinfo_fix_overlap() if hit]
    assert {"9本（9/15〜16 追記）", "リンク減2本"} <= set(hits)
    assert any(LABEL in label for label, _ in summarize.variants())


def test_the_early_release_rule_and_the_randomization_include_the_new_row(monkeypatch):
    s = _outside_every_set()
    _fix(monkeypatch, s)
    seen = []
    monkeypatch.setattr(summarize, "randomization", lambda after, exclude=(): seen.append(set(exclude)) or None)
    after = {s: ("④両方", 1), "agentforce-rag": ("①対照", 0)}
    summarize.sensitivity_table(after, {})
    assert {s} in seen, "再ランダム化検定も同じ除外で"
    rows = summarize.early_release(after, {}, {"n": 2500, "lead_p": 0.001, "faq_p": 0.001})
    labels = [label for label, _ in rows[0]["signs"]]
    assert "誤情報修正1本抜き（E99）" in labels and len(labels) == len(summarize.variants())
    # 条件(3)：この行で向きが逆なら解放しない
    assert all(r["signs"][-1][0] == "誤情報修正1本抜き（E99）" for r in rows)


def test_the_fix_row_is_listed_in_the_confounder_list_with_the_pool46_rows_first():
    import interventions
    def row(raw, iid, scope, touches):
        return {"raw_date": raw, "date": interventions.parse_date(raw), "intervention_id": iid,
                "description": f"{iid} の内容", "scope": scope, "touches_pool46": touches, "ongoing": False}
    rows = [row("2026-10-16", "I-36", "site_structure", "no"),
            row("2026-10-21", "I-91", "プール46本", "yes")]
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1), rows)
    groups = summarize.group_by_scope(overlap)
    assert groups[0][0] == "プール46本" and [r["intervention_id"] for r in groups[0][1]] == ["I-91"]
    # 長期判定(〜12/28)にも載る
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 12, 28), rows)
    assert "I-91" in {r["intervention_id"] for r in overlap}


def test_the_expected_edits_file_is_valid_json_when_present():
    path = Path(drift_check.EXPECTED_EDITS)
    if path.exists():
        edits = json.loads(path.read_text(encoding="utf-8"))
        for e in edits:
            assert {"slug", "from", "intervention"} <= set(e), e
            assert e.get("paragraphs") or ("before" in e and "after" in e), e
            assert all({"before", "after"} <= set(p) for p in e.get("paragraphs", [])), e
            dt.date.fromisoformat(e["from"])


# --- 2026-10-18：seo-agent の記録（148d365）を受けて登録した1本 ------------------------------------------
SLUG, EID = "agentforce-sales-roleplay", "E33"
FIXTURES = ROOT / "tests" / "fixtures"


def _real_row():
    import interventions
    rows = [r for r in interventions.load() if r["intervention_id"] == "I-41"]
    assert len(rows) == 1
    return rows[0]


def test_the_three_places_point_at_the_same_article():
    """pool.py・drift/expected_edits.json・interventions.csv が同じ記事(E33)を指す。"""
    assert pool.MISINFO_FIX_SLUGS == (SLUG,) and pool.MISINFO_FIX_IDS == (EID,)
    assert pool.load_allocation()[SLUG] == "②FAQのみ"
    edits = drift_check.load_expected_edits()
    assert [e["slug"] for e in edits] == [SLUG]
    assert edits[0]["from"] == "2026-10-18" and edits[0]["intervention"] == "I-41"
    assert len(edits[0]["paragraphs"]) == pool.MISINFO_FIX_PARAGRAPHS == 26
    row = _real_row()
    assert str(row["date"]) == "2026-10-18" and row["description"].startswith(f"15:46:09 {SLUG} ")
    assert (row["scope"], row["executor"], row["touches_pool46"]) == ("プール46本", "seo-agent（9d）", "yes")
    assert f"組②FAQのみ（{EID}）" in row["note"] and "本文195段落中26段落のみ変更" in row["note"]
    assert str(summarize.misinfo_fix_date()) == "2026-10-18"


def test_e33_is_in_none_of_the_existing_rows_so_it_is_its_own_row():
    assert not any(hit for _, hit in summarize.misinfo_fix_overlap())
    rows = summarize.variants()
    assert rows[-1] == ("誤情報修正1本抜き（E33）", {SLUG})
    assert summarize.misinfo_fix_note() == "※ 誤情報修正の1本（E33）は既存の感度分析のどの行にも含まれない"


def test_the_report_states_the_direction_of_the_bias_in_both_judgements(capsys):
    text = ("アフター期間中（2026-10-18）に E33（②）の本文26段落を修正。②の引用が下がる場合、リードの効果は大きめ（甘い方向）、"
            "FAQの効果は小さめに出る。リードの早期解放は『誤情報修正1本抜き』でも効果の向きが同じときだけ通る")
    for span in ("2026-10-06:2026-11-01", "2026-10-06:2026-12-28"):      # 短期・長期
        assert summarize.print_misinfo_fix_note(span)
        assert text in capsys.readouterr().out
    assert not summarize.print_misinfo_fix_note("2026-09-15:2026-09-28"), "期間外には出さない"
    assert not summarize.print_misinfo_fix_note("2026-10-06:2026-11-01", []), "記録が無ければ出さない"


def test_the_real_fix_row_is_in_the_confounder_list():
    import interventions
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1), interventions.load())
    groups = summarize.group_by_scope(overlap)
    pool46 = dict(groups)["プール46本"]
    assert "I-41" in [r["intervention_id"] for r in pool46]
    assert [k for k, _ in groups].index("プール46本") < [k for k, _ in groups].index("site_structure")


def _real_diff(after_text):
    import difflib
    before = (FIXTURES / "drift_sales_roleplay_before.txt").read_text(encoding="utf-8").split("\n")
    return list(difflib.unified_diff(before, after_text.split("\n"), lineterm="", n=1))


def test_the_real_published_change_is_expected_by_the_drift_check():
    """seo-agent の公開 HTML の前後(_7174_public_before/after.html を drift_check と同じ形にしたもの)。
    変わったのは26段落と記事の「更新」の日付(2026-09-29 → 2026-10-18)だけ。関連記事の並びは本文から切り落とされている。"""
    after = (FIXTURES / "drift_sales_roleplay_after.txt").read_text(encoding="utf-8")
    edits = drift_check.load_expected_edits()
    diff = _real_diff(after)
    assert "-2026-09-29" in diff and "+2026-10-18" in diff
    assert drift_check.expected_edit_for(SLUG, diff, "2026-10-19", edits) is edits[0]
    assert drift_check.expected_edit_for(SLUG, diff, "2026-10-17", edits) is None, "適用日より前"
    # 26段落以外の行が1行でも変われば想定外
    assert drift_check.expected_edit_for(SLUG, _real_diff(after.replace("目次", "もくじ", 1)), "2026-10-19", edits) is None
    # 更新日が適用日でない日付に変わったのも想定外
    assert drift_check.expected_edit_for(SLUG, _real_diff(after.replace("2026-10-18", "2026-10-25", 1)),
                                         "2026-10-26", edits) is None
    # H3 見出しと FAQ の答えの数字は残す(変えたら想定外)
    assert "41%" in after
