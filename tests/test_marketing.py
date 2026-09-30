"""第3観測層 prompt_marketing のテスト(2026-10-01).

固定したいのは6つ:
1. 54本の文言は戦略管制塔の確定版のまま凍結(以後の変更はここで止める)。実験のプールには触れない
2. mentioned は6表記の文字列照合。mention_rank は本文での初出の位置で決める(LLM に順位を決めさせない)
3. **Gemini の1日の合計が20を超えない**:実験・日次・月次・同日の marketing を先に数え、残りが3以上の日だけ、
   1本1回で残りの本数まで投げる。揃っていない日・15:30 JST 以降は投げない
4. 第1週で終わらなければ第2週(14日)まで延長し、残りは quota_skipped。翌月に持ち越さない
5. その月の実験で PerDay の欠測が出たら、Gemini の残りを止めて日誌に1回だけ記録
6. llm_marketing の列・ワークフロー・ダッシュボードの集計
"""
import csv
import datetime as dt
import hashlib
import json

import pytest
import yaml

import collect_llm
import marketing
import run_marketing
import settings
import sheets_writer

JST = run_marketing.JST
PROMPTS = settings.load_marketing_prompts()
MORNING = dt.datetime(2026, 10, 2, 11, 0, tzinfo=JST)


# --- 1. 54本と凍結 ---------------------------------------------------------------
# 2026-10 の初回実行後は文言を変えない。変えるなら戦略管制塔・効果測定チャットの判断を経て
# このハッシュごと更新する(月をまたいだ比較が切れることを日誌に残す)
FROZEN_SHA256 = "189e81d6f2721faa000439ed66c24b94a325b45e580b6b9dad7dc31798f667d6"


def test_the_54_prompts_are_frozen():
    rows = "".join(f"{p['id']}\t{p['layer']}\t{p['prompt']}\n" for p in PROMPTS)
    assert hashlib.sha256(rows.encode("utf-8")).hexdigest() == FROZEN_SHA256, \
        "prompts_marketing.csv の文言は初回実行後に凍結している"


def test_the_54_prompts_have_the_agreed_shape():
    assert len(PROMPTS) == 54 and len({p["id"] for p in PROMPTS}) == 54
    counts = {}
    for p in PROMPTS:
        counts[p["layer"]] = counts.get(p["layer"], 0) + 1
    assert counts == {"MOFU_L0": 10, "MOFU_L1": 18, "MOFU_L2": 6,
                      "BOFU_single": 12, "BOFU_compare": 8}
    with open(settings.PROMPTS_MARKETING_FILE, encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == ["id", "layer", "prompt"]


def test_marketing_prompts_are_not_in_the_experiment_pool():
    pool = {p["id"] for p in settings.load_observation_prompts()}
    assert not pool & {p["id"] for p in PROMPTS}
    assert len(settings.load_experiment_prompts()) == 46


def test_the_layers_are_interleaved_so_a_short_month_covers_every_layer():
    order = [p["layer"] for p in marketing.interleave_layers(PROMPTS)]
    assert order[:5] == list(marketing.LAYER_ORDER)
    assert len(order) == 54 and set(order[:28]) == set(marketing.LAYER_ORDER)


# --- 2. 判定 ---------------------------------------------------------------------
def test_mention_rank_is_the_position_in_the_answer():
    text = "おすすめは株式会社ウフル、次に合同会社クロスコム、最後に株式会社enucolorです。"
    names = ["株式会社enucolor", "合同会社クロスコム", "株式会社ウフル"]   # 一覧の順は使わない
    assert marketing.mention_rank(text, names) == 2
    assert marketing.mention_rank("Cross-Com が最初。次にウフル", ["ウフル", "Cross-Com"]) == 1
    assert marketing.mention_rank("ウフルとクロスコム", ["本文に無い社名", "クロスコム"]) == 1
    assert marketing.mention_rank("ウフルだけ", ["ウフル"]) is None


def _rec(answer="", error=None, urls=()):
    return {"prompt_id": "PM-L0-01", "model": "gemini", "answer": answer,
            "cited_urls": list(urls), "error": error}


def test_evaluate_fills_the_columns():
    calls = []

    def lister(question, answer):
        calls.append(question)
        return ["株式会社ウフル", "合同会社クロスコム"]

    got = marketing.evaluate(_rec("株式会社ウフルと合同会社クロスコム",
                                  urls=["https://www.cross-com.jp/a/", "https://uhuru.co.jp/"]),
                             PROMPTS[0], lister=lister)
    assert (got["mentioned"], got["mention_rank"], got["is_first"], got["cited_domain"]) == (1, 2, 0, 1)
    assert got["cited_domains"] == ["cross-com.jp", "uhuru.co.jp"]
    assert got["layer"] == "MOFU_L0" and got["prompt"] == PROMPTS[0]["prompt"] and calls


def test_no_mention_means_no_rank_and_no_llm_call():
    got = marketing.evaluate(_rec("株式会社ウフルがおすすめ"), PROMPTS[0],
                             lister=lambda q, a: pytest.fail("社名が無ければ呼ばない"))
    assert (got["mentioned"], got["mention_rank"], got["is_first"]) == (0, "", 0)


def test_a_failed_company_list_keeps_the_observation():
    def boom(q, a):
        raise RuntimeError("haiku down")
    got = marketing.evaluate(_rec("クロスコム"), PROMPTS[0], lister=boom)
    assert got["mentioned"] == 1 and got["mention_rank"] == "" and got["is_first"] == ""


def test_a_miss_leaves_the_columns_blank():
    got = marketing.evaluate(_rec(error="503 UNAVAILABLE"), PROMPTS[0])
    assert got["mentioned"] == got["is_first"] == got["mention_rank"] == got["cited_domain"] == ""


# --- 3. Gemini の枠 ----------------------------------------------------------------
@pytest.mark.parametrize("used", range(0, 25))
def test_the_allowance_never_takes_the_day_over_20(used):
    allowance = settings.marketing_gemini_allowance(used)
    if used <= settings.GEMINI_DAILY_REQUEST_LIMIT:
        assert used + allowance <= settings.GEMINI_DAILY_REQUEST_LIMIT
    assert allowance == 0 or allowance >= settings.MARKETING_MIN_SPARE


def test_the_planned_days_of_the_first_twelve_months_stay_within_20():
    day = dt.date(2026, 10, 1)
    while day < dt.date(2027, 10, 1):
        d = day.isoformat()
        q = settings.gemini_requests_on(d)
        used = q["daily"] + q["monthly"] + q["experiment"]
        extra = settings.marketing_gemini_allowance(used) if settings.in_marketing_window(d) else 0
        assert used + extra <= 20, d
        day += dt.timedelta(days=1)


def _fake_gemini(monkeypatch, fail_first=0):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def fake(text, model):
        calls.append(text)
        if len(calls) <= fail_first:
            raise RuntimeError("503 UNAVAILABLE")
        return f"{text} の答え。合同会社クロスコム", []

    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", fake)
    return calls


def _gemini(tmp_path, date="2026-10-02", used=16, now=MORNING, **kw):
    out = tmp_path / "marketing" / date
    out.mkdir(parents=True, exist_ok=True)
    kw.setdefault("lister", lambda q, a: ["合同会社クロスコム"])
    kw.setdefault("experiment_dir", tmp_path / "experiment")
    kw.setdefault("diary", tmp_path / "diary.md")
    return run_marketing.run_gemini(date, PROMPTS, out, now=now, used=used,
                                    used_note="test", **kw)


@pytest.mark.parametrize("used", [0, 12, 16, 17, 18, 20])
def test_gemini_uses_only_what_is_left_and_one_call_per_prompt(monkeypatch, tmp_path, used):
    calls = _fake_gemini(monkeypatch, fail_first=1)             # 1本目は 503(取り直さない)
    recs, _ = _gemini(tmp_path, used=used)
    left = 20 - used
    expected = left if left >= 3 else 0
    assert len(calls) == len(recs) == expected
    assert used + len(calls) <= 20
    if expected:
        assert recs[0]["error"] and recs[0]["attempts"] == 1


def test_a_503_is_tried_again_on_a_later_day_but_done_ones_are_not(monkeypatch, tmp_path):
    _fake_gemini(monkeypatch, fail_first=1)
    first, _ = _gemini(tmp_path, date="2026-10-02", used=16)
    calls = _fake_gemini(monkeypatch)
    second, _ = _gemini(tmp_path, date="2026-10-04", used=16)
    assert calls[0] == first[0]["question"]                     # 503 の1本から
    done = {r["prompt_id"] for r in first[1:]}
    assert not done & {r["prompt_id"] for r in second}


def test_nothing_is_thrown_when_the_prior_runs_are_not_complete(monkeypatch, tmp_path):
    calls = _fake_gemini(monkeypatch)
    recs, notes = _gemini(tmp_path, used=None)
    assert not calls and not recs


def test_nothing_is_thrown_after_the_cutoff(monkeypatch, tmp_path):
    calls = _fake_gemini(monkeypatch)
    late = dt.datetime(2026, 10, 2, 15, 30, tzinfo=JST)
    recs, notes = _gemini(tmp_path, now=late)
    assert not calls and "15:30" in notes[0]
    assert run_marketing.before_cutoff(dt.datetime(2026, 10, 2, 15, 29, tzinfo=JST))


def _raw(folder, name, rec):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_the_day_total_counts_every_prior_run_and_todays_marketing(tmp_path, monkeypatch):
    date = "2026-10-02"                                          # 金曜:日次・月次なし・実験16本
    plan = [p["id"] for p in settings.experiment_plan(date)["gemini"]]
    exp = [{"prompt_id": pid, "attempts": 2 if i == 0 else 1} for i, pid in enumerate(plan)]
    _raw(tmp_path / date, "PM-L0-01_gemini.json", {"prompt_id": "PM-L0-01", "attempts": 1})
    used, note = run_marketing.gemini_used_today(date, experiment_records=exp, prior=[],
                                                 marketing_dir=tmp_path)
    assert used == 16 + 1 + 1 and "実験17" in note
    missing = run_marketing.gemini_used_today(date, experiment_records=exp[:-1], prior=[],
                                              marketing_dir=tmp_path)
    assert missing == (None, "実験の Gemini が揃っていない")
    daily_short = [("日次", [{"prompt_id": "D-1"}], 7)]
    assert run_marketing.gemini_used_today(date, experiment_records=exp, prior=daily_short,
                                           marketing_dir=tmp_path)[0] is None


# --- 4. 期間と持ち越し ------------------------------------------------------------
def test_the_last_window_day_records_the_rest_as_quota_skipped(monkeypatch, tmp_path):
    calls = _fake_gemini(monkeypatch)
    recs, notes = _gemini(tmp_path, date="2026-10-14", used=16)
    assert len(calls) == 4
    skipped = [r for r in recs if str(r["error"]).startswith("quota_skipped")]
    assert len(skipped) == 50 and not any(r.get("attempts") for r in skipped)
    assert marketing.pending(PROMPTS, "2026-10", "gemini", tmp_path / "marketing") == []


def test_a_missed_last_day_is_closed_on_the_next_run_without_calls(monkeypatch, tmp_path):
    calls = _fake_gemini(monkeypatch)
    recs, _ = _gemini(tmp_path, date="2026-10-16", used=0)
    assert not calls and len(recs) == 54
    assert all(r["error"].startswith("quota_skipped") for r in recs)
    again, notes = _gemini(tmp_path, date="2026-10-17", used=0)
    assert not again and "終わっている" in notes[0]


def test_nothing_is_carried_over_to_the_next_month(monkeypatch, tmp_path):
    _fake_gemini(monkeypatch)
    _gemini(tmp_path, date="2026-10-16", used=0)
    assert len(marketing.pending(PROMPTS, "2026-11", "gemini", tmp_path / "marketing")) == 54


def test_before_the_first_month_nothing_happens(tmp_path, capsys):
    assert run_marketing.main(["--model", "gemini", "--date", "2026-09-30", "--no-sheets"]) == 0
    assert "より前" in capsys.readouterr().out
    assert not settings.in_marketing_window("2026-09-02")
    assert settings.in_marketing_window("2026-10-14") and not settings.in_marketing_window("2026-10-15")


# --- 5. 実験の PerDay 欠測で止める ------------------------------------------------------
def test_an_experiment_perday_miss_stops_the_month_and_is_written_to_the_diary(monkeypatch, tmp_path):
    _raw(tmp_path / "experiment" / "2026-10-01", "E05_gemini.json",
         {"prompt_id": "E05", "error": "429 RESOURCE_EXHAUSTED ... quotaId: GenerateRequestsPerDayPerProject"})
    diary = tmp_path / "diary.md"
    diary.write_text("# 日誌\n", encoding="utf-8")
    calls = _fake_gemini(monkeypatch)
    recs, notes = _gemini(tmp_path, date="2026-10-02", diary=diary)
    assert not calls and len(recs) == 54
    assert all("PerDay" in r["error"] and r["error"].startswith("quota_skipped") for r in recs)
    text = diary.read_text(encoding="utf-8")
    assert "prompt_marketing（2026-10）を停止" in text and "2026-10-01 E05" in text
    assert not run_marketing.record_stop_in_diary("2026-10", ["x"], 0, diary), "2回は書かない"


def test_a_per_minute_429_does_not_stop_the_month(tmp_path):
    _raw(tmp_path / "2026-10-01", "E05_gemini.json",
         {"prompt_id": "E05", "error": "429 RESOURCE_EXHAUSTED PerMinute"})
    assert marketing.experiment_perday_misses("2026-10", tmp_path) == []


def test_claude_runs_all_on_the_first_day_and_is_not_stopped(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    calls = []
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "claude",
                        lambda text, model: (calls.append(text) or ("答え", [])))
    out = tmp_path / "marketing" / "2026-10-01"
    out.mkdir(parents=True)
    recs, _ = run_marketing.run_claude("2026-10-01", PROMPTS, out, lister=lambda q, a: [])
    assert len(calls) == len(recs) == 54


# --- 6. 列・ワークフロー・ダッシュボード --------------------------------------------------
def test_the_sheet_has_the_agreed_columns():
    assert sheets_writer.HEADERS_MARKETING == [
        "date", "model", "prompt_id", "layer", "prompt", "mentioned", "is_first",
        "mention_rank", "cited_domain", "cited_domains", "answer_text", "error"]
    assert settings.TAB_MARKETING == "llm_marketing" != settings.TAB_EXPERIMENT


def test_gemini_runs_after_the_experiment_in_the_same_job_and_claude_on_its_own():
    wf = yaml.safe_load(open(settings.ROOT_DIR / ".github/workflows/experiment.yml", encoding="utf-8"))
    steps = [s.get("name", "") for s in wf["jobs"]["experiment"]["steps"]]
    assert steps.index("Run prompt_marketing (Gemini) within the day's remaining quota") \
        == steps.index("Run experiment observation") + 1
    commit = next(s for s in wf["jobs"]["experiment"]["steps"] if s.get("name", "").startswith("Commit"))
    assert "data/raw/marketing" in commit["run"]
    mk = yaml.safe_load(open(settings.ROOT_DIR / ".github/workflows/marketing.yml", encoding="utf-8"))
    run = " ".join(s.get("run", "") for s in mk["jobs"]["marketing"]["steps"])
    assert "--model claude" in run and "GEMINI_API_KEY" not in json.dumps(mk)


def test_layer_rates_use_the_latest_observation_and_skip_misses():
    rows = [
        {"date": "2026-10-02", "prompt_id": "A", "model": "gemini", "layer": "MOFU_L0",
         "mentioned": "0", "cited_domain": "0", "error": ""},
        {"date": "2026-10-04", "prompt_id": "A", "model": "gemini", "layer": "MOFU_L0",
         "mentioned": "1", "cited_domain": "1", "error": ""},
        {"date": "2026-10-02", "prompt_id": "B", "model": "gemini", "layer": "MOFU_L0",
         "mentioned": "", "cited_domain": "", "error": "quota_skipped"},
        {"date": "2026-10-01", "prompt_id": "C", "model": "claude", "layer": "BOFU_single",
         "mentioned": "1", "cited_domain": "0", "error": ""},
    ]
    got = marketing.layer_rates(rows)
    assert [(c["layer"], c["model"], c["n"], c["mentioned"], c["cited_domain"]) for c in got] == [
        ("MOFU_L0", "gemini", 1, 1, 1), ("BOFU_single", "claude", 1, 1, 0)]
