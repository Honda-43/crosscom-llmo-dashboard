"""Gemini の1分あたり上限への対処のテスト(2026-10-08).

gemini-2.5-flash の無料枠は1分5回。観測の呼び出しの間を13秒以上空け、1分あたりの 429 は待って取り直す
(取り直しもその日の枠に数える)。1日あたりの 429 は従来どおり取り直さない。
"""
import collect_llm
import settings

MINUTE_429 = ("429 RESOURCE_EXHAUSTED. quotaId: 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
              "quotaValue: '5' ... Please retry in 7.5s.")
DAY_429 = "429 RESOURCE_EXHAUSTED. quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', quotaValue: '20'"


def test_minute_and_day_429_are_told_apart():
    assert collect_llm.is_minute_quota(Exception(MINUTE_429))
    assert not collect_llm.is_minute_quota(Exception(DAY_429)) and collect_llm.is_daily_quota(Exception(DAY_429))
    assert not collect_llm.is_minute_quota(Exception("429 RESOURCE_EXHAUSTED")), "どちらか書かれていなければ取り直さない側"
    assert settings.GEMINI_MIN_INTERVAL_SECONDS == 13


def _clock(monkeypatch):
    now = [1000.0]
    slept = []
    monkeypatch.setattr(collect_llm.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(collect_llm.time, "time", lambda: now[0])

    def sleep(s):
        slept.append(s)
        now[0] += s
    monkeypatch.setattr(collect_llm.time, "sleep", sleep)
    return now, slept


def test_gemini_calls_are_spaced_by_13_seconds(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_llm, "GEMINI_MIN_INTERVAL_SECONDS", 13.0)
    now, _ = _clock(monkeypatch)
    collect_llm.note_gemini_call(0.0)
    called = []
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", lambda t, m: called.append(now[0]) or ("答え", []))
    collect_llm.collect("2026-10-12", prompts=[{"id": f"E{i:02d}", "text": "Q"} for i in range(1, 7)],
                        out_dir=tmp_path, models=["gemini"])
    gaps = [b - a for a, b in zip(called, called[1:])]
    assert len(called) == 6 and min(gaps) >= 13, gaps
    assert sum(1 for t in called if t - called[0] < 60) <= 5, "1分に5回を超えない"


def test_a_minute_429_is_retried_after_waiting_and_counts_against_the_budget(monkeypatch, tmp_path):
    now, slept = _clock(monkeypatch)
    replies = [Exception(MINUTE_429), ("答え", [])]

    def query(t, m):
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", query)
    budget = collect_llm.RetryBudget(2)
    recs = collect_llm.collect("2026-10-12", prompts=[{"id": "E01", "text": "Q"}], out_dir=tmp_path,
                               models=["gemini"], budget=budget)
    assert recs[0]["answer"] == "答え" and recs[0]["attempts"] == 2
    assert any(8 <= s <= 65 for s in slept), "retryDelay(7.5秒)+1秒以上待つ"
    assert budget.remaining == 1, "取り直しはその日の枠の余りから引く"


def test_a_day_429_is_still_not_retried(monkeypatch, tmp_path):
    _clock(monkeypatch)
    calls = []
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini",
                        lambda t, m: calls.append(1) or (_ for _ in ()).throw(Exception(DAY_429)))
    recs = collect_llm.collect("2026-10-12", prompts=[{"id": "E01", "text": "Q"}, {"id": "E02", "text": "Q"}],
                               out_dir=tmp_path, models=["gemini"], sweep=False)
    assert len(calls) == 2 and all(r["attempts"] == 1 for r in recs), "1日あたりは取り直さない"
