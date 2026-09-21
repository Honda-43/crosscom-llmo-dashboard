"""LLMO効果測定実験のテスト(2026-09-14).

固定したいのは4つ:

1. 47本の質問文が本田さんの貼った CSV から一文字も変わっていないこと。
   文言が変わるとビフォーとアフターが比較できない。
2. 巡回の割当が開始日から機械的に決まり、Gemini の1日20リクエストを
   超えないこと(日次・月次と合算)。週の観測本数が 47本×週2回 = 94本
   以上になること。
3. 判定(cited_domain / cited_article / mentioned)が URL の表記ゆれに強く、
   欠測を 0 と書かないこと。
4. 日次・月次のタブやスキーマを汚さないこと。
5. 503 は取り直し、429 は取り直さず欠測。終了コードがその理由で分かれること。
"""
import csv
import datetime as dt
import hashlib
import sys

import pytest
import yaml

import collect_llm
import experiment
import notify_slack
import run_experiment
import settings
import sheets_writer

PROMPTS = settings.load_experiment_prompts()


@pytest.fixture(autouse=True)
def never_wait_for_real(monkeypatch):
    """実験の待機ループが本当に眠ったらテストを落とす(git fetch も走らせない)。"""
    def boom(seconds):
        raise AssertionError(f"run_experiment が本当に {seconds}秒 待とうとした")
    monkeypatch.setattr(run_experiment.time, "sleep", boom)
    monkeypatch.setattr(run_experiment, "_gemini_raw_from_origin", lambda rel_dir: [])

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


# --- 2. 巡回の割当と Gemini の枠 -----------------------------------------------
START = dt.date.fromisoformat(settings.EXPERIMENT_CYCLE_START)
THREE_WEEKS = [START + dt.timedelta(days=i) for i in range(21)]
# 巡回の開始日は曜日を選ばない(本数は日付から決まる)。曜日ごとの本数を見る
# テストだけは、開始日以降の最初の月曜から7日を使う。
MONDAY = START + dt.timedelta(days=(7 - START.weekday()) % 7)
WEEK = [MONDAY + dt.timedelta(days=i) for i in range(7)]         # 月〜日


def _gemini_ids(day):
    return [p["id"] for p in settings.experiment_plan(day.isoformat()).get("gemini", [])]


def test_a_normal_week_covers_the_94_observations_the_protocol_needs():
    """月・水・金・日は16本(余り4)、日次のある日は 20 − 7 − 予備2 = 11本。

    通常の週は 16×4 + 11×3 = 97本で、47本×週2回 = 94本を満たす。
    """
    counts = [settings.experiment_daily_count(d.isoformat()) for d in WEEK]
    assert counts == [16, 11, 16, 11, 16, 11, 16], counts   # 月火水木金土日
    assert sum(counts) == 97
    assert sum(counts) >= settings.EXPERIMENT_WEEKLY_TARGET


@pytest.mark.parametrize("offset", range(120))
def test_every_seven_day_window_covers_94_unless_a_monthly_batch_eats_into_it(offset):
    """どこで7日を切っても97本。月次観測(第1水・第1木)を含む窓だけ94を割る。

    第1水は月次6 + 予備2 で12本(−4)、第1木は日次7 + 月次6 + 予備2 で5本(−6)。
    その週は週次サマリの警告に「月次観測週のため」と理由が付く。
    """
    days = [START + dt.timedelta(days=offset + i) for i in range(7)]
    total = sum(settings.experiment_daily_count(d.isoformat()) for d in days)
    batches = {settings.monthly_batch_on(d.isoformat()) for d in days} - {None}
    expected = 97 - (4 if "A" in batches else 0) - (6 if "B" in batches else 0)
    assert total == expected, (total, days[0], batches)
    assert (total >= 94) == (not batches), (total, batches)


def test_the_retry_budget_is_what_is_left_over_not_a_daily_set_aside():
    """余り = 20 − その日の計画本数。日次のある日は予備2本だけ残す。"""
    for day in WEEK:
        quota = settings.gemini_requests_on(day.isoformat())
        assert quota["retry_budget"] == (settings.GEMINI_DAILY_REQUEST_LIMIT
                                         - quota["total"]), quota
    # 日次のない日は4本(= 20 − 16)、日次のある日は予備の2本
    assert settings.gemini_requests_on(MONDAY.isoformat())["retry_budget"] == 4
    assert settings.gemini_requests_on(
        (MONDAY + dt.timedelta(days=1)).isoformat())["retry_budget"] == 2


def test_the_first_week_of_a_month_gives_way_to_the_monthly_batches():
    # 第1木(2026-10-01): 日次7 + 月次B 6 + 予備2 -> 実験は5本
    # 第1水(2026-10-07): 月次A 6 + 予備2 -> 実験は12本
    assert settings.experiment_daily_count("2026-10-01") == 5
    assert settings.experiment_daily_count("2026-10-07") == 12


def _days(start, end):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


@pytest.mark.parametrize("day", list(_days(dt.date(2026, 9, 21), dt.date(2026, 12, 31))),
                         ids=str)
def test_every_day_stays_under_the_limit(day):
    """計画本数(日次 + 月次 + 実験)は毎日20以内。超えた分は 429 になって落ちる。"""
    quota = settings.gemini_requests_on(day.isoformat())
    assert quota["total"] <= settings.GEMINI_DAILY_REQUEST_LIMIT, quota
    assert not quota["over"], quota
    assert quota["spare"] >= 0, quota
    assert quota["experiment"] <= settings.EXPERIMENT_DAILY_CAP, quota
    assert quota["experiment"] <= quota["experiment_budget"], quota
    assert quota["retry_budget"] == quota["spare"], quota


def test_nothing_is_planned_before_the_cycle_starts():
    before = (START - dt.timedelta(days=1)).isoformat()
    assert settings.experiment_plan(before) == {}


def test_the_assignment_follows_the_cycle_start_with_no_manual_table():
    """開始日から、その日までに回した本数ぶんだけ輪が進む。それだけで決まる。"""
    assert _gemini_ids(START)[0] == "E01"
    running = 0
    for day in THREE_WEEKS:
        assert settings.experiment_cursor(day.isoformat()) == running % 47, day
        ids = _gemini_ids(day)
        assert ids == [f"E{(running + i) % 47 + 1:02d}" for i in range(len(ids))], day
        running += settings.experiment_daily_count(day.isoformat())


def test_moving_the_cycle_start_moves_the_whole_assignment(monkeypatch):
    """割当は開始日だけで決まる。曜日ごとの表を手で直す余地が無いことの裏。"""
    monkeypatch.setattr(settings, "EXPERIMENT_CYCLE_START", (START + dt.timedelta(days=1)).isoformat())
    monkeypatch.setattr(settings, "_EXPERIMENT_CURSOR", {})
    assert _gemini_ids(START + dt.timedelta(days=1))[0] == "E01"


def test_the_cycle_wraps_without_skipping_or_repeating_a_prompt():
    """輪を1周する間に47本が漏れなく1回ずつ出る。"""
    seen, day = [], START
    while len(seen) < 47:
        seen += _gemini_ids(day)
        day += dt.timedelta(days=1)
    assert sorted(seen[:47]) == [f"E{i:02d}" for i in range(1, 48)]


def test_a_prompt_is_never_observed_twice_on_the_same_day():
    for day in THREE_WEEKS:
        ids = _gemini_ids(day)
        assert len(ids) == len(set(ids)), day


def test_every_prompt_is_observed_about_twice_a_week():
    """週97本 / 47本 = 2.06回。どの質問も同じ回数(差は多くても1回)になる。"""
    counts = {f"E{i:02d}": 0 for i in range(1, 48)}
    for day in THREE_WEEKS:
        for pid in _gemini_ids(day):
            counts[pid] += 1
    planned = sum(settings.experiment_daily_count(d.isoformat()) for d in THREE_WEEKS)
    assert sum(counts.values()) == planned
    assert max(counts.values()) - min(counts.values()) <= 1, counts
    assert planned / 47 / 3 >= 1.9, "1本あたり週1.9回を下回った"


def test_the_two_observations_of_a_prompt_are_three_or_four_days_apart():
    """同じ質問の観測が隣り合う日に寄ると、週の中の変動を拾えない。"""
    days = {}
    for index, day in enumerate(THREE_WEEKS):
        for pid in _gemini_ids(day):
            days.setdefault(pid, []).append(index)
    gaps = {b - a for seen in days.values() for a, b in zip(seen, seen[1:])}
    assert gaps <= {3, 4}, sorted(gaps)


def test_claude_observes_all_47_on_monday_and_thursday_only():
    for day in WEEK:
        claude = settings.experiment_plan(day.isoformat()).get("claude", [])
        expected = 47 if day.weekday() in (0, 3) else 0
        assert len(claude) == expected, day


def test_daily_llm_days_are_tuesday_thursday_saturday():
    assert [d.weekday() for d in WEEK if settings.is_daily_llm_day(d.isoformat())] == [1, 3, 5]


def test_collect_can_run_without_inline_retries_or_sweep(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def boom(text, model):
        calls.append(text)
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", boom)
    got = collect_llm.collect("2026-09-21", prompts=PROMPTS[:2], out_dir=tmp_path,
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
    plan = settings.experiment_plan(MONDAY.isoformat())   # 月曜: gemini 14 / claude 47
    run_experiment.observe(MONDAY.isoformat(), plan, tmp_path, failures)
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
    # どの曜日にも観測がある(巡回は曜日ではなく開始日からの日数で決まる)
    assert all(settings.experiment_daily_count(d.isoformat()) > 0 for d in WEEK)


def test_the_workflow_commits_the_experiment_journal():
    text = (settings.ROOT_DIR / ".github" / "workflows" / "experiment.yml").read_text(
        encoding="utf-8")
    assert "data/experiment_journal.csv" in text, "欠測の記録が commit されずに消える"


# --- 5. 503 と 429 の分岐・終了コード・実験日誌 -----------------------------------
# 実際に data/raw に記録されていたエラー文面。
GEMINI_503 = ("503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is "
              "currently experiencing high demand.', 'status': 'UNAVAILABLE'}}")
GEMINI_429 = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
              "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}")
AUTH_ERROR = "401 UNAUTHENTICATED: API key not valid"


@pytest.fixture
def no_sleeping(monkeypatch):
    """待ち時間を記録するだけにして、テストを実時間で止めない。"""
    slept = []
    monkeypatch.setattr(collect_llm.time, "sleep", slept.append)
    return slept


def test_the_reason_codes_separate_503_from_429():
    assert collect_llm.miss_reason(GEMINI_503) == "unavailable"
    assert collect_llm.miss_reason(GEMINI_429) == "quota"
    assert collect_llm.miss_reason(AUTH_ERROR) == "permanent"
    assert collect_llm.miss_reason("something else") == "error"
    assert collect_llm.miss_reason(None) == ""


def test_a_503_is_retried_three_times_with_5_10_20_second_backoff(no_sleeping):
    """一時的な混雑。初回 + 3回で、待ちの合計35秒。実測の障害窓20〜90秒を跨ぐため。"""
    calls = []

    def busy():
        calls.append(1)
        raise Exception(GEMINI_503)

    with pytest.raises(Exception):
        collect_llm._with_retry(busy, label="E01/gemini")
    assert len(calls) == 4, "初回 + リトライ3回"
    assert no_sleeping == [5, 10, 20]


def test_a_429_is_not_retried_at_all(no_sleeping):
    """枠切れ。取り直しても戻らず、投げるだけ枠を食う。プロトコルどおり欠測にする。"""
    calls = []

    def over():
        calls.append(1)
        raise Exception(GEMINI_429)

    with pytest.raises(Exception):
        collect_llm._with_retry(over, label="E01/gemini")
    assert len(calls) == 1 and no_sleeping == []


def _gemini_record(error):
    return dict(_record(prompt_id="E01", model="gemini", error=error),
                model_name="gemini-2.5-flash")


def test_the_sweep_takes_two_more_runs_at_60_and_180_seconds(no_sleeping, tmp_path,
                                                             monkeypatch):
    calls = []

    def busy(text, model):
        calls.append(1)
        raise Exception(GEMINI_503)

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", busy)
    collect_llm._sweep([_gemini_record(GEMINI_503)], PROMPTS[:1], tmp_path,
                       delays=run_experiment.EXPERIMENT_SWEEP_DELAYS)
    assert no_sleeping == [60.0, 180.0]
    assert len(calls) == 2, "掃き直しは1周につき1回ずつ"


def test_the_sweep_leaves_a_429_alone(no_sleeping, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini",
                        lambda text, model: calls.append(1) or ("x", []))
    assert collect_llm._sweep([_gemini_record(GEMINI_429)], PROMPTS[:1], tmp_path,
                              delays=(60.0, 180.0)) == 0
    assert not calls, "枠切れは取り直さない"


def test_the_retry_budget_stops_the_retries_when_the_spare_runs_out(no_sleeping):
    """枠の残りを見て自動調整する。余り2本なら、503 でも追加は2回まで。"""
    calls = []

    def busy():
        calls.append(1)
        raise Exception(GEMINI_503)

    budget = collect_llm.RetryBudget(2)
    with pytest.raises(Exception):
        collect_llm._with_retry(busy, label="E01/gemini", attempts=10, budget=budget)
    assert len(calls) == 3, "初回 + 余りの2回"
    assert budget.remaining == 0 and budget.used == 2


@pytest.mark.parametrize("offset", [0, 1], ids=["月(余り6)", "火(余り0)"])
def test_the_retries_never_push_the_day_past_the_gemini_limit(offset, monkeypatch,
                                                              tmp_path, no_sleeping):
    """全部 503 でも、投げる合計はその日の余りまで。20は超えない。"""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def busy(text, model):
        calls.append(1)
        raise Exception(GEMINI_503)

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", busy)
    date = (MONDAY + dt.timedelta(days=offset)).isoformat()
    quota = settings.gemini_requests_on(date)
    plan = {"gemini": settings.experiment_plan(date)["gemini"]}
    run_experiment.observe(date, plan, tmp_path, [], delays=(0.0, 0.0))
    assert len(calls) == quota["experiment"] + quota["retry_budget"]
    assert quota["daily"] + quota["monthly"] + len(calls) == settings.GEMINI_DAILY_REQUEST_LIMIT


def test_one_transient_failure_uses_the_four_spare_on_a_day_without_the_daily_run(
        monkeypatch, tmp_path, no_sleeping):
    """月曜は上限16本で余り4本。1本の 503 にはリトライ3回 + 掃き直し1回までで、
    180秒後の2回目の掃き直しは枠が尽きて投げない(上限を14から16にした代償)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    date = MONDAY.isoformat()
    plan = {"gemini": settings.experiment_plan(date)["gemini"]}
    dead = plan["gemini"][0]["text"]
    calls = []

    def flaky(text, model):
        calls.append(text)
        if text == dead:
            raise Exception(GEMINI_503)
        return ("答え", [])

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", flaky)
    budget = collect_llm.RetryBudget(settings.gemini_requests_on(date)["retry_budget"])
    records = run_experiment.observe(date, plan, tmp_path, [], budget=budget,
                                     delays=run_experiment.EXPERIMENT_SWEEP_DELAYS)
    assert no_sleeping == [5, 10, 20, 60.0, 180.0]   # 2回目の待ちに入ってから枠切れで止まる
    assert budget.used == 4 and budget.remaining == 0
    assert calls.count(dead) == 5, "初回 + リトライ3回 + 掃き直し1回"
    assert [r["prompt_id"] for r in records if r.get("error")] == [plan["gemini"][0]["id"]]


SLACK = []


def _exit_code(monkeypatch, tmp_path, records, raising=None):
    """main() をその日の観測結果だけ差し替えて走らせ、終了コードを返す。"""
    monkeypatch.setattr(run_experiment, "DATA_RAW_EXPERIMENT_DIR", tmp_path)
    monkeypatch.setattr(run_experiment, "EXPERIMENT_JOURNAL_FILE", tmp_path / "journal.csv")

    def fake_observe(date, plan, out_dir, failures, **kwargs):
        if raising:
            raise RuntimeError(raising)
        return records

    monkeypatch.setattr(run_experiment, "observe", fake_observe)
    monkeypatch.setattr(run_experiment, "wait_for_prior_runs", lambda date: 7)
    monkeypatch.setattr(notify_slack, "notify_experiment_warnings",
                        lambda date, lines: SLACK.extend(lines) or True)
    monkeypatch.setattr(sys, "argv",
                        ["run_experiment.py", "--date", START.isoformat(), "--no-sheets"])
    with pytest.raises(SystemExit) as exited:
        run_experiment.main()
    return exited.value.code


def _missing(prompt_id, error, date=None):
    return _record(prompt_id=prompt_id, model="gemini",
                   date=date or START.isoformat(),
                   error=error, miss_reason=collect_llm.miss_reason(error), attempts=1)


def _observed(prompt_id):
    """観測できた行。summary_lines が読む判定列まで入れておく。"""
    rec = _record(prompt_id=prompt_id, model="gemini", date=START.isoformat())
    rec.update(experiment.evaluate(rec, TARGET))
    return rec


def test_a_day_whose_misses_are_all_429_exits_zero(monkeypatch, tmp_path):
    """枠切れだけなら警告に留める。毎回失敗通知が飛ぶと本当の異常が埋もれる。"""
    assert _exit_code(monkeypatch, tmp_path,
                      [_missing("E01", GEMINI_429), _missing("E02", GEMINI_429)]) == 0


def test_a_day_with_no_misses_exits_zero(monkeypatch, tmp_path):
    assert _exit_code(monkeypatch, tmp_path, [_observed("E01")]) == 0


def test_a_503_miss_that_survived_the_retries_exits_one(monkeypatch, tmp_path):
    assert _exit_code(monkeypatch, tmp_path, [_missing("E01", GEMINI_503)]) == 1


def test_a_429_miss_next_to_a_503_miss_still_exits_one(monkeypatch, tmp_path):
    assert _exit_code(monkeypatch, tmp_path,
                      [_missing("E01", GEMINI_429), _missing("E02", GEMINI_503)]) == 1


def test_an_auth_error_exits_one(monkeypatch, tmp_path):
    assert _exit_code(monkeypatch, tmp_path, [_missing("E01", AUTH_ERROR)]) == 1


def test_a_code_exception_exits_one(monkeypatch, tmp_path):
    assert _exit_code(monkeypatch, tmp_path, [], raising="バグ") == 1


def test_the_journal_records_each_miss_with_its_reason_code(tmp_path):
    path = tmp_path / "journal.csv"
    run_experiment.write_journal(START.isoformat(),
                                 [_missing("E01", GEMINI_429),
                                  _missing("E02", GEMINI_503),
                                  _record(prompt_id="E03", model="gemini")],
                                 path=path)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [(r["experiment_id"], r["reason"]) for r in rows] == [
        ("E01", "quota"), ("E02", "unavailable")]
    assert rows[0]["date"] == START.isoformat() and rows[0]["model"] == "gemini"
    assert "429" in rows[0]["detail"] and "\n" not in rows[0]["detail"]
    assert rows[0]["attempts"] == "1"


def test_the_journal_replaces_the_rows_of_a_day_that_is_run_again(tmp_path):
    """同じ日を取り直したとき、古い欠測が残ると件数が二重に数えられる。"""
    path = tmp_path / "journal.csv"
    first, second = START.isoformat(), (START + dt.timedelta(days=1)).isoformat()
    run_experiment.write_journal(first, [_missing("E01", GEMINI_503, date=first)], path=path)
    run_experiment.write_journal(second, [_missing("E09", GEMINI_429, date=second)], path=path)
    run_experiment.write_journal(first, [], path=path)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [(r["date"], r["experiment_id"]) for r in rows] == [(second, "E09")]


def test_the_journal_columns_are_the_agreed_ones():
    assert run_experiment.JOURNAL_HEADERS == [
        "date", "experiment_id", "model", "reason", "detail", "attempts"]
    assert settings.EXPERIMENT_JOURNAL_FILE.name == "experiment_journal.csv"


# --- 6. 503欠測の監視(週次サマリの1行) -----------------------------------------
WATCH_END = "2026-10-11"          # 週次が走る日曜。直近週は 10-05〜10-11


def _journal(tmp_path, rows):
    """(日付, 理由) の並びから実験日誌を作る。"""
    path = tmp_path / "journal.csv"
    records = [_missing(f"E{i:02d}", GEMINI_503 if reason == "unavailable" else GEMINI_429,
                        date=date)
               for i, (date, reason) in enumerate(rows, start=1)]
    run_experiment.write_journal("", records, path=path)
    return path


def test_the_watch_counts_only_503_misses_in_the_last_two_weeks(tmp_path):
    path = _journal(tmp_path, [
        ("2026-10-11", "unavailable"),      # 直近週
        ("2026-10-05", "unavailable"),      # 直近週のはじめ
        ("2026-10-05", "quota"),            # 429 は数えない
        ("2026-10-04", "unavailable"),      # 前の週の終わり
        ("2026-09-28", "unavailable"),      # 前の週のはじめ
        ("2026-09-27", "unavailable"),      # 2週より前。数えない
    ])
    assert run_experiment.unavailable_by_week(WATCH_END, path=path) == [2, 2]


def test_the_watch_warns_when_two_weeks_running_go_over_five(tmp_path):
    path = _journal(tmp_path, [("2026-10-11", "unavailable")] * 6
                    + [("2026-10-04", "unavailable")] * 7)
    line = run_experiment.unavailable_watch_line(WATCH_END, path=path)
    assert line.startswith("- ⚠️")
    assert "7件 / 6件" in line, line
    assert "2週続けて週5件" in line


def test_one_bad_week_alone_is_not_a_warning(tmp_path):
    """1週だけ多いのは provider 側の波。枠の配分の話と混ぜない。"""
    path = _journal(tmp_path, [("2026-10-11", "unavailable")] * 9
                    + [("2026-10-04", "unavailable")] * 2)
    line = run_experiment.unavailable_watch_line(WATCH_END, path=path)
    assert not line.startswith("- ⚠️")
    assert "2件 / 9件" in line, line


def test_exactly_five_is_not_over_the_threshold(tmp_path):
    path = _journal(tmp_path, [("2026-10-11", "unavailable")] * 5
                    + [("2026-10-04", "unavailable")] * 5)
    assert not run_experiment.unavailable_watch_line(WATCH_END, path=path).startswith("- ⚠️")


def test_the_watch_says_zero_when_the_journal_does_not_exist_yet(tmp_path):
    line = run_experiment.unavailable_watch_line(WATCH_END, path=tmp_path / "none.csv")
    assert "0件 / 0件" in line and not line.startswith("- ⚠️")


def test_quota_misses_never_trigger_the_warning(tmp_path):
    """429 は枠切れ。取り直しの枠が足りているかとは別の話。"""
    path = _journal(tmp_path, [("2026-10-11", "quota")] * 20
                   + [("2026-10-04", "quota")] * 20)
    line = run_experiment.unavailable_watch_line(WATCH_END, path=path)
    assert not line.startswith("- ⚠️") and "0件 / 0件" in line


# --- 7. 日次の実消費からの本数決定・実行順・警告(2026-09-21) ------------------------
TUESDAY = (MONDAY + dt.timedelta(days=1)).isoformat()


def _daily_raw(used_per_prompt):
    """日次の Gemini raw(prompt_id ごとの attempts)。"""
    return [{"prompt_id": pid, "model": "gemini", "attempts": n, "error": None}
            for pid, n in used_per_prompt.items()]


def test_9_19_would_have_left_the_experiment_one_request_not_thirteen():
    """9/19: 日次が17回投げた。20 − 17 − 予備2 = 1本だけ回す。"""
    assert settings.experiment_gemini_allowance("2026-09-19", 17) == 1
    assert settings.experiment_gemini_allowance("2026-09-19", 7) == 11
    assert settings.experiment_gemini_allowance("2026-09-19", 30) == 0


def test_days_without_the_daily_run_are_capped_at_16():
    assert settings.experiment_gemini_allowance(MONDAY.isoformat(), 0) == 16


def test_the_daily_consumption_counts_retries():
    records = _daily_raw({"A-1": 1, "A-2": 2, "A-3": 5, "B-1": 1, "B-2": 3, "B-3": 4, "E-1": 1})
    assert run_experiment.daily_gemini_used(records) == 17      # 9/19 の実測
    assert run_experiment.daily_is_done(records, expected=7)
    assert not run_experiment.daily_is_done(records[:6], expected=7)


def test_a_busy_daily_run_trims_the_tail_and_records_it_as_skipped():
    plan = settings.experiment_plan(TUESDAY)                     # 名目11本
    sized, skipped, budget, warnings = run_experiment.size_gemini_plan(TUESDAY, plan, 10)
    assert len(sized["gemini"]) == 8                             # 20 − 10 − 2
    assert [r["prompt_id"] for r in skipped] == [p["id"] for p in plan["gemini"][8:]]
    assert all(r["miss_reason"] == "skipped" and r["attempts"] == 0 for r in skipped)
    assert all(r["cited_domain"] == "" for r in skipped), "欠測を0と書かない"
    assert budget == 2 and not warnings
    assert 10 + len(sized["gemini"]) + budget == settings.GEMINI_DAILY_REQUEST_LIMIT


def test_a_daily_run_that_never_finished_skips_the_gemini_part_only():
    plan = settings.experiment_plan("2026-09-24")                # 木: gemini + claude
    sized, skipped, budget, warnings = run_experiment.size_gemini_plan(
        "2026-09-24", plan, None, "(90分待機)")
    assert "gemini" not in sized and len(sized["claude"]) == 47
    assert len(skipped) == len(plan["gemini"]) and budget == 0
    assert warnings and "揃わなかった" in warnings[0]


def test_the_experiment_waits_until_the_daily_gemini_is_complete():
    polls = [_daily_raw({"A-1": 1}), _daily_raw({f"P{i}": 2 for i in range(7)})]
    slept = []
    used = run_experiment.wait_for_daily(
        TUESDAY, fetch=lambda d: polls.pop(0), sleep=slept.append,
        timeout_minutes=90, poll_seconds=300)
    assert used == 14 and slept == [300]


def test_the_wait_gives_up_after_the_timeout():
    slept = []
    used = run_experiment.wait_for_daily(
        TUESDAY, fetch=lambda d: [], sleep=slept.append, timeout_minutes=10, poll_seconds=300)
    assert used is None and sum(slept) == 600


def test_three_quota_misses_raise_a_slack_line_but_two_do_not():
    two = [_missing("E01", GEMINI_429), _missing("E02", GEMINI_429)]
    assert run_experiment.quota_alert_line(two) is None
    line = run_experiment.quota_alert_line(two + [_missing("E03", GEMINI_429)])
    assert line and "3件" in line and "E03/gemini" in line


def test_three_quota_misses_post_to_slack_and_still_exit_zero(monkeypatch, tmp_path):
    SLACK.clear()
    code = _exit_code(monkeypatch, tmp_path,
                      [_missing(f"E0{i}", GEMINI_429) for i in range(1, 4)])
    assert code == 0
    assert any("429" in s and "3件" in s for s in SLACK), SLACK


def test_skipped_prompts_do_not_fail_the_run(monkeypatch, tmp_path):
    SLACK.clear()
    monkeypatch.setattr(run_experiment, "DATA_RAW_EXPERIMENT_DIR", tmp_path)
    monkeypatch.setattr(run_experiment, "EXPERIMENT_JOURNAL_FILE", tmp_path / "journal.csv")
    monkeypatch.setattr(run_experiment, "observe", lambda *a, **k: [])
    monkeypatch.setattr(run_experiment, "wait_for_prior_runs", lambda date: None)
    monkeypatch.setattr(notify_slack, "notify_experiment_warnings",
                        lambda date, lines: SLACK.extend(lines) or True)
    monkeypatch.setattr(sys, "argv", ["run_experiment.py", "--date", TUESDAY, "--no-sheets"])
    with pytest.raises(SystemExit) as exited:
        run_experiment.main()
    assert exited.value.code == 0
    assert any("揃わなかった" in s for s in SLACK)
    with open(tmp_path / "journal.csv", encoding="utf-8", newline="") as fh:
        reasons = {r["reason"] for r in csv.DictReader(fh)}
    assert reasons == {"skipped"}


def test_the_experiment_does_not_wait_on_days_without_the_daily_run(monkeypatch, tmp_path):
    waited = []
    monkeypatch.setattr(run_experiment, "DATA_RAW_EXPERIMENT_DIR", tmp_path)
    monkeypatch.setattr(run_experiment, "EXPERIMENT_JOURNAL_FILE", tmp_path / "journal.csv")
    monkeypatch.setattr(run_experiment, "observe", lambda *a, **k: [])
    monkeypatch.setattr(run_experiment, "wait_for_prior_runs",
                        lambda date: waited.append(date))
    monkeypatch.setattr(sys, "argv",
                        ["run_experiment.py", "--date", MONDAY.isoformat(), "--no-sheets"])
    with pytest.raises(SystemExit):
        run_experiment.main()
    assert waited == []


def _experiment_raw(tmp_path, per_day):
    for date, (ok, missing) in per_day.items():
        folder = tmp_path / date
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(ok + missing):
            rec = {"prompt_id": f"E{i + 1:02d}", "model": "gemini",
                   "error": None if i < ok else "429 RESOURCE_EXHAUSTED"}
            (folder / f"E{i + 1:02d}_gemini.json").write_text(
                __import__("json").dumps(rec), encoding="utf-8")


def test_the_weekly_count_warns_below_94(tmp_path):
    days = {(MONDAY + dt.timedelta(days=i)).isoformat(): (13, 1) for i in range(7)}
    _experiment_raw(tmp_path, days)                               # 13 × 7 = 91
    end = (MONDAY + dt.timedelta(days=6)).isoformat()
    assert run_experiment.weekly_observation_count(end, tmp_path) == 91
    line = run_experiment.weekly_count_line(end, tmp_path)
    assert line.startswith("- ⚠️") and "週91本" in line and "94本" in line


def test_the_weekly_count_is_quiet_at_94_or_more(tmp_path):
    days = {(MONDAY + dt.timedelta(days=i)).isoformat(): (14, 0) for i in range(7)}
    _experiment_raw(tmp_path, days)                               # 98
    line = run_experiment.weekly_count_line((MONDAY + dt.timedelta(days=6)).isoformat(),
                                            tmp_path)
    assert not line.startswith("- ⚠️") and "週98本" in line


# --- 8. 月次観測の日も実消費で本数を決める(2026-09-21) -----------------------------
FIRST_WED, FIRST_THU = "2026-10-07", "2026-10-01"


def _raw(n, attempts=1):
    return [{"prompt_id": f"P{i}", "model": "gemini", "attempts": attempts, "error": None}
            for i in range(n)]


def test_the_monthly_batch_is_recognised_on_the_first_wednesday_and_thursday():
    assert settings.monthly_batch_on(FIRST_WED) == "A"
    assert settings.monthly_batch_on(FIRST_THU) == "B"
    assert settings.monthly_batch_on("2026-10-14") is None        # 第2水
    assert settings.has_prior_gemini_run(FIRST_WED)               # 水だが月次がある


def test_the_first_wednesday_waits_for_the_monthly_batch():
    runs = run_experiment.prior_runs(FIRST_WED)
    assert [label for label, _, _ in runs] == ["月次(バッチA)"]
    assert runs[0][2] == 6
    assert [label for label, _, _ in run_experiment.prior_runs(FIRST_THU)] == [
        "日次", "月次(バッチB)"]


def test_the_monthly_actual_consumption_is_subtracted_not_the_plan():
    """月次が再試行で10回投げた第1水: 20 − 10 − 予備2 = 8本(計画値なら12本)。"""
    plan = settings.experiment_plan(FIRST_WED)
    assert len(plan["gemini"]) == 12                               # 名目(計画値)
    used = run_experiment.wait_for_prior_runs(
        FIRST_WED, runs=[("月次(バッチA)", lambda d: _raw(6) + _raw(0), 6)])
    sized, skipped, budget, _ = run_experiment.size_gemini_plan(
        FIRST_WED, plan, used + 4)                                 # 実消費10回
    assert len(sized["gemini"]) == 8 and len(skipped) == 4 and budget == 2


def test_daily_and_monthly_are_both_counted_on_the_first_thursday():
    daily = _raw(7, attempts=2)                                    # 14回
    monthly = _raw(6)                                              # 6回
    used = run_experiment.wait_for_prior_runs(
        FIRST_THU, runs=[("日次", lambda d: daily, 7), ("月次(バッチB)", lambda d: monthly, 6)])
    assert used == 20
    sized, skipped, budget, _ = run_experiment.size_gemini_plan(
        FIRST_THU, settings.experiment_plan(FIRST_THU), used)
    assert "gemini" not in sized and len(skipped) == 5 and budget == 0


def test_the_experiment_waits_until_the_monthly_batch_is_committed():
    polls = [_raw(3), _raw(6)]
    slept = []
    used = run_experiment.wait_for_prior_runs(
        FIRST_WED, runs=[("月次(バッチA)", lambda d: polls.pop(0), 6)],
        sleep=slept.append, timeout_minutes=90, poll_seconds=300)
    assert used == 6 and slept == [300]


def test_an_unfinished_monthly_batch_skips_the_gemini_part():
    slept = []
    used = run_experiment.wait_for_prior_runs(
        FIRST_WED, runs=[("月次(バッチA)", lambda d: _raw(2), 6)],
        sleep=slept.append, timeout_minutes=5, poll_seconds=300)
    assert used is None and slept == [300]


def test_the_weekly_warning_names_the_monthly_week(tmp_path):
    """月次のある週は94を割る。警告に理由を添える。"""
    end = "2026-10-07"                                             # 10/01(木B)〜10/07(水A)
    days = {(dt.date(2026, 10, 7) - dt.timedelta(days=i)).isoformat(): (12, 0)
            for i in range(7)}
    _experiment_raw(tmp_path, days)                               # 84本
    line = run_experiment.weekly_count_line(end, tmp_path)
    assert line.startswith("- ⚠️") and line.endswith("(月次観測週のため)"), line


def test_a_normal_short_week_has_no_monthly_reason(tmp_path):
    days = {(MONDAY + dt.timedelta(days=i)).isoformat(): (12, 0) for i in range(7)}
    _experiment_raw(tmp_path, days)
    line = run_experiment.weekly_count_line((MONDAY + dt.timedelta(days=6)).isoformat(),
                                            tmp_path)
    assert line.startswith("- ⚠️") and "月次観測週" not in line

