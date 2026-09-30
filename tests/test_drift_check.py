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
