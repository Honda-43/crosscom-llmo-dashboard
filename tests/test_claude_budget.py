"""Claude API の1日の呼び出し上限とクレジット不足での即停止のテスト(2026-10-03).

本田さんは自動チャージを使わない。固定したいのは4つ:
1. 上限(config/claude_budget.yaml)を超える呼び出しは投げずに止まり、その日の残りは daily_cap になる
2. クレジット不足(400)は再試行せず、その日の Claude 呼び出しをすべて止める
3. 止まったらワークフローの最後の確認が失敗する(Slack に通知が届く)
4. Gemini の観測には一切影響しない
"""
import json
import sys
import types

import pytest
import yaml

import claude_budget
import collect_llm
import extract
import generate_insight
import settings

CREDIT_400 = ("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
              "'message': 'Your credit balance is too low to access the Anthropic API. Please go to "
              "Plans & Billing to upgrade or purchase credits.'}}")


class FakeClient:
    """anthropic.Anthropic の代わり。呼ばれた回数を数え、``fail`` があればそれを上げる。"""
    calls = 0
    fail = None

    def __init__(self, api_key=None):
        self.messages = self

    def create(self, **kw):
        FakeClient.calls += 1
        if FakeClient.fail:
            raise Exception(FakeClient.fail)
        block = types.SimpleNamespace(type="text", text="答え", citations=[])
        return types.SimpleNamespace(content=[block], stop_reason="end_turn", usage=None)


@pytest.fixture
def fake_anthropic(monkeypatch):
    FakeClient.calls, FakeClient.fail = 0, None
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeClient))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    return FakeClient


# --- 上限の決め方 ---------------------------------------------------------------------
def test_the_caps_come_from_the_config_file():
    cfg = yaml.safe_load(open(settings.CONFIG_DIR / "claude_budget.yaml", encoding="utf-8"))
    assert cfg == {"experiment_day": 60, "other_day": 30, "monthly_batch_extra": 25,
                   "marketing_extra": 130}


@pytest.mark.parametrize("date, cap", [
    ("2026-10-12", 60),    # 月:実験の Claude 47本 + 週次所見 + 再試行
    ("2026-10-13", 30),    # 火:日次 7本 + Haiku 14回 + 再試行
    ("2026-10-15", 30),    # 木(10/5 から実験の Claude なし)
    ("2026-11-04", 55),    # 第1水:月次バッチA を足す
    ("2026-11-05", 55),    # 第1木:日次 + 月次バッチB
    ("2027-01-04", 30),    # 実験の観測が終わったあとの月曜
])
def test_the_cap_is_the_days_plan_plus_room_for_retries(date, cap):
    assert claude_budget.cap_for(date) == cap


def test_the_cap_can_be_raised_for_one_run(monkeypatch):
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "80")
    assert claude_budget.cap_for("2026-10-13") == 80


# --- 1. 上限を超えたら止まる --------------------------------------------------------------
def test_calls_over_the_cap_are_not_sent(monkeypatch, tmp_path, fake_anthropic):
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "3")
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    client = FakeClient()
    for _ in range(3):
        claude_budget.create(client, model="m", max_tokens=1, messages=[])
    for _ in range(2):
        with pytest.raises(claude_budget.ClaudeStopped, match="^daily_cap"):
            claude_budget.create(client, model="m", max_tokens=1, messages=[])
    assert FakeClient.calls == 3, "上限を超えた分は投げない"
    saved = json.loads((tmp_path / "2026-10-13" / "daily.json").read_text(encoding="utf-8"))
    assert saved["calls"] == 3 and saved["stopped"] == "daily_cap" and saved["cap"] == 3


def test_other_jobs_calls_that_day_count_toward_the_cap(monkeypatch, tmp_path, fake_anthropic):
    folder = tmp_path / "2026-10-13"
    folder.mkdir()
    (folder / "daily.json").write_text(json.dumps({"calls": 28}), encoding="utf-8")
    claude_budget.start("monthly", "2026-10-13", usage_dir=tmp_path, read_origin=False)   # 上限30
    client = FakeClient()
    claude_budget.create(client, model="m", max_tokens=1, messages=[])
    claude_budget.create(client, model="m", max_tokens=1, messages=[])
    with pytest.raises(claude_budget.ClaudeStopped):
        claude_budget.create(client, model="m", max_tokens=1, messages=[])
    assert FakeClient.calls == 2


def test_a_rerun_of_the_same_job_keeps_counting(monkeypatch, tmp_path, fake_anthropic):
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "2")
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)    # 取り直し
    claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    with pytest.raises(claude_budget.ClaudeStopped):
        claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])


def test_the_rest_of_the_day_is_recorded_as_daily_cap(monkeypatch, tmp_path, fake_anthropic):
    """観測の途中で上限に達したら、残りの観測は投げずに error=daily_cap… として残る。"""
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "2")
    claude_budget.start("experiment", "2026-10-12", usage_dir=tmp_path, read_origin=False)
    prompts = [{"id": f"E{i:02d}", "text": "質問"} for i in range(1, 5)]
    recs = collect_llm.collect("2026-10-12", prompts=prompts, out_dir=tmp_path / "raw",
                               models=["claude"])
    assert [bool(r["error"]) for r in recs] == [False, False, True, True]
    assert all(r["error"].startswith("daily_cap") for r in recs[2:])
    assert all(r["attempts"] == 1 for r in recs[2:]), "止まっている観測は取り直さない"
    assert FakeClient.calls == 2


# --- 2. クレジット不足(400)は再試行せず、その日を止める --------------------------------------
def test_a_credit_400_is_not_retried_and_stops_the_day(monkeypatch, tmp_path, fake_anthropic):
    monkeypatch.setattr(collect_llm.time, "sleep", lambda s: pytest.fail("待って再試行しない"))
    claude_budget.start("experiment", "2026-10-12", usage_dir=tmp_path, read_origin=False)
    FakeClient.fail = CREDIT_400
    prompts = [{"id": f"E{i:02d}", "text": "質問"} for i in range(1, 4)]
    recs = collect_llm.collect("2026-10-12", prompts=prompts, out_dir=tmp_path / "raw",
                               models=["claude"])
    assert FakeClient.calls == 1, "1回目の 400 で止め、再試行も次の観測も投げない(2026-10-01 は50回投げていた)"
    assert "credit balance is too low" in recs[0]["error"]
    assert all(r["error"].startswith("credit_exhausted") for r in recs[1:])
    assert claude_budget.status()["stopped"] == "credit_exhausted"


def test_a_credit_stop_seen_by_an_earlier_job_stops_later_jobs(tmp_path, fake_anthropic):
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    FakeClient.fail = CREDIT_400
    with pytest.raises(Exception, match="credit balance"):
        claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    claude_budget.start("weekly", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    with pytest.raises(claude_budget.ClaudeStopped, match="^credit_exhausted"):
        claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    assert FakeClient.calls == 1


def test_extraction_and_the_weekly_insight_go_through_the_cap(monkeypatch, tmp_path, fake_anthropic):
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    FakeClient.fail = CREDIT_400
    got = extract.extract_record({"prompt_id": "A-1", "model": "gemini", "answer": "本文",
                                  "cited_urls": []})
    assert got["error"].startswith("credit_exhausted"), "2回目の試行は投げずに止まる"
    assert FakeClient.calls == 1
    with pytest.raises(claude_budget.ClaudeStopped):
        generate_insight._call_model("s", "u", "m")
    assert FakeClient.calls == 1


def test_the_haiku_rank_extraction_goes_through_the_cap(monkeypatch, tmp_path, fake_anthropic):
    import marketing
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "0")
    claude_budget.start("marketing_gemini", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    with pytest.raises(claude_budget.ClaudeStopped):
        marketing.list_companies_with_haiku("q", "a")
    assert FakeClient.calls == 0


# --- 3. 止まったらワークフローが失敗する ---------------------------------------------------------
def test_the_check_fails_the_run_when_claude_was_stopped(monkeypatch, tmp_path, fake_anthropic):
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "1")
    claude_budget.start("daily", "2026-10-13", usage_dir=tmp_path, read_origin=False)
    claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    ok, _ = claude_budget.check(["daily"], "2026-10-13", usage_dir=tmp_path)
    assert ok, "上限ちょうどまでは止まっていない"
    with pytest.raises(claude_budget.ClaudeStopped):
        claude_budget.create(FakeClient(), model="m", max_tokens=1, messages=[])
    ok, lines = claude_budget.check(["daily"], "2026-10-13", usage_dir=tmp_path)
    assert not ok and "daily_cap" in lines[0]
    monkeypatch.setattr(claude_budget, "USAGE_DIR", tmp_path)
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    import notify_slack
    monkeypatch.setattr(notify_slack, "_post", lambda text, hook: posted.append(text))
    assert claude_budget.main(["--check", "--job", "daily", "--date", "2026-10-13"]) == 1
    assert posted and "止めました" in posted[0]


def test_the_check_passes_when_the_job_did_not_call_claude(tmp_path):
    ok, lines = claude_budget.check(["experiment"], "2026-10-14", usage_dir=tmp_path)
    assert ok and "呼んでいない" in lines[0]


@pytest.mark.parametrize("name, jobs", [
    ("daily", ["daily"]), ("monthly", ["monthly"]), ("experiment", ["experiment", "marketing_gemini"]),
    ("weekly", ["weekly"]), ("marketing", ["marketing_claude"]),
])
def test_every_workflow_commits_the_counts_and_checks_the_cap(name, jobs):
    wf = yaml.safe_load(open(settings.ROOT_DIR / ".github" / "workflows" / f"{name}.yml", encoding="utf-8"))
    # 観測を記録するジョブ(monthly.yml は曜日の guard ジョブのあとの monthly ジョブ)
    job = next(j for j in wf["jobs"].values()
               if any(s.get("name", "").startswith("Commit") for s in j.get("steps", [])))
    steps = job["steps"]
    names = [s.get("name", "") for s in steps]
    commit = next(i for i, s in enumerate(steps) if s.get("name", "").startswith("Commit"))
    check = names.index("Check Claude daily cap")
    assert "data/claude_usage" in steps[commit]["run"]
    assert check > commit, "記録を commit してから確かめる"
    assert steps[check]["if"] == "always()"
    assert steps[check]["run"] == "python claude_budget.py --check " + " ".join(f"--job {j}" for j in jobs)
    notify = names.index("Notify Slack on workflow failure")
    assert check < notify, "失敗の通知より前に確かめる"


# --- 4. Gemini には影響しない ----------------------------------------------------------------
def test_gemini_never_goes_through_the_claude_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(claude_budget, "guard", lambda label="": pytest.fail("Gemini は数えない"))
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", lambda text, model: ("答え", []))
    recs = collect_llm.collect("2026-10-13", prompts=[{"id": "E01", "text": "質問"}],
                               out_dir=tmp_path, models=["gemini"])
    assert recs[0]["answer"] == "答え" and not recs[0]["error"]


def test_a_stopped_claude_does_not_stop_gemini(monkeypatch, tmp_path, fake_anthropic):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    claude_budget.start("experiment", "2026-10-12", usage_dir=tmp_path, read_origin=False)
    FakeClient.fail = CREDIT_400
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", lambda text, model: ("答え", []))
    prompts = [{"id": f"E{i:02d}", "text": "質問"} for i in range(1, 4)]
    recs = collect_llm.collect("2026-10-12", prompts=prompts, out_dir=tmp_path / "raw",
                               models=["gemini", "claude"])
    gemini = [r for r in recs if r["model"] == "gemini"]
    claude = [r for r in recs if r["model"] == "claude"]
    assert all(r["answer"] == "答え" and not r["error"] for r in gemini), "Gemini は3本とも取れる"
    assert all(r["error"] for r in claude) and FakeClient.calls == 1


def test_the_web_search_and_max_tokens_of_the_observation_are_unchanged():
    """実験の設定(1回の呼び出しの量)は変えない(2026-10-03 確認のみ)。"""
    src = (settings.ROOT_DIR / "src" / "collect_llm.py").read_text(encoding="utf-8")
    assert "max_tokens=2048," in src and '"max_uses": 5' in src
