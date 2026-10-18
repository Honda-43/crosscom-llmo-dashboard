"""drift_check の基準の選び方のテスト(2026-09-30).

処置(2026-09-29〜30)の後、最初の週次(10/5)だけは「処置後の基準(9/30 取得)」と比べ、
9/29〜30 の処置による変化を想定内として差分に出さない。翌週からは従来どおり前回と比べる。
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import drift_check  # noqa: E402

OLD_0928 = {"a": {"sha256": "old-a", "checked": "2026-09-28"},
            "b": {"sha256": "old-b", "checked": "2026-09-28"}}
POST_0930 = {"a": {"sha256": "post-a", "checked": "2026-09-30"},
             "b": {"sha256": "post-b", "checked": "2026-09-30"}}
NEW_1005 = {"a": {"sha256": "post-a", "checked": "2026-10-05"},
            "b": {"sha256": "post-b", "checked": "2026-10-05"}}


def test_first_run_after_treatment_uses_post_baseline():
    ref, kind = drift_check.choose_reference(OLD_0928, POST_0930)
    assert kind == "post_treatment"
    assert ref is POST_0930


def test_following_weeks_use_previous_run():
    ref, kind = drift_check.choose_reference(NEW_1005, POST_0930)
    assert kind == "previous"
    assert ref is NEW_1005


def test_mixed_manifest_is_treated_as_after_treatment():
    # 1本でも処置の後に取った基準があれば、取り直しは済んでいる
    mixed = {"a": {"sha256": "x", "checked": "2026-09-28"}, "b": {"sha256": "y", "checked": "2026-10-05"}}
    assert drift_check.choose_reference(mixed, POST_0930)[1] == "previous"


def test_without_post_baseline_falls_back_to_previous():
    assert drift_check.choose_reference(OLD_0928, {})[1] == "previous"


def test_first_ever_run_has_no_reference():
    assert drift_check.choose_reference({}, POST_0930) == ({}, "previous")


def test_treatment_end_is_sept_30():
    assert drift_check.TREATMENT_END == "2026-09-30"


def _run(monkeypatch, tmp_path, pages, old, post, today):
    """main() をネットワークなしで回す。(戻り値, 変化の報告ファイルの中身 or None)"""
    snap, pdir = tmp_path / "snap", tmp_path / "post"
    (pdir / "snapshots").mkdir(parents=True)
    snap.mkdir()
    man, pman = tmp_path / "manifest.json", pdir / "manifest.json"
    man.write_text(json.dumps(old), encoding="utf-8")
    for s, v in old.items():
        (snap / f"{s}.txt").write_text(v["text"], encoding="utf-8")
    if post:
        pman.write_text(json.dumps(post), encoding="utf-8")
        for s, v in post.items():
            (pdir / "snapshots" / f"{s}.txt").write_text(v["text"], encoding="utf-8")
    monkeypatch.setattr(drift_check, "SNAP_DIR", str(snap))
    monkeypatch.setattr(drift_check, "MANIFEST", str(man))
    monkeypatch.setattr(drift_check, "POST_MANIFEST", str(pman))
    monkeypatch.setattr(drift_check, "POST_SNAP_DIR", str(pdir / "snapshots"))
    monkeypatch.setattr(drift_check, "targets", lambda: [(s, f"https://x/{s}/") for s in pages])
    monkeypatch.setattr(drift_check, "fetch", lambda url: f"<article>{pages[url.rstrip('/').split('/')[-1]]}</article>")

    class _D(drift_check.datetime.date):
        @classmethod
        def today(cls):
            return drift_check.datetime.date.fromisoformat(today)
    monkeypatch.setattr(drift_check.datetime, "date", _D)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["drift_check.py", "--sleep", "0", "--out-dir", str(out)])
    rc = drift_check.main()
    reps = list(out.glob("experiment47_drift_*.md")) if out.exists() else []
    return rc, (reps[0].read_text(encoding="utf-8") if reps else None)


def _entry(body, checked):
    import hashlib
    b = drift_check.body_of(f"<article>{body}</article>")
    return {"sha256": hashlib.sha256(b.encode()).hexdigest(), "checked": checked,
            "text": drift_check.text_of(b)}


def test_oct5_treatment_change_is_expected_no_report(monkeypatch, tmp_path):
    # 9/28: 処置前 → 9/30: 処置後（D-39 が足された）→ 10/5: 処置後のまま
    old = {"a": _entry("<p>本文</p>", "2026-09-28")}
    post = {"a": _entry("<div>要約</div><p>本文</p>", "2026-09-30")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": "<div>要約</div><p>本文</p>"}, old, post, "2026-10-05")
    assert rc == 0 and rep is None


def test_oct5_change_after_treatment_is_reported(monkeypatch, tmp_path):
    old = {"a": _entry("<p>本文</p>", "2026-09-28")}
    post = {"a": _entry("<div>要約</div><p>本文</p>", "2026-09-30")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": "<div>要約</div><p>本文が変わった</p>"}, old, post, "2026-10-05")
    assert rep is not None
    assert "処置後の基準" in rep and "本文が変わった" in rep


def test_reading_time_is_not_part_of_the_hash():
    # 2026-09-21 の回：本文が同じでも「読了時間」が 11分→6分 と動き、47本すべてが変化ありになった
    rt = ('<span class="span-reading-time rt-reading-time" style="display: block;">'
          '<span class="rt-label rt-prefix">読了時間</span> <span class="rt-time"> {}</span> '
          '<span class="rt-label rt-postfix">分</span></span>')
    a = drift_check.body_of(f"<article>{rt.format(11)}<p>本文</p></article>")
    b = drift_check.body_of(f"<article>{rt.format(6)}<p>本文</p></article>")
    assert a == b and "読了時間" not in a


def test_markup_only_change_is_listed_separately(monkeypatch, tmp_path):
    old = {"a": _entry("<p>本文</p>", "2026-10-05")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": '<p class="x">本文</p>'}, old, None, "2026-10-12")
    assert rep is not None
    assert "本文テキストが変化した記事（想定外）：**0 本" in rep
    assert "HTMLのみの変化（本文テキストは同一・要確認）：1 本" in rep


def test_markup_diff_points_at_the_changed_fragment():
    d = drift_check.markup_diff('<p class="a">本文</p>', '<p class="abcdefgh">本文</p>')
    assert d and "abcdefgh" in d[0]


# 2026-10-09 19:42 の著者表示の変更（I-31・I-32）。46本の公開ページで実際に出た差分の形
_OLD_BOX = ("<p>この記事を書いた人</p><p>本田正憲</p><p>" + sorted(drift_check.AUTHOR_REMOVED, key=len)[-1] + "</p>"
            "<p>https://note.com/honda_crosscom</p><p>記事一覧へ</p>")
_NEW_TOP = "<p>著者：</p><p>本田正憲</p><p>合同会社クロスコム 代表／Salesforce認定コンサルタント</p>"
_NEW_BIO = [x for x in drift_check.AUTHOR_ADDED if x.startswith("双日")][0]
_NEW_BOX = (f"<p>この記事を書いた人</p><p>本田正憲</p><p>合同会社クロスコム 代表／Salesforce認定コンサルタント</p>"
            f"<p>{_NEW_BIO}</p><p>プロフィールを見る →</p>")


def test_author_display_change_is_expected(monkeypatch, tmp_path):
    old = {"a": _entry(f"<p>事例紹介</p><p>本文</p>{_OLD_BOX}", "2026-10-05")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": f"<p>事例紹介</p>{_NEW_TOP}<p>本文</p>{_NEW_BOX}"},
                   old, None, "2026-10-12")
    assert rep is not None
    assert "本文テキストが変化した記事（想定外）：**0 本" in rep
    assert "想定内の変化（著者表示の変更 I-31・I-32 の行だけ）：1 本" in rep


def test_author_change_plus_body_change_is_unexpected(monkeypatch, tmp_path):
    old = {"a": _entry(f"<p>本文</p>{_OLD_BOX}", "2026-10-05")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": f"{_NEW_TOP}<p>本文が変わった</p>{_NEW_BOX}"}, old, None, "2026-10-12")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep and "本文が変わった" in rep


def test_rewritten_author_bio_is_unexpected(monkeypatch, tmp_path):
    old = {"a": _entry(f"<p>本文</p>{_OLD_BOX}", "2026-10-05")}
    box = _NEW_BOX.replace(_NEW_BIO, "紹介文を書き換えた")
    rc, rep = _run(monkeypatch, tmp_path, {"a": f"{_NEW_TOP}<p>本文</p>{box}"}, old, None, "2026-10-12")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep


def test_author_rule_does_not_apply_before_oct9():
    diff = ["--- a", "+++ b", "+著者：", "+本田正憲"]
    assert not drift_check.author_only_change(diff, "2026-10-08")
    assert drift_check.author_only_change(diff, "2026-10-09")
    assert not drift_check.author_only_change(["--- a", "+++ b"], "2026-10-12")


# 2026-10-18：実験期間中に誤情報を直す1本（pool.MISINFO_FIX_SLUGS）。決めた段落だけの変化は想定内
_FIX_BEFORE = "<p>防災設備メーカーA社では、商談化率が<strong>32%</strong>向上し、受注が1.8倍になった。</p>"
_FIX_AFTER = ("<p>※以下は架空の事例です。</p><p>防災設備メーカーを想定した例では、商談化率が"
              "<strong>2〜3割程度</strong>向上し、受注が1.5〜2倍程度になるケースが考えられる。</p>")
_FIX = {"slug": "a", "from": "2026-10-20", "intervention": "I-91", "before": _FIX_BEFORE, "after": _FIX_AFTER}


def _with_fix(monkeypatch, tmp_path, edits=(_FIX,)):
    path = tmp_path / "expected_edits.json"
    path.write_text(json.dumps(list(edits), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(drift_check, "EXPECTED_EDITS", str(path))


def test_the_planned_fix_of_one_paragraph_is_expected(monkeypatch, tmp_path):
    _with_fix(monkeypatch, tmp_path)
    old = {"a": _entry(f"<h2>見出し</h2>{_FIX_BEFORE}<p>本文</p>", "2026-10-19")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": f"<h2>見出し</h2>{_FIX_AFTER}<p>本文</p>"}, old, None, "2026-10-26")
    assert rep is not None
    assert "本文テキストが変化した記事（想定外）：**0 本" in rep
    assert "想定内の変化（実験期間中に入れると決めた修正の段落だけ）：1 本" in rep
    assert "| a | I-91 | 2026-10-20 |" in rep


def test_a_change_outside_the_paragraph_is_unexpected(monkeypatch, tmp_path):
    _with_fix(monkeypatch, tmp_path)
    old = {"a": _entry(f"<h2>見出し</h2>{_FIX_BEFORE}<p>本文</p>", "2026-10-19")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": f"<h2>見出しを変えた</h2>{_FIX_AFTER}<p>本文</p>"},
                   old, None, "2026-10-26")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep
    assert "決めた段落の外も変わっている" in rep and "見出しを変えた" in rep


def test_a_different_rewrite_of_the_paragraph_is_unexpected(monkeypatch, tmp_path):
    _with_fix(monkeypatch, tmp_path)
    old = {"a": _entry(f"{_FIX_BEFORE}<p>本文</p>", "2026-10-19")}
    rc, rep = _run(monkeypatch, tmp_path, {"a": "<p>防災設備の段落を別の文に書き換えた</p><p>本文</p>"},
                   old, None, "2026-10-26")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep


def test_the_rule_is_only_for_that_article_and_from_that_day(monkeypatch, tmp_path):
    diff = ["--- a", "+++ b", "-" + drift_check.text_of(_FIX_BEFORE).split("\n")[0], "+※以下は架空の事例です。"]
    assert drift_check.expected_edit_for("a", diff, "2026-10-20", [_FIX]) == _FIX
    assert drift_check.expected_edit_for("a", diff, "2026-10-19", [_FIX]) is None, "適用日より前"
    assert drift_check.expected_edit_for("b", diff, "2026-10-26", [_FIX]) is None, "ほかの記事"
    assert drift_check.expected_edit_for("a", ["--- a", "+++ b", "-防災設備メーカーA社では、商談化率が"],
                                         "2026-10-26", [_FIX]) is None, "消えただけ(足された行なし)"
    # 戻した(修正後→修正前)のも想定外
    back = ["--- a", "+++ b", "-※以下は架空の事例です。", "+防災設備メーカーA社では、商談化率が"]
    assert drift_check.expected_edit_for("a", back, "2026-10-26", [_FIX]) is None


def test_other_articles_are_unaffected_by_the_fix_rule(monkeypatch, tmp_path):
    _with_fix(monkeypatch, tmp_path)
    old = {"b": _entry(f"{_FIX_BEFORE}", "2026-10-19")}
    rc, rep = _run(monkeypatch, tmp_path, {"b": _FIX_AFTER}, old, None, "2026-10-26")
    assert "本文テキストが変化した記事（想定外）：**1 本" in rep
