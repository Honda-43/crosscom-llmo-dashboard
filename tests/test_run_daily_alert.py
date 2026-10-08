"""日次観測の欠測が必ず Slack に届くことの配線テスト(2026-09-21 の調査を受けて).

9/15〜9/21 の llm_observations が3日分しかない件を調べた際、「日次が欠測した日に
Slack が鳴るか」を確かめた。鳴る — run_daily が欠測を failures に積み、
notify_slack がそれを「❌ パイプライン一部失敗」として投稿し、exit 1 で
ワークフローの失敗通知も出る。ただしこの経路を通しで確かめるテストが無かった
ので、ここで固定する。部品(missing_observations / build_message)のテストは
別にあるが、run_daily がその2つをつなぎ忘れても落ちない。

外部(LLM・Sheets・GA4・GSC)はすべて差し替える。
"""
import pytest

import collect_gsc
import collect_ga4
import collect_llm
import extract
import notify_slack
import run_daily
import sheets_writer

GEMINI_503 = "503 UNAVAILABLE. {'error': {'code': 503, 'status': 'UNAVAILABLE'}}"
OBSERVATION_DAY = "2026-09-22"      # 火(日次の観測日)
QUIET_DAY = "2026-09-23"            # 水(観測しない日)
PROMPT_IDS = ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3", "E-1")
MODELS = ("gemini", "claude")


def _record(prompt_id, model, error=None):
    return {"date": OBSERVATION_DAY, "prompt_id": prompt_id, "pillar": "A", "category": "",
            "target_brand": "", "model": model, "model_name": model, "question": "Q",
            "cep": None, "timestamp": "2026-09-21T23:00:00Z",
            "answer": None if error else "答え", "cited_urls": [], "error": error}


@pytest.fixture
def wired(monkeypatch):
    posted = {}

    def fake_notify(date, extractions=(), changes=(), failures=(), **kwargs):
        posted["date"] = date
        posted["failures"] = list(failures)
        posted["text"] = notify_slack.build_message(
            date, extractions, changes, failures, warnings=kwargs.get("warnings", ()))
        return True

    monkeypatch.setattr(notify_slack, "notify", fake_notify)
    monkeypatch.setattr(extract, "extract_record", lambda record: dict(record))
    monkeypatch.setattr(collect_ga4, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect_pages", lambda: [])
    # 本物のシートには絶対に行かない
    monkeypatch.setattr(sheets_writer, "_open_spreadsheet",
                        lambda: (_ for _ in ()).throw(RuntimeError("no sheets in tests")))
    monkeypatch.setattr(run_daily, "_job_summary", lambda lines: None)
    # 欠測の母数(7本×有効モデル)を環境変数に左右されないよう固定する
    monkeypatch.setattr(collect_llm, "enabled_models", lambda: list(MODELS))
    return posted


def _run(monkeypatch, date, records):
    monkeypatch.setattr(collect_llm, "collect", lambda d, **kw: records)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", date])
    with pytest.raises(SystemExit) as exited:
        run_daily.main()
    return exited.value.code


@pytest.fixture
def sheets_ok(monkeypatch):
    """シートの読み書きを何もしない形にする(終了コードを欠測の扱いだけで見るため)。"""
    for name in dir(sheets_writer):
        if name.startswith("read_"):
            monkeypatch.setattr(sheets_writer, name, lambda *a, **k: [])
        elif name.startswith("write_"):
            monkeypatch.setattr(sheets_writer, name, lambda *a, **k: None)


def test_a_single_503_miss_is_a_warning_not_a_failure(wired, sheets_ok, monkeypatch):
    """2026-10-08:日次は7本しかないので、503 由来の欠測1件は警告だけ(exit 0)。件数と理由は Slack に出す。"""
    records = [_record(pid, model, error=GEMINI_503 if (pid, model) == ("A-2", "gemini") else None)
               for pid in PROMPT_IDS for model in MODELS]
    code = _run(monkeypatch, OBSERVATION_DAY, records)
    assert code == 0, "一時的な混雑1件では失敗にしない"
    assert not any("欠測" in f for f in wired["failures"])
    assert "collect_llm(欠測 1件): 503(混雑) 1件(A-2/gemini)" in wired["text"], "サマリ行には出す"


def test_two_503_misses_fail_the_run(wired, sheets_ok, monkeypatch):
    bad = {("A-2", "gemini"), ("B-1", "gemini")}
    records = [_record(pid, model, error=GEMINI_503 if (pid, model) in bad else None)
               for pid in PROMPT_IDS for model in MODELS]
    assert _run(monkeypatch, OBSERVATION_DAY, records) == 1
    assert any(f.startswith("collect_llm(欠測 2件): 503(混雑) 2件") for f in wired["failures"])
    assert "❌ パイプライン一部失敗" in wired["text"]


def test_misses_that_are_all_429_are_a_warning(wired, sheets_ok, monkeypatch):
    quota = "429 RESOURCE_EXHAUSTED. quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
    bad = {("A-2", "gemini"), ("B-1", "gemini"), ("E-1", "gemini")}
    records = [_record(pid, model, error=quota if (pid, model) in bad else None)
               for pid in PROMPT_IDS for model in MODELS]
    assert _run(monkeypatch, OBSERVATION_DAY, records) == 0
    assert "429(枠切れ) 3件" in wired["text"]


def test_an_auth_error_or_a_missing_observation_fails_the_run(wired, sheets_ok, monkeypatch):
    auth = "401 UNAUTHENTICATED API key not valid"
    records = [_record(pid, model, error=auth if (pid, model) == ("A-1", "gemini") else None)
               for pid in PROMPT_IDS for model in MODELS]
    assert _run(monkeypatch, OBSERVATION_DAY, records) == 1
    assert any("認証・権限など 1件" in f for f in wired["failures"])
    # 観測そのものが無い(collect が途中で落ちた・モデルが飛ばされた)も失敗
    records = [_record(pid, model) for pid in PROMPT_IDS[:-1] for model in MODELS]
    assert _run(monkeypatch, OBSERVATION_DAY, records) == 1
    assert any("観測そのものが無い 2件" in f for f in wired["failures"])


def test_a_quiet_day_does_not_observe_so_it_cannot_miss(wired, monkeypatch):
    """水曜は日次の観測日ではない。collect を呼ばないので欠測も起こらない。"""
    called = []
    monkeypatch.setattr(collect_llm, "collect", lambda d, **kw: called.append(d) or [])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", QUIET_DAY])
    with pytest.raises(SystemExit):
        run_daily.main()
    assert not called
    assert not any("欠測" in f for f in wired.get("failures", []))


def test_a_model_skipped_without_a_record_still_counts_as_missing(wired, monkeypatch):
    """鍵が無いと collect は record を作らずにそのモデルを飛ばす。7件の欠測として鳴らす。"""
    records = [_record(pid, "claude") for pid in PROMPT_IDS]
    code = _run(monkeypatch, OBSERVATION_DAY, records)
    assert code == 1
    assert any(f.startswith("collect_llm(欠測 7件)") and "E-1/gemini" in f
               for f in wired["failures"]), wired["failures"]


def test_a_crashed_collect_counts_every_observation_as_missing(wired, monkeypatch):
    """collect 自体が例外で落ちると records は空。14件すべてを欠測として鳴らす。"""
    def boom(date):
        raise RuntimeError("collect crashed")

    monkeypatch.setattr(collect_llm, "collect", boom)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", OBSERVATION_DAY])
    with pytest.raises(SystemExit) as exited:
        run_daily.main()
    assert exited.value.code == 1
    assert any(f.startswith("collect_llm(欠測 14件)") for f in wired["failures"]), wired["failures"]
    assert "collect_llm(欠測 14件)" in wired["text"]


def test_a_complete_observation_day_reports_no_missing(wired, monkeypatch):
    records = [_record(pid, model) for pid in PROMPT_IDS for model in MODELS]
    _run(monkeypatch, OBSERVATION_DAY, records)
    assert not any("欠測" in f for f in wired["failures"])


# --- 前日の実行漏れ(ワークフロー未実行)の検知 --------------------------------------
def _obs(date, n):
    return [{"date": date, "prompt_id": f"P{i}", "model": "gemini"} for i in range(n)]


def test_a_missing_summary_row_for_yesterday_is_flagged():
    gaps = run_daily.previous_day_gaps("2026-09-22", [{"date": "2026-09-20"}], [], 14)
    assert len(gaps) == 1 and "2026-09-21" in gaps[0] and "daily_summary" in gaps[0]


def test_a_short_observation_day_yesterday_is_flagged():
    """前日が火・木・土なら llm_observations が14件あるはず。"""
    gaps = run_daily.previous_day_gaps("2026-09-23", [{"date": "2026-09-22"}],
                                       _obs("2026-09-22", 10), 14)
    assert len(gaps) == 1 and "10件" in gaps[0] and "期待14件" in gaps[0]


def test_yesterday_without_observations_is_fine_when_it_was_not_an_observation_day():
    """月曜は観測しない日。llm_observations が0件でも正常。"""
    assert run_daily.previous_day_gaps("2026-09-22", [{"date": "2026-09-21"}], [], 14) == []


def test_a_complete_yesterday_raises_nothing():
    assert run_daily.previous_day_gaps("2026-09-23", [{"date": "2026-09-22"}],
                                       _obs("2026-09-22", 14), 14) == []


def test_the_gap_warning_reaches_slack_even_on_a_quiet_day(wired, monkeypatch):
    monkeypatch.setattr(sheets_writer, "read_daily_summary", lambda: [{"date": "2026-09-21"}])
    monkeypatch.setattr(sheets_writer, "read_llm_observations",
                        lambda: _obs("2026-09-22", 3))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", QUIET_DAY])   # 水
    with pytest.raises(SystemExit):
        run_daily.main()
    assert "⚠️ 前日(2026-09-22・火)の llm_observations が3件です(期待14件)" in wired["text"]


def test_an_unreadable_sheet_does_not_invent_a_gap(wired, monkeypatch):
    """シートが読めない日は「0件」と誤報しない(読めなかったことは失敗として出る)。"""
    monkeypatch.setattr(sheets_writer, "read_daily_summary", lambda: [{"date": "2026-09-22"}])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", QUIET_DAY])
    with pytest.raises(SystemExit):
        run_daily.main()
    assert "llm_observations が0件" not in wired.get("text", "")
