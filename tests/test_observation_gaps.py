"""判定レポートの「観測の欠測」の注記(2026-10-22)。抜けた日の日付と理由が自動で載る。

作り物のデータだけを使う(計画・行・実験日誌をすべて作り物に差し替える。本物の観測は読まない)。
"""
import csv
import datetime as dt
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import summarize  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
PLAN = {"2026-10-20": ["E01", "E02", "E03"], "2026-10-21": ["E04", "E05"], "2026-10-22": ["E06", "E07"],
        "2026-10-23": ["E08"], "2026-10-24": ["E09"]}
TODAY = dt.date(2026, 10, 24)
Q429 = "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED'}}"
U503 = "503 UNAVAILABLE. {'error': {'code': 503, 'status': 'UNAVAILABLE'}}"


def _plan(date):
    return PLAN.get(date, [])


def _row(date, eid, error="", model="gemini"):
    return {"date": date, "experiment_id": eid, "model": model, "error": error,
            "target_url": f"https://cross-com.jp/x-{eid}/", "experiment_flag": "pool", "cited_article": "0"}


ROWS = [_row("2026-10-20", "E01"), _row("2026-10-20", "E02", Q429), _row("2026-10-20", "E03", U503),
        # 10/21:E04 は答えあり。E05 は日誌だけ(シートに書く前にジョブが止まった)
        _row("2026-10-21", "E04"),
        # 10/22:行も日誌も無い(ジョブが動かなかった)。Claude の行は数えない
        _row("2026-10-22", "E06", model="claude"),
        _row("2026-10-23", "E08", "skipped: 日次・月次の実消費15回で枠が足りず実行せず")]
JOURNAL = [{"date": "2026-10-21", "experiment_id": "E05", "model": "gemini", "reason": "skipped",
            "detail": "job_timeout: 2026-10-21 の実験ジョブが Gemini の応答待ちで止まった。ほか"},
           {"date": "2026-10-20", "experiment_id": "E03", "model": "gemini", "reason": "unavailable", "detail": U503}]


def test_gaps_list_the_dates_and_reasons():
    gaps = summarize.observation_gaps(ROWS, [("2026-10-20", "2026-10-31")], JOURNAL, _plan, TODAY)
    assert gaps == [
        ("2026-10-20", 3, 1, {"枠切れ（429）": 1, "一時的な混雑・時間切れ（503）": 1}),
        ("2026-10-21", 2, 1, {"投げなかった（job_timeout：2026-10-21 の実験ジョブが Gemini の応答待ちで止まった）": 1}),
        ("2026-10-22", 2, 0, {summarize.GAP_NO_RECORD: 2}),
        ("2026-10-23", 1, 0, {"投げなかった（日次・月次の実消費15回で枠が足りず実行せず）": 1}),
    ], "今日(10/24)の分は含めない"


def test_a_retaken_observation_is_not_a_gap():
    rows = ROWS + [_row("2026-10-20", "E02"), _row("2026-10-20", "E03")]   # あとで取り直せた
    gaps = summarize.observation_gaps(rows, [("2026-10-20", "2026-10-20")], JOURNAL, _plan, TODAY)
    assert gaps == []


def test_reason_labels():
    assert summarize.gap_reason("quota") == "枠切れ（429）"
    assert summarize.gap_reason("skipped", "time_budget: 40分を超えた") == "投げなかった（時間の予算切れ）"
    assert summarize.gap_reason("permanent") == "認証・権限・課金のエラー"
    assert summarize.gap_reason("", "") == "理由不明"


def test_the_note_is_printed_without_groups(capsys):
    summarize.print_observation_gaps(ROWS, [("2026-10-20", "2026-10-31")], JOURNAL, _plan, TODAY)
    out = capsys.readouterr().out
    assert f"### {summarize.GAP_HEADING}" in out
    assert "欠測のある日 4日・欠測 6本" in out
    assert "- 2026-10-20：計画 3本・観測 1本・欠測 2本（枠切れ（429） 1本・一時的な混雑・時間切れ（503） 1本）" in out
    assert f"- 2026-10-22：計画 2本・観測 0本・欠測 2本（{summarize.GAP_NO_RECORD} 2本）" in out
    assert not any(g in out for g in summarize.GROUP_ORDER)


def test_no_gaps(capsys):
    rows = [_row(d, e) for d, ids in PLAN.items() for e in ids]
    summarize.print_observation_gaps(rows, [("2026-10-20", "2026-10-31")], [], _plan, TODAY)
    assert "計画に対する欠測は無い" in capsys.readouterr().out


def test_the_report_carries_the_note_before_11_02(monkeypatch, tmp_path, capsys):
    """判定レポート(main)に自動で載る。11/2 より前の本物のデータ扱いでも出る(組を含まないため)。"""
    head = ["date", "experiment_id", "model", "target_url", "cited_article", "mentioned_v2", "error",
            "experiment_flag", "timestamp"]
    path, journal = tmp_path / "e.csv", tmp_path / "journal.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, head, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(ROWS)
    with io.open(journal, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["date", "experiment_id", "model", "reason", "detail", "attempts"], restval="")
        w.writeheader()
        w.writerows(JOURNAL)
    monkeypatch.setattr(summarize, "_default_plan", _plan)
    monkeypatch.setattr(summarize, "is_synthetic", lambda p: False)
    monkeypatch.setattr(summarize, "_now_jst", lambda: dt.datetime(2026, 10, 24, 9, 0, tzinfo=JST))
    assert summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01",
                           "--model", "gemini", "--csv", str(path), "--journal", str(journal)]) == 0
    out = capsys.readouterr().out
    assert summarize.BLIND_MESSAGE in out
    assert f"### {summarize.GAP_HEADING}" in out and "- 2026-10-21：計画 2本・観測 1本・欠測 1本（投げなかった（job_timeout" in out


def test_days_before_the_current_plan_rules_count_only_recorded_misses():
    """9/22 より前(9/19〜9/21)は本数の決まりが今と違うので、記録のある欠測だけを数える。9/19 より前は数えない。"""
    rows = [_row("2026-09-18", "E01", Q429),
            _row("2026-09-20", "E01"), _row("2026-09-20", "E02", Q429),
            _row("2026-09-22", "E03")]
    plan = {"2026-09-20": ["E01", "E02", "E09", "E10"], "2026-09-22": ["E03", "E04"]}.get
    gaps = summarize.observation_gaps(rows, [("2026-09-15", "2026-09-28")], [], lambda d: plan(d, []), TODAY)
    assert gaps == [("2026-09-20", 2, 1, {"枠切れ（429）": 1}),
                    ("2026-09-22", 2, 1, {summarize.GAP_NO_RECORD: 1})]


def test_the_footer_is_formatted(capsys):
    summarize.print_observation_gaps([], [("2026-10-20", "2026-10-20")], [], _plan, TODAY)
    out = capsys.readouterr().out
    assert "{" not in out and "2026-09-19 より前" in out and "2026-09-22 より前" in out
