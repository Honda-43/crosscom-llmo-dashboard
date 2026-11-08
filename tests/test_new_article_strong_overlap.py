"""便VK(2026-11-08)の15行と、感度分析「新記事の強の重なり抜き」(2026-11-08 事前登録)。

1. I-56〜I-70 を原文のまま追記(ID だけ埋める)。scope に URL が入っていた行は site_content にし、URL は note の先頭へ
2. 新記事5本の note は「実験用プロンプトとの重なり：seo-agent が確認中（要確認）」→ 横取りの欄では要確認
3. アフター期間に公開された新記事のうち重なりが「強」の記事の E番号を、判定期間の全体(全組)から抜く。強0本なら「該当なし」で計算しない
4. 長期判定の感度分析の1行。variants() に入れない(早期解放の条件に使わない)
5. 横取りの欄に公開日と強・弱の E番号
判定の出力を確かめるテストは作り物の観測だけを使う(本物の観測は読まない)。
"""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import interventions  # noqa: E402
import pool  # noqa: E402
import summarize  # noqa: E402

SPAN = ("2026-10-06", "2026-12-27")
PENDING = "実験用プロンプトとの重なり：seo-agent が確認中（要確認）"
NEW = ["solution-sales-ai", "business-design-implementation-support", "it-consulting-agentforce",
       "building-materials-sales-ai", "sales-ai-case-study"]
CTA = ["sales-back-office", "agentforce-japanese", "salesforce-partner", "agentforce-similar-deals",
       "agentforce-delivery-answer", "ai-agent-implementation-support", "agentforce-pricing", "agentforce-support-company"]


def _row(iid, date, note, scope="new_article"):
    return {"intervention_id": iid, "date": dt.date.fromisoformat(date), "raw_date": date, "ongoing": False,
            "description": f"新記事公開：x-{iid}", "scope": scope, "executor": "seo-agent（abcd1234）",
            "touches_pool46": "no", "note": note}


def _eid():
    return {a["id"]: a["slug"] for a in summarize.load_pool()}


def _after():
    """作り物の観測(全46本・引用は E番号の偶奇で決めた値)。"""
    alloc = pool.load_allocation()
    return {s: (g, i % 2) for i, (s, g) in enumerate(sorted(alloc.items()))}


def _no_pool(monkeypatch, seen):
    def fake(after, exclude=()):
        seen.append(set(exclude))
        return None
    monkeypatch.setattr(summarize, "randomization", fake)


# --- 記録 -----------------------------------------------------------------------------------------------
def test_the_15_rows_are_appended():
    rows = {r["intervention_id"]: r for r in interventions.load()}
    ids = [f"I-{n}" for n in range(56, 71)]
    assert all(i in rows for i in ids) and "I-55" in rows and "I-53" in rows, "既存の行は残っている"
    for i, slug in zip(ids[:5], NEW):
        r = rows[i]
        assert (r["raw_date"], r["scope"], r["executor"], r["touches_pool46"]) == (
            "2026-11-08", "new_article", "seo-agent（a2846ad4）", "no")
        assert f"https://cross-com.jp/{slug}/。目次・記事内CTA（上下）" in r["description"]
        assert r["note"].startswith("本田さん OK（2026-11-08 便VK：アイキャッチ5本・図6枚）。凍結46本・編集保留の外。")
        assert r["note"].endswith("保留14本へのリンクは構成案の計画どおり（注意・止めない）。" + PENDING)
        assert summarize.new_article_overlap(r) == ("unknown", [], [])
    for i, slug in zip(ids[5:13], CTA):
        r = rows[i]
        assert r["scope"] == "site_content" and r["touches_pool46"] == "no"
        assert r["note"].startswith(f"対象：https://cross-com.jp/{slug}/。本田さん OK（2026-11-08 便VK 2）。")
        assert "記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した" in r["description"]
    assert rows["I-69"]["note"].startswith("対象：https://cross-com.jp/it-consulting-agentforce/。本田さん OK（2026-11-08 便VK 2・3）。")
    assert rows["I-70"]["note"] == ("対象：https://cross-com.jp/building-materials-sales-ai/。"
                                    "本田さん OK（2026-11-08 便VK 3）。apply_gate NG0・リンクと見出しの数は不変")


def test_the_15_rows_are_confounder_candidates(capsys):
    summarize.print_site_wide_interventions("2026-09-15:2026-09-28", "2026-10-06:2026-12-27")
    out = capsys.readouterr().out
    for n in range(56, 71):
        assert f"｜I-{n}｜" in out, n
    assert out.count("｜scope=new_article｜touches_pool46=no") >= 6, "I-53 と新記事5本"


def test_poaching_lists_publish_dates_and_pending_overlap(capsys):
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 12, 27))
    summarize.print_new_article_poaching(overlap, blind=False, groups={})
    out = capsys.readouterr().out
    assert "重なりが要確認 5本（I-56・I-57・I-58・I-59・I-60）" in out
    for n, slug in zip(range(56, 61), NEW):
        assert f"- I-{n} {slug}（公開 2026-11-08）：要確認" in out
    assert "- I-53 claudeforce（公開 2026-09-23）：強0・弱（E16・E22・E14・E46・E11・E12）" in out


# --- 重なりの読み方 -------------------------------------------------------------------------------------
def test_a_pending_overlap_is_unknown_until_the_result_is_appended():
    f = summarize.new_article_overlap
    assert f({"note": "本文。" + PENDING}) == ("unknown", [], [])
    later = "本文。" + PENDING + "　追記：・実験用プロンプトとの重なり：強：E05・弱：E16（…）"
    assert f({"note": later}) == ("known", ["E05"], ["E16"]), "確認結果の追記(後ろの記載)を読む"
    assert f({"note": "実験用プロンプトとの重なり：強0・弱0"}) == ("known", [], [])


# --- 抜く記事の決め方 -----------------------------------------------------------------------------------
def _rows():
    return [_row("I-90", "2026-11-10", "実験用プロンプトとの重なり：強：E05・弱：E16"),
            _row("I-91", "2026-11-11", "実験用プロンプトとの重なり：強0・弱：E22"),
            _row("I-92", "2026-11-12", PENDING),
            _row("I-93", "2026-09-30", "実験用プロンプトとの重なり：強：E30"),                     # アフター期間の前
            _row("I-94", "2026-11-12", "実験用プロンプトとの重なり：強：E31", scope="site_content")]  # 新記事ではない


def test_only_strong_new_articles_in_the_after_period_are_dropped():
    ex = summarize.new_article_strong_exclusion(SPAN, _rows())
    assert [r["intervention_id"] for r in ex["news"]] == ["I-90", "I-91", "I-92"]
    assert ex["strong"] == ["E05"] and ex["slugs"] == {_eid()["E05"]}
    assert [r["intervention_id"] for r in ex["unknown"]] == ["I-92"]
    assert summarize.new_article_strong_label(ex) == "新記事の強の重なり抜き（E05・全組）"


def test_the_row_drops_the_articles_from_both_periods(monkeypatch, capsys):
    monkeypatch.setattr(interventions, "load", _rows)
    seen = []
    _no_pool(monkeypatch, seen)
    calls = []
    real_tally = summarize.tally
    monkeypatch.setattr(summarize, "tally", lambda a, b, exclude=(): calls.append(set(exclude)) or real_tally(a, b, exclude))
    after = _after()
    before = {s: (g, 0) for s, (g, _) in after.items()}
    summarize.both_ways(after, before, "gemini ", None, SPAN)
    out = capsys.readouterr().out
    slug = _eid()["E05"]
    assert {slug} in seen and {slug} in calls, "ビフォー・アフターとも同じ記事を抜く(tally に除く記事を渡す)"
    line = [ln for ln in out.splitlines() if ln.startswith("新記事の強の重なり抜き（E05・全組）")]
    assert len(line) == 1 and line[0].split()[1] == "45"
    assert ("※ 新記事の強の重なり抜き：アフター期間に公開された新記事 3本（I-90・I-91・I-92）・強の重なり E05"
            "・重なりが要確認 1本（I-92）。長期判定の感度分析の1行で、早期解放の条件・判定の基準には使わない（2026-11-08 事前登録）") in out
    assert "gemini 新記事の強の重なり抜き（E05・全組）" in out, "組別の内訳も出す"


def test_zero_strong_says_none_and_does_not_compute(monkeypatch, capsys):
    monkeypatch.setattr(interventions, "load", lambda: [r for r in _rows() if r["intervention_id"] != "I-90"])
    seen = []
    _no_pool(monkeypatch, seen)
    rows = []
    real = summarize._table_row
    monkeypatch.setattr(summarize, "_table_row", lambda label, *a, **k: rows.append(label) or real(label, *a, **k))
    summarize.sensitivity_table(_after(), {}, span=SPAN)
    out = capsys.readouterr().out
    assert not any(label.startswith(summarize.NEW_ARTICLE_STRONG_LABEL) for label in rows), "計算しない"
    line = [ln for ln in out.splitlines() if ln.startswith(summarize.NEW_ARTICLE_STRONG_LABEL)]
    assert len(line) == 1 and "該当なし（重なり要確認 1本）" in line[0]
    assert "強の重なり 0本" in out


def test_it_is_not_an_early_release_variant_and_not_in_the_probe_table(monkeypatch, capsys):
    monkeypatch.setattr(interventions, "load", _rows)
    _no_pool(monkeypatch, [])
    assert not any(summarize.NEW_ARTICLE_STRONG_LABEL in label for label, _ in summarize.variants())
    summarize.sensitivity_table(_after(), {})
    assert summarize.NEW_ARTICLE_STRONG_LABEL not in capsys.readouterr().out, "期間の無い引用プローブには出さない"
