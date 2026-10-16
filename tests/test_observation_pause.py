"""日次・月次・週次の観測と配信の一時停止(2026-10-17〜・ダッシュボードの再設計のため・本田さん決定)。

止めるもの:日次観測7本・月次観測12本・週次所見の生成と配信・prompt_marketing・日次の結果配信。
止めないもの:実験観測(停止中は毎日14本・予備6本・週98本)・GA4/GSC・各ワークフローの失敗通知。
停止は config/observation_pause.yaml の日付で決まる。停止より前の日の本数(=巡回の割当)は変えない。
"""
import datetime as dt

import pytest

import collect_ga4
import collect_gsc
import collect_llm
import notify_slack
import settings

PAUSE_FROM = "2026-10-17"


def _pause(monkeypatch, tmp_path, start=PAUSE_FROM, until=None):
    path = tmp_path / "observation_pause.yaml"
    text = f'paused_from: "{start}"' + chr(10)
    text += (f'paused_until: "{until}"' if until else "paused_until: null") + chr(10)
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(settings, "OBSERVATION_PAUSE_FILE", path)
    settings._EXPERIMENT_CURSOR.clear()


@pytest.fixture
def paused(monkeypatch, tmp_path):
    _pause(monkeypatch, tmp_path)


def _days(first, last):
    day, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    while day <= end:
        yield day.isoformat()
        day += dt.timedelta(days=1)


def _week_total(monday):
    return sum(settings.experiment_daily_count(d)
               for d in _days(monday, (dt.date.fromisoformat(monday) + dt.timedelta(days=6)).isoformat()))


def test_the_real_config_pauses_from_10_17_with_no_end_yet():
    start, until = settings.observation_pause_window(settings.CONFIG_DIR / "observation_pause.yaml")
    assert (start, until) == (PAUSE_FROM, "")


def test_every_paused_day_runs_14_experiment_prompts_with_6_spare(paused):
    for d in _days(PAUSE_FROM, "2026-12-31"):
        quota = settings.gemini_requests_on(d)
        assert settings.observation_paused(d)
        assert not settings.has_prior_gemini_run(d), d          # 日次・月次を待たない
        assert (quota["daily"], quota["monthly"], quota["experiment"]) == (0, 0, 14), d
        assert quota["retry_budget"] == 6, d
    assert not settings.is_daily_llm_day("2026-10-20")              # 火曜でも日次は無い
    assert settings.monthly_batch_on("2026-11-04") is None          # 第1水でも月次は無い
    assert settings.monthly_batch_on("2026-11-05") is None


def test_a_paused_week_has_98_which_meets_twice_a_week_including_the_monthly_week(paused):
    target = settings.experiment_weekly_target()
    assert target == 92
    for monday in ("2026-10-19", "2026-10-26", "2026-11-02", "2026-12-07"):   # 11/2・12/7 は月次のある週だった
        assert _week_total(monday) == 98 >= target, monday


def test_days_before_the_pause_keep_their_counts_and_assignments(monkeypatch, tmp_path):
    """停止は日付で効く。停止より前の日の本数が変わると巡回が過去に遡ってずれる。"""
    before = {d: (settings.experiment_daily_count(d), settings.experiment_cursor(d))
              for d in _days(settings.EXPERIMENT_CYCLE_START, PAUSE_FROM)}
    plan = [p["id"] for p in settings.experiment_plan(PAUSE_FROM)["gemini"]]
    _pause(monkeypatch, tmp_path)
    after = {d: (settings.experiment_daily_count(d), settings.experiment_cursor(d))
             for d in _days(settings.EXPERIMENT_CYCLE_START, PAUSE_FROM)}
    last_day = (dt.date.fromisoformat(PAUSE_FROM) - dt.timedelta(days=1)).isoformat()
    assert {d: v for d, v in after.items() if d <= last_day} == \
        {d: v for d, v in before.items() if d <= last_day}
    # 停止の初日(土曜)は先頭の位置は同じで、本数だけ 11 → 14
    assert before[PAUSE_FROM] == (11, after[PAUSE_FROM][1])
    assert after[PAUSE_FROM][0] == 14
    paused_plan = [p["id"] for p in settings.experiment_plan(PAUSE_FROM)["gemini"]]
    assert set(plan) <= set(paused_plan) and len(paused_plan) == 14


def test_resuming_with_paused_until_keeps_the_paused_days_and_brings_back_tue_thu_sat(monkeypatch, tmp_path):
    """再開は paused_until に最後の日を入れる。停止中の日の割当は変わらず、翌日から日次・月次が戻る。"""
    _pause(monkeypatch, tmp_path)
    ongoing = {d: settings.experiment_cursor(d) for d in _days(PAUSE_FROM, "2026-11-30")}
    _pause(monkeypatch, tmp_path, until="2026-11-29")
    assert {d: settings.experiment_cursor(d) for d in _days(PAUSE_FROM, "2026-11-30")} == ongoing
    assert not settings.observation_paused("2026-11-30")
    assert settings.is_daily_llm_day("2026-12-01")                  # 火曜
    assert settings.experiment_daily_count("2026-12-01") == 11      # 予備2に戻る
    assert settings.monthly_batch_on("2026-12-02") == "A"           # 第1水
    # 再開すると14本×7日の前提が崩れる(README):火木土が11本に戻ると 14×4 + 11×3 = 89 < 92
    assert 14 * 4 + 11 * 3 == 89 < settings.experiment_weekly_target()


# --------------------------------------------------------------------------
# 各ワークフローの入口
# --------------------------------------------------------------------------
def test_daily_skips_the_llm_and_the_daily_delivery_but_still_collects_ga4_gsc(paused, monkeypatch):
    import run_daily
    import sheets_writer
    called = {"collect": 0, "ga4": 0, "gsc": 0, "notify": []}
    monkeypatch.setattr(collect_llm, "collect",
                        lambda d, **kw: called.__setitem__("collect", called["collect"] + 1) or [])
    monkeypatch.setattr(collect_ga4, "collect", lambda: called.__setitem__("ga4", called["ga4"] + 1) or [])
    monkeypatch.setattr(collect_gsc, "collect", lambda: called.__setitem__("gsc", called["gsc"] + 1) or [])
    monkeypatch.setattr(collect_gsc, "collect_pages", lambda: [])
    monkeypatch.setattr(notify_slack, "notify",
                        lambda date, *a, **kw: called["notify"].append(list(a[2] if len(a) > 2 else ())) or True)
    for name in dir(sheets_writer):
        if name.startswith("read_"):
            monkeypatch.setattr(sheets_writer, name, lambda *a, **k: [])
        elif name.startswith("write_"):
            monkeypatch.setattr(sheets_writer, name, lambda *a, **k: None)
    # 前日の daily_summary はある(実行漏れの警告を出さない)
    monkeypatch.setattr(sheets_writer, "read_daily_summary", lambda: [{"date": "2026-10-16"}])
    summary = []
    monkeypatch.setattr(run_daily, "_job_summary", lambda lines: summary.extend(lines))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", PAUSE_FROM])     # 土曜(日次の観測日だった)
    with pytest.raises(SystemExit) as exited:
        run_daily.main()
    assert exited.value.code == 0
    assert called["collect"] == 0, "日次の7本は投げない"
    assert (called["ga4"], called["gsc"]) == (1, 1), "GA4・GSC は取る"
    assert called["notify"] == [], "失敗も警告も無い日は Slack に配信しない"
    assert any("停止中" in line for line in summary)

    # 失敗した日は通知する(daily.yml の失敗通知も exit 1 で出る)
    def broken():
        raise RuntimeError("GA4 401")
    monkeypatch.setattr(collect_ga4, "collect", broken)
    with pytest.raises(SystemExit) as exited:
        run_daily.main()
    assert exited.value.code == 1
    assert len(called["notify"]) == 1


def test_monthly_does_nothing_on_the_first_wednesday(paused, monkeypatch):
    import run_monthly
    monkeypatch.setattr(collect_llm, "collect",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("投げない")))
    summary = []
    monkeypatch.setattr(run_monthly, "_job_summary", lambda lines: summary.extend(lines))
    monkeypatch.setattr("sys.argv", ["run_monthly.py", "--date", "2026-11-04", "--batch", "A"])
    run_monthly.main()
    assert any("月次観測は停止中" in line for line in summary)


def test_marketing_does_nothing_and_records_no_quota_skipped(paused, monkeypatch, tmp_path):
    import run_experiment
    import run_marketing
    monkeypatch.setattr(run_marketing, "DATA_RAW_MARKETING_DIR", tmp_path / "marketing")
    monkeypatch.setattr(collect_llm, "collect",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("投げない")))
    summary = []
    monkeypatch.setattr(run_experiment, "_job_summary", lambda lines: summary.extend(lines))
    for date in ("2026-11-02", "2026-11-16"):        # 期間内・期間後(quota_skipped を書く日だった)
        assert run_marketing.main(["--model", "gemini", "--date", date, "--no-sheets"]) == 0
    assert not (tmp_path / "marketing").exists()
    assert any("停止中" in line for line in summary)


def test_weekly_skips_the_insight_but_keeps_the_experiment_lines(paused, monkeypatch, tmp_path):
    import collect_ahrefs
    import rules_engine
    import run_experiment
    import run_weekly
    monkeypatch.setattr(run_experiment, "EXPERIMENT_JOURNAL_FILE", tmp_path / "experiment_journal.csv")
    monkeypatch.setattr(collect_ahrefs, "collect",
                        lambda date=None: (_ for _ in ()).throw(AssertionError("Ahrefs を呼ばない")))
    monkeypatch.setattr(rules_engine, "run",
                        lambda date: (_ for _ in ()).throw(AssertionError("ルールを回さない")))
    monkeypatch.setattr(notify_slack, "notify_weekly",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("配信しない")))
    summary = []
    monkeypatch.setattr(run_weekly, "_job_summary", lambda lines: summary.extend(lines))
    monkeypatch.setattr("sys.argv", ["run_weekly.py", "--date", "2026-10-19"])
    with pytest.raises(SystemExit) as exited:
        run_weekly.main()
    assert exited.value.code == 0
    text = chr(10).join(summary)
    assert "週次所見の生成と配信は停止中" in text
    assert "実験の503欠測" in text and "実験の Gemini 観測" in text
