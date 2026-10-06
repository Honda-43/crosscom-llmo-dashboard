"""Gemini の時間切れと、Claude が止まっても Gemini の観測が続く仕組みのテスト(2026-10-06).

固定したいのは2つ:
1. Gemini の1回の呼び出しは180秒で打ち切り、503 と同じ扱いで取り直す。実験の観測のジョブは1時間で打ち切る
   (日次・月次の完了待ちは別のジョブ)。10/05 は応答待ちで4時間止まり、Claude まで進まなかった
2. Claude が止まった日(クレジット不足・1日の上限)は抽出を「保留」にする。Gemini の回答は保存したまま、
   シートに空の行・言及率 0% を書かない。Claude が使える日にまとめて抽出してシートを直す
"""
import json
import sys
import time
import types

import pytest
import yaml

import claude_budget
import collect_llm
import extract
import extract_pending
import run_experiment
import settings
import sheets_writer


# --- 1. Gemini の時間切れ --------------------------------------------------------------
def test_a_call_that_does_not_return_times_out_as_a_503():
    started = time.monotonic()
    with pytest.raises(collect_llm.GeminiTimeout) as got:
        collect_llm._with_deadline(lambda: time.sleep(3), 0.2)
    assert time.monotonic() - started < 2, "待ち続けない"
    assert str(got.value).startswith("503 UNAVAILABLE")
    assert collect_llm.is_unavailable(got.value), "503 と同じ扱い(取り直す)"
    assert collect_llm.miss_reason(str(got.value)) == collect_llm.REASON_UNAVAILABLE


def test_an_sdk_timeout_is_also_treated_as_a_503():
    class ReadTimeout(Exception):
        pass

    def boom():
        raise ReadTimeout("The read operation timed out")

    with pytest.raises(collect_llm.GeminiTimeout, match="^503 UNAVAILABLE"):
        collect_llm._with_deadline(boom, 1)
    with pytest.raises(ValueError):                          # 時間切れ以外はそのまま上げる
        collect_llm._with_deadline(lambda: (_ for _ in ()).throw(ValueError("bad")), 1)


def test_the_gemini_query_passes_a_180_second_timeout_and_gives_up_on_a_hang(monkeypatch):
    seen = {}

    class Models:
        def generate_content(self, **kw):
            time.sleep(3)                                     # 応答が返らない

    class Client:
        def __init__(self, api_key=None, http_options=None):
            seen["timeout_ms"] = http_options.timeout
            self.models = Models()

    from google.genai import types as gtypes
    genai = types.SimpleNamespace(Client=Client, types=gtypes)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(sys.modules["google"], "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert settings.GEMINI_CALL_TIMEOUT_SECONDS == 180
    monkeypatch.setattr(collect_llm, "GEMINI_CALL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(collect_llm, "DEADLINE_SLACK_SECONDS", 0)
    with pytest.raises(collect_llm.GeminiTimeout):
        collect_llm._query_gemini("質問", "gemini-2.5-flash")
    assert seen["timeout_ms"] == 200, "SDK の HTTP にもミリ秒で時間切れを渡す"


def test_a_timed_out_call_is_retried_like_a_503(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(collect_llm.time, "sleep", lambda s: None)
    calls = []

    def flaky(text, model):
        calls.append(1)
        if len(calls) == 1:
            raise collect_llm.GeminiTimeout("503 UNAVAILABLE (時間切れ): Gemini の応答が 180秒以内に返らなかった")
        return "答え", []

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", flaky)
    recs = collect_llm.collect("2026-10-13", prompts=[{"id": "A-1", "text": "質問"}],
                               out_dir=tmp_path, models=["gemini"])
    assert recs[0]["answer"] == "答え" and recs[0]["attempts"] == 2


def test_the_experiment_job_is_cut_at_one_hour_and_waits_in_its_own_job():
    wf = yaml.safe_load(open(settings.ROOT_DIR / ".github/workflows/experiment.yml", encoding="utf-8"))
    wait, observe = wf["jobs"]["wait"], wf["jobs"]["experiment"]
    assert observe["timeout-minutes"] == 60 and observe["needs"] == "wait"
    assert observe["if"] == "${{ !cancelled() }}", "待ちのジョブが落ちても観測はする"
    assert observe["env"]["EXPERIMENT_DAILY_WAIT_MINUTES"] == "10"
    assert any("--wait-only" in s.get("run", "") for s in wait["steps"])
    assert wait["timeout-minutes"] >= run_experiment.DAILY_WAIT_MINUTES, "日次・月次の待ち(最大90分)が収まる"
    assert not any("GEMINI_API_KEY" in json.dumps(s) or "ANTHROPIC" in json.dumps(s)
                   for s in wait["steps"]) and "env" not in wait, "待ちのジョブは API の鍵を持たない"


def test_wait_only_waits_and_observes_nothing(monkeypatch):
    waited = []
    monkeypatch.setattr(run_experiment, "wait_for_prior_runs", lambda date: waited.append(date) or 15)
    monkeypatch.setattr(run_experiment, "observe", lambda *a, **k: pytest.fail("観測しない"))
    monkeypatch.setattr(claude_budget, "start", lambda *a, **k: pytest.fail("Claude の数え始めもしない"))
    monkeypatch.setattr("sys.argv", ["run_experiment.py", "--wait-only", "--date", "2026-10-13"])  # 火:日次あり
    run_experiment.main()
    assert waited == ["2026-10-13"]
    waited.clear()
    monkeypatch.setattr("sys.argv", ["run_experiment.py", "--wait-only", "--date", "2026-10-14"])  # 水:待たない
    run_experiment.main()
    assert waited == []


# --- 2. 抽出保留 -------------------------------------------------------------------------
def _stop_claude(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "EXTRACT_MODEL", "claude-haiku-4-5-20251001")   # Claude の抽出の経路を確かめる
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "0")
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path / "usage", read_origin=False)
    class NoCall:
        def __init__(self, api_key=None):
            self.messages = self

        def create(self, **kw):
            pytest.fail("止まっている日は Claude を呼ばない")

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=NoCall))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


def _raw(date, pid, model, answer="答え", error=None):
    return {"date": date, "prompt_id": pid, "pillar": "A" if pid.startswith("A") else "B",
            "model": model, "question": "Q", "answer": None if error else answer, "cited_urls": [],
            "error": error, "raw_file": f"data/raw/{date}/{pid}_{model}.json",
            "category": "bofu_single", "target_brand": "X"}


def test_a_stopped_claude_makes_the_extraction_pending_without_calling(monkeypatch, tmp_path):
    _stop_claude(monkeypatch, tmp_path)
    got = extract.extract_record(_raw("2026-10-13", "A-1", "gemini"))
    assert extract.is_pending(got) and got["error"].startswith("extraction_pending: daily_cap")
    assert got["prompt_id"] == "A-1" and got["model"] == "gemini"


def test_pending_is_saved_once_per_observation(tmp_path):
    pending = [dict(_raw("2026-10-13", "A-1", "gemini"), extraction_pending=True, error="extraction_pending: x")]
    assert extract_pending.save("daily", "2026-10-13", pending, root=tmp_path) == 1
    assert extract_pending.save("daily", "2026-10-13", pending, root=tmp_path) == 1, "同じ観測は1件"
    saved = json.loads((tmp_path / "daily_2026-10-13.json").read_text(encoding="utf-8"))
    assert saved["pending"][0]["raw_file"] == "data/raw/2026-10-13/A-1_gemini.json"


class FakeWriter:
    """シートの代わり。書いた行を覚え、llm_observations には先に書いた行を返す。"""

    def __init__(self, stored=(), summary=()):
        self.llm = list(stored)
        self.summary = list(summary)
        self.sov, self.monthly = [], []

    _llm_row = staticmethod(sheets_writer._llm_row)

    def write_llm_observations(self, extractions):
        self.llm += [sheets_writer._llm_row(e) for e in extractions]

    def read_llm_observations(self):
        return [dict(r, mention="TRUE" if r["mention"] is True else
                     "FALSE" if r["mention"] is False else r["mention"]) for r in self.llm]

    def read_daily_summary(self):
        return self.summary

    def write_daily_summary(self, row):
        self.summary = [r for r in self.summary if r["date"] != row["date"]] + [row]

    def write_sov_daily(self, rows):
        self.sov += rows

    def write_monthly_observations(self, extractions):
        self.monthly += extractions


def _pending_day(tmp_path, monkeypatch, kind="daily", date="2026-10-13"):
    raw_dir = tmp_path / "raw"
    for pid in ("A-1", "A-2"):
        (raw_dir / date).mkdir(parents=True, exist_ok=True)
        (raw_dir / date / f"{pid}_gemini.json").write_text(
            json.dumps(_raw(date, pid, "gemini"), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(extract_pending.RAW_DIRS, kind, raw_dir)
    pending = [dict(_raw(date, pid, "gemini"), extraction_pending=True) for pid in ("A-1", "A-2")]
    extract_pending.save(kind, date, pending, root=tmp_path / "ledger")


def test_catch_up_waits_while_claude_is_still_stopped(monkeypatch, tmp_path):
    _pending_day(tmp_path, monkeypatch)
    writer = FakeWriter()
    got = extract_pending.catch_up(writer, root=tmp_path / "ledger",
                                   extractor=lambda r: dict(r, extraction_pending=True, error="extraction_pending: x"))
    assert got == {"done": 0, "left": 2} and writer.llm == [], "まだ止まっていれば何も書かず、台帳は残す"


def test_catch_up_extracts_writes_and_rebuilds_the_days_rates(monkeypatch, tmp_path):
    _pending_day(tmp_path, monkeypatch)
    stored = [sheets_writer._llm_row(dict(_raw("2026-10-13", "B-1", "claude"), error="Error code: 400"))]
    writer = FakeWriter(stored, summary=[{"date": "2026-10-13", "mention_rate_all": "",
                                          "ai_sessions": "5", "branded_clicks": "2"}])

    def extractor(raw):
        return {**{k: raw[k] for k in ("date", "prompt_id", "pillar", "model", "raw_file")},
                "mention": raw["prompt_id"] == "A-1", "mention_type": "none", "rank": None,
                "kbf_tags": [], "negative_or_outdated": False, "negative_detail": None,
                "cited_crosscom_urls": [], "all_cited_urls": [], "competitors_mentioned": ["DCS"],
                "error": None}

    got = extract_pending.catch_up(writer, root=tmp_path / "ledger", extractor=extractor)
    assert got == {"done": 2, "left": 0}
    assert not list((tmp_path / "ledger").glob("*.json")), "抽出し終えた台帳は消す"
    assert {(r["prompt_id"], r["model"]) for r in writer.llm} == {("B-1", "claude"), ("A-1", "gemini"),
                                                                  ("A-2", "gemini")}
    day = writer.summary[0]
    assert day["mention_rate_all"] == 0.5 and day["mention_rate_pillar_a"] == 0.5, "Gemini 2本中1本"
    assert day["ai_sessions"] == "5" and day["negative_flag_count"] == 0, "GA4 などの列は残す"
    assert writer.sov and all(r["date"] == "2026-10-13" for r in writer.sov)


def test_catch_up_of_a_monthly_day_writes_monthly_observations(monkeypatch, tmp_path):
    _pending_day(tmp_path, monkeypatch, kind="monthly", date="2026-11-05")
    writer = FakeWriter()
    got = extract_pending.catch_up(writer, root=tmp_path / "ledger",
                                   extractor=lambda r: {"date": r["date"], "prompt_id": r["prompt_id"],
                                                        "model": r["model"], "mention": True, "error": None})
    assert got["done"] == 2 and writer.llm == []
    assert all(e["category"] == "bofu_single" and e["target_brand"] == "X" for e in writer.monthly)


def test_a_day_without_any_valid_observation_has_no_rate():
    """10/06:抽出がすべて失敗した日を「言及率 0%」と書いていた。有効な観測が無ければ空にする。"""
    rows = [dict(_raw("2026-10-06", "A-1", m), error="extraction_pending: x") for m in ("gemini", "claude")]
    summary = sheets_writer.build_summary(rows, [], [], "2026-10-06")
    assert summary["mention_rate_all"] is None and summary["negative_flag_count"] is None


# --- 日次の実行:Claude が止まっても Gemini の回答は保存され、空の行・0% を書かない ----------------
def test_the_daily_run_keeps_gemini_when_claude_is_stopped(monkeypatch, tmp_path):
    import collect_ga4
    import collect_gsc
    import notify_slack
    import run_daily

    date = "2026-10-13"                                       # 火:日次の観測日
    credit = "Error code: 400 - credit balance is too low"
    records = [_raw(date, pid, "gemini") for pid in ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3", "E-1")]
    records += [_raw(date, pid, "claude", error=credit) for pid in ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3", "E-1")]
    _stop_claude(monkeypatch, tmp_path)
    monkeypatch.setattr(extract_pending, "PENDING_DIR", tmp_path / "ledger")
    monkeypatch.setattr(collect_llm, "collect", lambda d, **kw: records)
    monkeypatch.setattr(collect_llm, "enabled_models", lambda: ["gemini", "claude"])
    monkeypatch.setattr(collect_ga4, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect_pages", lambda: [])
    monkeypatch.setattr(notify_slack, "notify", lambda *a, **k: True)
    monkeypatch.setattr(run_daily, "_job_summary", lambda lines: None)
    monkeypatch.setattr(sheets_writer, "_open_spreadsheet",
                        lambda: (_ for _ in ()).throw(RuntimeError("no sheets in tests")))
    written = {}
    monkeypatch.setattr(sheets_writer, "write_llm_observations",
                        lambda ex: written.setdefault("llm", list(ex)))
    monkeypatch.setattr(sheets_writer, "write_daily_summary",
                        lambda row: written.setdefault("summary", row))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", date])
    with pytest.raises(SystemExit):
        run_daily.main()
    ledger = json.loads((tmp_path / "ledger" / f"daily_{date}.json").read_text(encoding="utf-8"))
    assert {(e["prompt_id"], e["model"]) for e in ledger["pending"]} == {
        (pid, "gemini") for pid in ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3", "E-1")}, "Gemini 7本を保留に残す"
    assert {r["model"] for r in written["llm"]} == {"claude"}, "Gemini の空の行を書かない(Claude の欠測行だけ)"
    assert written["summary"]["mention_rate_all"] is None, "言及率 0% と書かない"
