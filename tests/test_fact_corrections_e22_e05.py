"""凍結46本の事実訂正 E22・E05(2026-10-22 準備・効果測定チャットで了承済み・まだ反映していない)。

- agentforce-reasoning-control(E22・③リードのみ)2か所、agentforce-roi(E05・③リードのみ)1か所。
  Agentforce の顧客導入0件(2026-10-20 本田確認)なのに、相談を受けている・顧客と一緒に作業していると言い切る文の訂正。
  序文・見出し・FAQ・リンクは変えない。反映はその日の観測ジョブの後(10:00 JST 以降の見込み)
- 感度分析 A の見出しは「事実訂正2本抜き(E22・E05)」
- 偏りの向きの注記を短期・長期の両方に出す
- 参考の表(反映の前後の Gemini の cited_article・mentioned_v2・観測回数)は 11/2 の短期判定まで出さない
- ドリフト検知：修正前後の文は expected_edits.json の mode=sentences の項目に入れる。時刻は fact_corrections.csv から
記録が届くまで実際の表は空。ここのテストは表を一時ファイルに差し替えて確かめる。
"""
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
sys.path.insert(0, str(ROOT / "tests"))

import drift_check  # noqa: E402
import pool  # noqa: E402
import summarize  # noqa: E402

E22, E05 = "agentforce-reasoning-control", "agentforce-roi"
HEAD = ["E番号", "slug", "組", "リビジョン", "時刻"]
NOTE = ("**E22・E05（ともに③）の本文3か所を事実訂正。③の引用が下がった場合、"
        "リードの効果は小さめ（安全側）、FAQの効果は大きめ（甘い方向）に出る**")
S1 = ("相談を受けている文。", "直した文1。")
S2 = ("顧客と一緒に作業している文。", "直した文2。")
S3 = ("ROI の記事の言い切りの文。", "直した文3。")


def _tables(monkeypatch, tmp_path, at22="2026-10-23 10:30:00", at05="2026-10-23 10:31:00", sentences=True):
    path = tmp_path / "fact_corrections.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HEAD, ["E22", E22, "③リードのみ", "", at22], ["E05", E05, "③リードのみ", "", at05]])
    monkeypatch.setattr(pool, "FACT_CORRECTIONS_CSV", str(path))
    empty = tmp_path / "fact_correction_sentences.csv"
    empty.write_text("E番号,slug,修正前,修正後\n", encoding="utf-8")
    monkeypatch.setattr(drift_check, "FACT_SENTENCES", str(empty))
    edits = [{"slug": "agentforce-sales-roleplay", "from": "2026-10-18", "intervention": "I-41",
              "paragraphs": [{"before": "<p>x</p>", "after": "<p>y</p>"}]}]
    if sentences:
        edits += [{"slug": E22, "mode": "sentences", "intervention": "事実訂正（E22）",
                   "sentences": [{"before": S1[0], "after": S1[1]}, {"before": S2[0], "after": S2[1]}]},
                  {"slug": E05, "mode": "sentences", "intervention": "事実訂正（E05）",
                   "sentences": [{"before": S3[0], "after": S3[1]}]}]
    js = tmp_path / "expected_edits.json"
    js.write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(drift_check, "EXPECTED_EDITS", str(js))


def test_the_real_tables_accept_e22_and_e05():
    groups = pool.load_allocation()
    assert groups[E22] == "③リードのみ" and groups[E05] == "③リードのみ"
    with io.open(pool.FACT_CORRECTIONS_CSV, encoding="utf-8") as f:
        assert next(csv.reader(f)) == HEAD


def test_a_is_named_after_the_two_articles_and_drops_them_from_every_group(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)
    label, ex = summarize.variants()[-1]
    assert (label, ex) == ("事実訂正2本抜き（E22・E05）", {E22, E05})


def test_the_direction_note_is_printed_for_short_and_long(monkeypatch, tmp_path, capsys):
    _tables(monkeypatch, tmp_path)
    for span in (("2026-10-06", "2026-11-01"), ("2026-10-06", "2026-12-27")):
        summarize.print_fact_correction_head(span=span)
        assert NOTE in capsys.readouterr().out, span
    # 反映がアフター期間の後なら、その期間には出さない
    summarize.print_fact_correction_head(span=("2026-10-06", "2026-10-20"))
    assert "を事実訂正" not in capsys.readouterr().out


def test_the_note_says_when_the_time_or_sentences_are_missing(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path, at22="", at05="", sentences=False)
    note = summarize.fact_direction_note(span=("2026-10-06", "2026-11-01"))
    assert note.startswith("**E22・E05（ともに③）の本文の文（箇所の数は記録待ち）を事実訂正（反映の時刻は記録待ち）。")
    _tables(monkeypatch, tmp_path, at22="", at05="")
    assert "本文3か所を事実訂正（反映の時刻は記録待ち）" in summarize.fact_direction_note(span=("2026-10-06", "2026-11-01"))


def test_the_direction_follows_the_group():
    assert summarize.fact_direction("③リードのみ") == ("小さめ（安全側）", "大きめ（甘い方向）")
    assert summarize.fact_direction("②FAQのみ") == ("大きめ（甘い方向）", "小さめ（安全側）")
    assert summarize.fact_direction("④両方") == ("小さめ（安全側）", "小さめ（安全側）")
    assert summarize.fact_direction("①対照") == ("大きめ（甘い方向）", "大きめ（甘い方向）")


def _rows():
    def r(s, date, ts, cited, men, err=""):
        return {"date": date, "model": "gemini", "target_url": f"https://cross-com.jp/{s}/", "cited_article": cited,
                "mentioned_v2": men, "error": err, "experiment_flag": "pool", "timestamp": ts}
    return [r(E22, "2026-10-20", "2026-10-20T00:30:00Z", "1", "1"),
            r(E22, "2026-10-23", "2026-10-23T00:30:00Z", "0", "1"),   # 09:30 JST：反映前
            r(E22, "2026-10-23", "2026-10-23T02:00:00Z", "0", "0"),   # 11:00 JST：反映後
            r(E22, "2026-10-23", "", "1", "1"),                       # 時刻なし・反映の日：どちらにも入れない
            r(E22, "2026-10-26", "", "0", "0"),
            r(E22, "2026-10-27", "2026-10-27T00:30:00Z", "1", "0", err="timeout"),  # 欠測は数えない
            r(E05, "2026-10-21", "2026-10-21T00:30:00Z", "0", "0"),
            {"date": "2026-10-24", "model": "claude", "target_url": f"https://cross-com.jp/{E05}/",
             "cited_article": "1", "mentioned_v2": "1", "error": "", "experiment_flag": "pool", "timestamp": ""}]


def test_the_reference_table_counts_before_and_after(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)
    t = summarize.fact_reference(_rows(), ("2026-10-06", "2026-11-01"), pool.pool_slugs())
    assert [x["slug"] for x in t] == [E22, E05]
    assert t[0]["before"] == {"obs": 2, "cited": 1, "mentioned": 2}
    assert t[0]["after"] == {"obs": 2, "cited": 0, "mentioned": 0}
    assert t[1]["before"] == {"obs": 1, "cited": 0, "mentioned": 0} and t[1]["after"]["obs"] == 0


def test_the_reference_table_is_hidden_until_the_short_judgement(monkeypatch, tmp_path, capsys):
    _tables(monkeypatch, tmp_path)
    span = ("2026-10-06", "2026-11-01")
    assert summarize.print_fact_reference(_rows(), span, today=dt.date(2026, 11, 1)) is None
    out = capsys.readouterr().out
    assert "2026-11-02 の短期判定まで出さない（組ごとの結果を途中で見ないため。③の記事の結果にあたる）" in out
    assert "cited_article" not in out and "回 |" not in out
    assert summarize.print_fact_reference(_rows(), span, today=dt.date(2026, 11, 2))
    out = capsys.readouterr().out
    assert "**2本・数回ずつの観測のため、上下から何かを言える量ではない。**判定には使わない" in out
    assert "| E22 | agentforce-reasoning-control | ③リードのみ | 2026-10-23 10:30 | 2回 | 1回 | 2回 | 2回 | 0回 | 0回 |" in out


def test_the_reference_table_shows_pending_when_the_time_is_missing(monkeypatch, tmp_path, capsys):
    _tables(monkeypatch, tmp_path, at05="")
    summarize.print_fact_reference(_rows(), ("2026-10-06", "2026-11-01"), today=dt.date(2026, 11, 2))
    assert "| E05 | agentforce-roi | ③リードのみ | 記録待ち |" in capsys.readouterr().out


def test_the_reference_table_is_in_the_report_but_hidden_now(monkeypatch, tmp_path, capsys):
    _tables(monkeypatch, tmp_path)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    path = tmp_path / "e.csv"
    head = ["date", "experiment_id", "model", "target_url", "cited_article", "mentioned_v2", "error",
            "experiment_flag", "timestamp"]
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([head] + [[r["date"], "", r["model"], r["target_url"], r["cited_article"],
                                           r["mentioned_v2"], r["error"], r["experiment_flag"], r["timestamp"]]
                                          for r in _rows()])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01", "--csv", str(path),
                    "--model", "gemini"])
    out = capsys.readouterr().out
    assert NOTE in out and summarize.FACT_REFERENCE_HEADING in out
    if dt.date.today() < dt.date(2026, 11, 2):
        assert "2026-11-02 の短期判定まで出さない" in out
    assert "事実訂正2本抜き（E22・E05）" in out


# --- ドリフト検知：expected_edits.json の mode=sentences -----------------------------------------------------
def _texts(*paras):
    return drift_check.text_of(drift_check.body_of("<article>" + "".join(paras) + "</article>"))


def _diff(old, new):
    import difflib
    return list(difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=1))


def test_sentence_entries_take_their_date_from_the_corrections_table(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path)
    edits = drift_check.load_expected_edits()
    e22 = [e for e in edits if e["slug"] == E22][0]
    assert e22["from"] == "2026-10-23" and len(e22["paragraphs"]) == 2 and e22["update_date_display"]
    assert drift_check.fact_correction_pending() == set()
    old = _texts("<h2>見出し</h2>", f"<p>前。{S1[0]}後。</p>", f"<p>{S2[0]}</p>")
    new = _texts("<h2>見出し</h2>", f"<p>前。{S1[1]}後。</p>", f"<p>{S2[1]}</p>")
    assert drift_check.expected_edit_for(E22, _diff(old, new), "2026-10-26", edits, old, new) == e22
    other = _texts("<h2>見出しを変えた</h2>", f"<p>前。{S1[1]}後。</p>", f"<p>{S2[1]}</p>")
    assert drift_check.expected_edit_for(E22, _diff(old, other), "2026-10-26", edits, old, other) is None


def test_sentence_entries_wait_for_the_time(monkeypatch, tmp_path):
    _tables(monkeypatch, tmp_path, at22="", at05="")
    assert [e["slug"] for e in drift_check.load_expected_edits()] == ["agentforce-sales-roleplay"]
    assert drift_check.fact_correction_pending() == {E22, E05}
    assert len(drift_check.load_expected_edits(keep_pending=True)) == 3


def test_the_real_expected_edits_file_still_loads():
    edits = drift_check.load_expected_edits(keep_pending=True)
    assert edits and edits[0]["slug"] == "agentforce-sales-roleplay"
