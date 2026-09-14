"""LLMO効果測定実験のテスト(2026-09-14).

固定したいのは4つ:

1. 47本の質問文が本田さんの貼った CSV から一文字も変わっていないこと。
   文言が変わるとビフォーとアフターが比較できない。
2. 曜日割りで Gemini の1日20リクエストを超えないこと(日次・月次と合算)。
3. 判定(cited_domain / cited_article / mentioned)が URL の表記ゆれに強く、
   欠測を 0 と書かないこと。
4. 日次・月次のタブやスキーマを汚さないこと。
"""
import datetime as dt
import hashlib

import pytest
import yaml

import collect_llm
import experiment
import run_experiment
import settings
import sheets_writer

PROMPTS = settings.load_experiment_prompts()

# 2026-09-14 に貼られた CSV の「id\t質問文」を改行でつないだ SHA-256。
# CSV を1文字でも書き換えるとここで落ちる(意図しない編集の検知)。
PROMPTS_SHA256 = "4f7b306cbf7a947f3f6cc6e0b7ca8d7d9a27b15358e28307e26b215e9c63ea2c"


# --- 1. 質問文 ----------------------------------------------------------------
def test_the_prompts_are_unchanged_from_the_pasted_csv():
    joined = "\n".join(f"{p['id']}\t{p['prompt']}" for p in PROMPTS)
    assert hashlib.sha256(joined.encode("utf-8")).hexdigest() == PROMPTS_SHA256


def test_spot_check_the_wording():
    by_id = {p["id"]: p["text"] for p in PROMPTS}
    assert by_id["E01"] == ("Agentforce for SalesのSDRエージェントとSales Coachは"
                            "営業でどう使う？活用事例も知りたい")
    assert by_id["E47"] == ("提案書のレビューが遅くて商談が止まる。"
                            "営業部門でレビュー待ちを減らす仕組みの作り方は？")


def test_the_loader_passes_the_prompt_through_untouched():
    """collect_llm に渡す text は CSV の prompt 列そのもの(strip もしない)。"""
    assert all(p["text"] == p["prompt"] for p in PROMPTS)


def test_there_are_47_prompts_in_order_with_unique_articles():
    assert [p["id"] for p in PROMPTS] == [f"E{i:02d}" for i in range(1, 48)]
    urls = [p["url"] for p in PROMPTS]
    assert len(set(urls)) == 47
    assert all(u.startswith("https://cross-com.jp/") and u.endswith("/") for u in urls)
    layers = [p["layer"] for p in PROMPTS]
    assert (layers.count("古"), layers.count("中"), layers.count("新")) == (14, 17, 16)


# --- 2. 曜日割りと Gemini の枠 -------------------------------------------------
WEEK = [dt.date(2026, 9, 14) + dt.timedelta(days=i) for i in range(7)]  # 月〜日


def test_gemini_observes_every_prompt_twice_a_week():
    seen = []
    for day in WEEK:
        seen += [p["id"] for p in settings.experiment_plan(day.isoformat()).get("gemini", [])]
    assert sorted(seen) == sorted([f"E{i:02d}" for i in range(1, 48)] * 2)


def test_the_two_gemini_observations_of_a_prompt_are_three_or_four_days_apart():
    """同じ質問の2回が隣り合う日に寄ると、週の中の変動を拾えない。"""
    weekdays = {}
    for day in WEEK:
        for p in settings.experiment_plan(day.isoformat()).get("gemini", []):
            weekdays.setdefault(p["id"], []).append(day.weekday())
    for pid, days in weekdays.items():
        first, second = sorted(days)
        gap = second - first
        assert {gap, 7 - gap} == {3, 4}, (pid, days)


def test_claude_observes_all_47_on_monday_and_thursday_only():
    for day in WEEK:
        claude = settings.experiment_plan(day.isoformat()).get("claude", [])
        expected = 47 if day.weekday() in (0, 3) else 0
        assert len(claude) == expected, day


def test_daily_llm_days_are_tuesday_thursday_saturday():
    assert [d.weekday() for d in WEEK if settings.is_daily_llm_day(d.isoformat())] == [1, 3, 5]


def _days(start, end):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


@pytest.mark.parametrize("day", list(_days(dt.date(2026, 9, 1), dt.date(2026, 12, 31))),
                         ids=str)
def test_no_day_plans_more_than_the_gemini_limit(day):
    """計画本数(日次 + 月次 + 実験)は毎日20以内で、最低1本は余りを残す。"""
    budget = settings.gemini_requests_on(day.isoformat())
    assert budget["total"] <= 20 and budget["spare"] >= 1, budget
    assert budget["experiment"] <= budget["experiment_budget"], budget


def test_the_tightest_days_are_the_first_week_wednesday_and_thursday():
    # 第1水: 実験13 + 月次A 6 = 19 / 第1木: 実験5 + 日次7 + 月次B 6 = 18
    assert settings.gemini_requests_on("2026-10-07")["total"] == 19
    assert settings.gemini_requests_on("2026-10-01")["total"] == 18
    # 通常の週はどの日も18以下
    assert max(settings.gemini_requests_on(d.isoformat())["total"] for d in WEEK) == 18


def test_gemini_retries_stay_within_the_days_spare(monkeypatch, tmp_path):
    """余りが2本なら、失敗が5件あっても取り直しは2回まで。"""
    calls = []

    def still_failing(record, question, attempts, on_daily_quota=None):
        calls.append(record["prompt_id"])
        record["error"] = "503 UNAVAILABLE"
        return False

    monkeypatch.setattr(collect_llm, "_attempt", still_failing)
    monkeypatch.setattr(collect_llm, "_save", lambda record, out_dir: None)
    records = [_record(prompt_id=p["id"], model="gemini", error="503 UNAVAILABLE")
               for p in PROMPTS[:5]]
    by_id = {p["id"]: p for p in PROMPTS[:5]}
    used = run_experiment.retry_within_budget(records, by_id, tmp_path, budget=2, cooldown=0)
    assert used == 2 and len(calls) == 2


def test_gemini_retries_stop_at_the_daily_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_llm, "_save", lambda record, out_dir: None)
    records = [_record(prompt_id="E01", model="gemini",
                       error="429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel")]
    used = run_experiment.retry_within_budget(records, {"E01": PROMPTS[0]}, tmp_path,
                                              budget=5, cooldown=0)
    assert used == 0


def test_collect_can_run_without_inline_retries_or_sweep(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def boom(text, model):
        calls.append(text)
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", boom)
    got = collect_llm.collect("2026-09-15", prompts=PROMPTS[:2], out_dir=tmp_path,
                              models=["gemini"], attempts=1, sweep=False)
    assert len(calls) == 2 and all(r["error"] for r in got)


# --- 3. 判定 --------------------------------------------------------------------
TARGET = {"id": "E06", "layer": "古", "url": "https://cross-com.jp/agentforce-rag/"}


def _record(**kw):
    base = {"prompt_id": "E06", "model": "claude", "answer": "", "cited_urls": [],
            "error": None}
    base.update(kw)
    return base


def test_the_article_matches_despite_www_slash_query_and_fragment():
    rec = _record(cited_urls=["https://www.cross-com.jp/agentforce-rag?utm=x#faq"])
    got = experiment.evaluate(rec, TARGET)
    assert (got["cited_domain"], got["cited_article"]) == (1, 1)
    assert got["cited_domains"] == ["cross-com.jp"]


def test_another_article_on_our_domain_is_a_domain_hit_only():
    rec = _record(cited_urls=["https://cross-com.jp/agentforce-guide/",
                              "https://www.salesforce.com/jp/agentforce/"])
    got = experiment.evaluate(rec, TARGET)
    assert (got["cited_domain"], got["cited_article"]) == (1, 0)
    assert got["cited_domains"] == ["cross-com.jp", "salesforce.com"]


def test_a_lookalike_domain_is_not_ours():
    rec = _record(cited_urls=["https://notcross-com.jp/agentforce-rag/"])
    assert experiment.evaluate(rec, TARGET)["cited_domain"] == 0


def test_mentioned_looks_for_the_company_name_in_the_answer():
    assert experiment.evaluate(_record(answer="合同会社クロスコムの記事では"), TARGET)["mentioned"] == 1
    assert experiment.evaluate(_record(answer="Salesforceの公式では"), TARGET)["mentioned"] == 0


def test_gemini_redirects_are_resolved_before_matching():
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    lost = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/zzz"
    rec = _record(model="gemini", cited_urls=[redirect, lost])
    resolved = {redirect: "https://cross-com.jp/agentforce-rag/", lost: None}
    got = experiment.evaluate(rec, TARGET, resolver=resolved.get)
    assert got["cited_article"] == 1
    assert got["unresolved_redirects"] == 1
    assert all("vertexaisearch" not in u for u in got["resolved_urls"])


def test_a_missing_observation_is_blank_not_zero():
    got = experiment.evaluate(_record(error="429 RESOURCE_EXHAUSTED PerDay"), TARGET)
    assert got["cited_domain"] == got["cited_article"] == got["mentioned"] == ""


# --- 4. 収集・保存 -------------------------------------------------------------
def test_collect_runs_only_the_requested_model(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    calls = []

    def fake(name):
        return lambda text, model: (calls.append(name) or ("答え", []))

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", fake("gemini"))
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "claude", fake("claude"))
    got = collect_llm.collect("2026-09-14", prompts=PROMPTS[:2], out_dir=tmp_path,
                              models=["claude"])
    assert set(calls) == {"claude"} and len(got) == 2


def test_observe_flags_a_model_that_could_not_run(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_llm, "collect", lambda *a, **k: [])
    failures = []
    plan = settings.experiment_plan("2026-09-14")          # 月曜: gemini 12 / claude 47
    run_experiment.observe("2026-09-14", plan, tmp_path, failures)
    assert len(failures) == 2


def test_observe_adds_the_experiment_columns(monkeypatch, tmp_path):
    def fake_collect(date, prompts, out_dir, models, **kwargs):
        return [_record(prompt_id=p["id"], model=models[0], date=date,
                        question=p["text"], answer="クロスコム",
                        cited_urls=[p["url"]]) for p in prompts]

    monkeypatch.setattr(collect_llm, "collect", fake_collect)
    monkeypatch.setattr(collect_llm, "_save", lambda record, out_dir: None)
    failures = []
    plan = {"claude": PROMPTS[:3]}
    records = run_experiment.observe("2026-09-17", plan, tmp_path, failures)
    assert not failures
    assert [(r["experiment_id"], r["cited_article"], r["mentioned"]) for r in records] == [
        ("E01", 1, 1), ("E02", 1, 1), ("E03", 1, 1)]


def test_the_experiment_tab_has_the_requested_columns_and_keys_first():
    for column in ("experiment_id", "cited_domain", "cited_article", "mentioned",
                   "cited_domains", "answer_text"):
        assert column in sheets_writer.HEADERS_EXPERIMENT
    assert sheets_writer.HEADERS_EXPERIMENT[:3] == sheets_writer.KEYS_EXPERIMENT


def test_the_experiment_row_guards_formulas_and_long_answers():
    rec = dict(experiment.evaluate(_record(answer="- 箇条書きで始まる回答"), TARGET),
               date="2026-09-14", model="claude", question="Q")
    row = sheets_writer._experiment_row(rec)
    assert row["answer_text"] == "'- 箇条書きで始まる回答"
    long = dict(rec, answer_text="あ" * (sheets_writer.CELL_CHAR_LIMIT + 10))
    assert len(sheets_writer._experiment_row(long)["answer_text"]) < 50_000


def test_the_experiment_tab_is_separate_from_the_dashboard_tabs():
    assert settings.TAB_EXPERIMENT == "llm_experiment"
    assert settings.TAB_EXPERIMENT not in sheets_writer.LOOKER_TABS
    assert settings.TAB_EXPERIMENT not in (settings.TAB_LLM, settings.TAB_MONTHLY)


def test_the_experiment_workflow_runs_on_the_observation_weekdays():
    doc = yaml.safe_load((settings.ROOT_DIR / ".github" / "workflows" / "experiment.yml")
                         .read_text(encoding="utf-8"))
    triggers = doc.get(True) or doc.get("on")
    # Gemini が毎日あるので毎日走らせる(23:00 UTC = 翌 08:00 JST)
    assert triggers["schedule"] == [{"cron": "0 23 * * *"}]
    needed = set(settings.EXPERIMENT_GEMINI_GROUPS) | set(settings.EXPERIMENT_CLAUDE_WEEKDAYS)
    assert needed == set(range(7))
