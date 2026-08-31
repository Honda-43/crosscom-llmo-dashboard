"""収集の再試行・掃き直しのテスト(2026-08-31 の欠測調査を受けて).

直近7日で B-1/B-2/B-3 の gemini が6件欠測していた。原因は provider 側の
一過性の障害(20〜90秒)に対して、待機が 2+4=6秒 しかなかったこと。
3回とも同じ障害窓の中で落ちていた。

ここで固定するのは4つ:
  - provider が retryDelay を返したらそれに従う(固定バックオフより優先)
  - 待っても直らないエラーは1回で止める
  - 1日あたりの枠の 429 は、リトライで枠をさらに食わないよう1回で止める
  - 一巡したあと、失敗した観測だけを1回だけ掃き直す
"""
import pytest

import collect_llm

# 実際に data/raw に記録されていたエラー文面
GEMINI_DAILY_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota... Please retry in 14.44845715s.', 'status': 'RESOURCE_EXHAUSTED', "
    "'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': "
    "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}, "
    "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '14s'}]}}"
)
GEMINI_503 = (
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
    "experiencing high demand. Spikes in demand are usually temporary.', 'status': 'UNAVAILABLE'}}"
)
OPENAI_QUOTA = (
    "Error code: 429 - {'error': {'message': 'You exceeded your current quota, please "
    "check your plan and billing details.', 'type': 'insufficient_quota'}}"
)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """待ち時間を記録するだけにして、テストを実時間で止めない。"""
    slept = []
    monkeypatch.setattr(collect_llm.time, "sleep", slept.append)
    return slept


# --- エラーの分類 -----------------------------------------------------------
def test_the_provider_retry_delay_is_read():
    assert collect_llm.retry_delay(Exception(GEMINI_DAILY_429)) == 14.0


def test_a_retry_delay_is_capped():
    """1回の実行が止まらないよう上限を設ける。"""
    huge = Exception("429 ... 'retryDelay': '3600s'")
    assert collect_llm.retry_delay(huge) == collect_llm.RETRY_DELAY_CAP_SECONDS


def test_an_error_without_a_hint_has_no_delay():
    assert collect_llm.retry_delay(Exception(GEMINI_503)) is None


def test_a_transient_outage_is_retryable():
    exc = Exception(GEMINI_503)
    assert not collect_llm.is_permanent(exc)
    assert not collect_llm.is_daily_quota(exc)


def test_a_billing_problem_is_permanent():
    """insufficient_quota は待っても直らない。2026-07-08 の chatgpt 7件がこれ。"""
    assert collect_llm.is_permanent(Exception(OPENAI_QUOTA))


def test_an_auth_error_is_permanent():
    assert collect_llm.is_permanent(Exception("401 UNAUTHENTICATED: API key not valid"))


def test_the_daily_quota_is_recognised():
    assert collect_llm.is_daily_quota(Exception(GEMINI_DAILY_429))


# --- 待ち時間の決め方 -------------------------------------------------------
def test_the_provider_hint_beats_the_fixed_backoff(no_sleeping):
    """旧実装は2秒待って再試行し、14秒待てと言われているのを無視していた。"""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise Exception("500 internal. 'retryDelay': '30s'")
        return ("ok", [])

    collect_llm._with_retry(flaky, label="t")
    assert no_sleeping == [30.0], "provider の指示に従う"


def test_the_fixed_backoff_is_used_when_there_is_no_hint(no_sleeping):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Exception(GEMINI_503)
        return ("ok", [])

    collect_llm._with_retry(flaky, label="t")
    assert no_sleeping == [collect_llm.BACKOFF_BASE_SECONDS,
                           collect_llm.BACKOFF_BASE_SECONDS * 2]


def test_the_total_wait_spans_the_observed_outage_window():
    """実測した障害窓は20〜90秒。待機の合計がそれを跨げること。"""
    total = sum(collect_llm.BACKOFF_BASE_SECONDS * (2 ** i)
                for i in range(collect_llm.MAX_RETRIES - 1))
    assert total >= 30, f"待機合計 {total}秒 では障害窓を跨げない"


# --- 早く諦める -------------------------------------------------------------
def test_a_permanent_error_is_not_retried(no_sleeping):
    calls = []

    def broken():
        calls.append(1)
        raise Exception(OPENAI_QUOTA)

    with pytest.raises(Exception):
        collect_llm._with_retry(broken, label="t")
    assert len(calls) == 1, "待っても直らないので1回で止める"
    assert no_sleeping == []


def test_the_daily_quota_stops_retrying_and_reports_it(no_sleeping):
    """リトライがその枠をさらに食うため、1回で止めて呼び出し側に知らせる。"""
    calls, flagged = [], []

    def over():
        calls.append(1)
        raise Exception(GEMINI_DAILY_429)

    with pytest.raises(Exception):
        collect_llm._with_retry(over, label="t",
                                on_daily_quota=lambda: flagged.append(True))
    assert len(calls) == 1
    assert flagged == [True]


# --- 掃き直し ---------------------------------------------------------------
PROMPTS = [{"id": "B-2", "text": "質問", "pillar": "B"}]


def _record(error=None):
    return {"date": "2026-08-31", "prompt_id": "B-2", "model": "gemini",
            "model_name": "gemini-2.5-flash", "answer": None, "cited_urls": [],
            "error": error, "timestamp": None}


def test_the_sweep_recovers_a_transient_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini",
                        lambda txt, model: ("回復した回答", []))
    records = [_record(GEMINI_503)]
    assert collect_llm._sweep(records, PROMPTS, tmp_path, cooldown=0) == 1
    assert records[0]["error"] is None
    assert records[0]["answer"] == "回復した回答"


def test_the_sweep_writes_the_recovered_record_to_disk(monkeypatch, tmp_path):
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini",
                        lambda txt, model: ("回復した回答", []))
    collect_llm._sweep([_record(GEMINI_503)], PROMPTS, tmp_path, cooldown=0)
    assert (tmp_path / "B-2_gemini.json").exists()


def test_the_sweep_skips_permanent_failures(monkeypatch, tmp_path):
    called = []
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini",
                        lambda txt, model: called.append(1) or ("x", []))
    assert collect_llm._sweep([_record(OPENAI_QUOTA)], PROMPTS, tmp_path, cooldown=0) == 0
    assert not called, "待っても直らないものは掃き直さない"


def test_the_sweep_does_nothing_when_everything_succeeded(tmp_path):
    assert collect_llm._sweep([_record()], PROMPTS, tmp_path, cooldown=0) == 0


def test_the_sweep_tries_only_once(monkeypatch, tmp_path):
    """回数を重ねると1日あたりの枠の消費が読めなくなる。"""
    calls = []

    def always_down(txt, model):
        calls.append(1)
        raise Exception(GEMINI_503)

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", always_down)
    collect_llm._sweep([_record(GEMINI_503)], PROMPTS, tmp_path, cooldown=0)
    assert len(calls) == 1


# --- 欠測の通知 -------------------------------------------------------------
def test_missing_observations_are_listed():
    records = [_record(), _record(GEMINI_503)]
    assert collect_llm.missing_observations(records) == ["B-2/gemini"]


def test_no_missing_observations_when_all_succeeded():
    assert collect_llm.missing_observations([_record()]) == []
