"""抽出と週次所見の Gemini への移行のテスト(2026-10-06).

Claude を計画的に停止したため、抽出(extract.py)と週次所見(generate_insight)を Gemini に移した。
- 観測(gemini-2.5-flash)と別のモデルにする(無料枠の1日の上限はモデルごと。429 の quotaDimensions が model 単位)
- 抽出は JSON だけを返させる。1日の枠を使い切ったら「抽出保留」にして後日まとめて抽出する
- Claude の計画的停止とは無関係に動く(抽出・所見は Claude を呼ばない)
"""
import json
import sys
import types

import pytest

import claude_budget
import extract
import generate_insight
import settings

OBSERVATION_MODEL = "gemini-2.5-flash"
ANSWER = {"date": "2026-10-08", "prompt_id": "A-1", "pillar": "A", "model": "gemini",
          "question": "Q", "answer": "合同会社クロスコムがおすすめです", "cited_urls": [],
          "raw_file": "data/raw/2026-10-08/A-1_gemini.json"}
GOOD_JSON = json.dumps({"mention": True, "mention_type": "recommended_list", "rank": 1,
                        "kbf_tags": ["定着支援"], "negative_or_outdated": False, "negative_detail": None,
                        "cited_crosscom_urls": [], "all_cited_urls": [], "competitors_mentioned": []},
                       ensure_ascii=False)


def _fake_genai(monkeypatch, replies, seen):
    from google.genai import types as gtypes

    class Models:
        def generate_content(self, **kw):
            seen.append(kw)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            text, reason = reply if isinstance(reply, tuple) else (reply, "STOP")
            cand = types.SimpleNamespace(finish_reason=types.SimpleNamespace(name=reason))
            return types.SimpleNamespace(text=text, candidates=[cand])

    class Client:
        def __init__(self, api_key=None, http_options=None):
            self.models = Models()

    genai = types.SimpleNamespace(Client=Client, types=gtypes)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(sys.modules["google"], "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(extract, "GEMINI_EXTRACT_MIN_INTERVAL_SECONDS", 0)


def test_the_extraction_and_insight_models_are_gemini_and_not_the_observation_model():
    assert settings.EXTRACT_MODEL == "gemini-3.5-flash-lite"
    assert settings.INSIGHT_MODEL == "gemini-3.5-flash"
    assert OBSERVATION_MODEL == settings.MODEL_CONFIG["gemini"]["model"]
    assert len({settings.EXTRACT_MODEL, settings.INSIGHT_MODEL, OBSERVATION_MODEL}) == 3, \
        "観測の1日20回の枠を使わないよう、別のモデルにする"
    assert extract.provider_of(settings.EXTRACT_MODEL) == "gemini"


def test_gemini_extraction_returns_the_same_schema_and_never_calls_claude(monkeypatch):
    seen = []
    _fake_genai(monkeypatch, [GOOD_JSON], seen)
    monkeypatch.setattr(claude_budget, "guard", lambda label="": pytest.fail("Claude を通らない"))
    got = extract.extract_record(ANSWER)
    assert got["error"] is None and got["mention"] is True and got["rank"] == 1
    assert seen[0]["model"] == settings.EXTRACT_MODEL
    assert seen[0]["config"].response_mime_type == "application/json"
    assert not getattr(seen[0]["config"], "tools", None), "抽出に検索は使わない"


def test_a_broken_json_reply_is_retried_once(monkeypatch):
    seen = []
    _fake_genai(monkeypatch, ["{ 壊れた", GOOD_JSON], seen)
    assert extract.extract_record(ANSWER)["error"] is None and len(seen) == 2


def test_a_daily_quota_429_makes_the_extraction_pending(monkeypatch):
    seen = []
    err = Exception("429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    _fake_genai(monkeypatch, [err], seen)
    got = extract.extract_record(ANSWER)
    assert extract.is_pending(got) and "gemini_daily_quota" in got["error"] and len(seen) == 1


def test_a_per_minute_429_waits_and_retries(monkeypatch):
    seen, slept = [], []
    err = Exception("429 RESOURCE_EXHAUSTED. PerMinute ... Please retry in 7.5s.")
    _fake_genai(monkeypatch, [err, GOOD_JSON], seen)
    import time
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    assert extract.extract_record(ANSWER)["error"] is None
    assert slept and 8 <= slept[-1] <= 65


def test_the_weekly_insight_is_written_by_gemini_even_while_claude_is_stopped(monkeypatch, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text('planned_stop_from: "2026-10-06"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", cfg)
    seen = []
    _fake_genai(monkeypatch, ["本文"], seen)
    text = generate_insight._call_model("system", "user", settings.INSIGHT_MODEL)
    assert text == "本文" and seen[0]["config"].system_instruction == "system"
    assert seen[0]["model"] == "gemini-3.5-flash"


def test_a_truncated_gemini_insight_raises_like_claude(monkeypatch):
    seen = []
    _fake_genai(monkeypatch, [("途中まで", "MAX_TOKENS")], seen)
    with pytest.raises(generate_insight.TruncatedResponse):
        generate_insight._call_model("s", "u", "gemini-3.5-flash", 100)
