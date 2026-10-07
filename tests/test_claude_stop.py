"""Claude API の計画的停止のテスト(2026-10-06・費用ゼロ方針・本田さん決定).

固定したいのは4つ:
1. 停止日から Claude を一切呼ばない(観測・抽出・順位抽出・週次所見・引用プローブ)。上限0。再開は設定を null にするだけ
2. 停止中の Claude の観測は行を作らない(欠測 error と区別がつく)。失敗の通知・上限の警告も出さない
3. 実験の判定は Claude を外す(欠測を0として数えない)。Gemini の判定は変えない
4. Gemini の観測の本数・日程は変わらない
"""
import csv
import datetime as dt
import io
import sys
import types
from pathlib import Path

import pytest
import yaml

import claude_budget
import collect_llm
import extract
import generate_insight
import run_experiment
import settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
import summarize  # noqa: E402

STOP = "2026-10-06"


@pytest.fixture
def claude_stop(tmp_path, monkeypatch):
    cfg = tmp_path / "claude_budget_stopped.yaml"
    cfg.write_text(f'planned_stop_from: "{STOP}"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", cfg)
    monkeypatch.setattr(settings, "_today_jst", lambda: "2026-10-07")
    monkeypatch.setattr(claude_budget, "today", lambda: "2026-10-07")


class NoCall:
    def __init__(self, api_key=None):
        self.messages = self

    def create(self, **kw):
        pytest.fail("停止中は Claude を呼ばない")


@pytest.fixture
def no_anthropic(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=NoCall))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


# --- 1. 設定 -----------------------------------------------------------------------------
def test_the_real_config_stops_claude_from_20261006():
    assert settings.claude_planned_stop_from(settings.CONFIG_DIR / "claude_budget.yaml") == STOP


def test_resuming_is_just_setting_null(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("planned_stop_from: null\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", cfg)
    assert not settings.claude_stopped("2026-10-20") and "claude" in settings.enabled_models()
    assert claude_budget.cap_for("2026-10-20") == 30


def test_the_cap_is_zero_while_stopped_even_with_an_override(claude_stop, monkeypatch):
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "80")
    assert claude_budget.cap_for("2026-10-12") == 0 and claude_budget.cap_for("2026-12-28") == 0
    assert claude_budget.cap_for("2026-10-05") == 80, "停止日より前は止めない"


# --- 1. 1週間の予定で Claude の呼び出しが0回・Gemini は変わらない ------------------------------------
def _week(start="2026-10-06", days=7):
    d = dt.date.fromisoformat(start)
    return [(d + dt.timedelta(days=i)).isoformat() for i in range(days)]


def test_a_week_of_plans_has_no_claude_and_the_same_gemini(claude_stop, monkeypatch):
    monkeypatch.setattr(settings, "_EXPERIMENT_CURSOR", {})
    stopped = {d: settings.experiment_plan(d) for d in _week() + ["2026-12-28"]}
    assert all("claude" not in p for p in stopped.values()), "実験の Claude(46本＋E37)は0本"
    assert sum(claude_budget.cap_for(d) for d in stopped) == 0
    assert "claude" not in settings.enabled_models(), "日次・月次の Claude 観測も外れる"

    off = Path(settings.CLAUDE_BUDGET_FILE).with_name("running.yaml")
    off.write_text("planned_stop_from: null\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", off)
    monkeypatch.setattr(settings, "_EXPERIMENT_CURSOR", {})
    running = {d: settings.experiment_plan(d) for d in stopped}
    assert "claude" in running["2026-10-12"], "止めていなければ月曜は Claude を観測する"
    for d in stopped:
        assert ([p["id"] for p in stopped[d].get("gemini", [])]
                == [p["id"] for p in running[d].get("gemini", [])]), f"{d} の Gemini が変わった"


def test_the_daily_collection_makes_no_claude_rows_and_no_misses(claude_stop, no_anthropic, monkeypatch,
                                                                 tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", lambda text, model: ("答え", []))
    prompts = [{"id": "A-1", "text": "質問"}, {"id": "B-1", "text": "質問"}]
    recs = collect_llm.collect("2026-10-08", prompts=prompts, out_dir=tmp_path)
    assert {r["model"] for r in recs} == {"gemini"}, "停止中の Claude は行を作らない(error の行も作らない)"
    assert not list(tmp_path.glob("*_claude.json"))
    assert collect_llm.missing_observations(recs, expected=collect_llm.expected_labels(prompts)) == []


# --- 1-2. 呼び出しを止める・欠測と区別する・通知を出さない ---------------------------------------
def test_the_guard_stops_every_call_without_marking_a_failure(claude_stop, tmp_path):
    claude_budget.start("daily", "2026-10-08", usage_dir=tmp_path, read_origin=False)
    with pytest.raises(claude_budget.ClaudePlannedStop, match="^planned_stop"):
        claude_budget.create(NoCall(), model="m", max_tokens=1, messages=[])
    assert claude_budget.status()["stopped"] == "" and not list(tmp_path.rglob("*.json"))
    ok, lines = claude_budget.check(["daily"], "2026-10-08", usage_dir=tmp_path)
    assert ok, "計画的停止はワークフローを失敗にしない(Slack の失敗通知・上限の警告を出さない)"


def test_extraction_is_held_as_pending_with_the_reason(claude_stop, no_anthropic, monkeypatch):
    monkeypatch.setattr(extract, "EXTRACT_MODEL", "claude-haiku-4-5-20251001")   # Claude の抽出の経路を確かめる
    got = extract.extract_record({"date": "2026-10-08", "prompt_id": "A-1", "model": "gemini",
                                  "answer": "本文", "cited_urls": []})
    assert extract.is_pending(got) and got["error"].startswith("extraction_pending: planned_stop")


def test_the_weekly_insight_is_numbers_only_and_not_a_failure(claude_stop, no_anthropic, monkeypatch):
    monkeypatch.setattr(generate_insight, "fallback_report", lambda stats: "## 数値")
    got = generate_insight.generate({"date": "2026-10-12"}, model="claude-sonnet-5")   # Claude の所見の経路
    assert got["source"] == "numbers_only" and got["error"] is None
    assert "計画的に停止" in got["report_md"] and got["report_md"].endswith("## 数値")


def test_the_haiku_rank_extraction_and_the_probe_are_stopped(claude_stop, no_anthropic, monkeypatch):
    import marketing
    with pytest.raises(claude_budget.ClaudePlannedStop):
        marketing.list_companies_with_haiku("q", "a")
    import llmo_probe
    monkeypatch.setattr(llmo_probe, "today_jst", lambda: "2027-01-05")      # 実験期間が終わっても
    monkeypatch.setattr(llmo_probe, "post_json", lambda *a, **k: pytest.fail("呼ばない"))
    with pytest.raises(claude_budget.ClaudePlannedStop):
        llmo_probe.ask_claude("質問")


def test_the_weekly_claude_line_says_planned_stop_not_a_warning(claude_stop, tmp_path):
    line = run_experiment.weekly_claude_count_line("2026-10-19", tmp_path)     # 窓 10/12〜10/18:すべて停止後
    assert "計画的に停止中" in line and "⚠️" not in line
    # 10/12 の週次(窓 10/05〜10/11)は停止前の 10/05 を含む。10/05 は Gemini の応答待ちで取れなかった本当の欠測なので警告が残る
    assert "⚠️" in run_experiment.weekly_claude_count_line("2026-10-12", tmp_path)


def test_the_experiment_weekly_report_says_claude_is_stopped(claude_stop):
    import experiment_weekly
    text = experiment_weekly.build(dt.date(2026, 10, 12), [], pool=[], intervention_rows=[])
    assert "Claude は 2026-10-06 から計画的に停止" in text and "欠測ではない" in text


# --- 3. 実験の判定 ------------------------------------------------------------------------
EXP_HEAD = ["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag"]


def _judge(monkeypatch, tmp_path, capsys, rows, *extra):
    # 作成中の再ランダム化プール(results/rerandomization_pool.csv)を読まない。2回の出力を比べるので、
    # その間にプールが1行増えると出力が変わってしまう(2026-10-08 に1回だけ落ちた)
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"agentforce-rag": "③リードのみ", "agentforce-features": "①対照"})
    path = tmp_path / "e.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([EXP_HEAD] + rows)
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-12-28",
                    "--csv", str(path), *extra])
    return capsys.readouterr().out


RAG, FEAT = "https://cross-com.jp/agentforce-rag/", "https://cross-com.jp/agentforce-features/"
ROWS = [
    ["2026-09-21", "E06", "claude", RAG, "1", "", "pool"],      # ビフォーの Claude(記録として残る)
    ["2026-09-24", "E12", "claude", FEAT, "0", "", "pool"],
    ["2026-09-20", "E06", "gemini", RAG, "0", "", "pool"],
    ["2026-10-10", "E06", "gemini", RAG, "1", "", "pool"],
    ["2026-09-20", "E12", "gemini", FEAT, "0", "", "pool"],
    ["2026-10-11", "E12", "gemini", FEAT, "0", "", "pool"],
]


def test_claude_is_out_of_the_judgement_and_never_counted_as_zero(claude_stop, monkeypatch, tmp_path, capsys):
    out = _judge(monkeypatch, tmp_path, capsys, ROWS)
    assert out.splitlines()[0] == f"**{summarize.GENERALIZATION_NOTE}**", "冒頭に一般化の注記"
    assert "Claude：アフター期間の観測なし（2026-10-06 に計画的停止・費用ゼロ方針）。判定対象外" in out
    assert "=== claude" not in out and "感度分析（claude）" not in out, "Claude の欠測を0として判定しない"
    assert "=== gemini 両方込み（2本）" in out
    out_c = _judge(monkeypatch, tmp_path, capsys, ROWS, "--model", "claude")
    assert "判定対象外" in out_c and "=== claude" not in out_c


def test_the_gemini_judgement_is_identical_with_or_without_the_stop(claude_stop, monkeypatch, tmp_path, capsys):
    stopped = _judge(monkeypatch, tmp_path, capsys, ROWS, "--model", "gemini")
    off = tmp_path / "running.yaml"
    off.write_text("planned_stop_from: null\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", off)
    running = _judge(monkeypatch, tmp_path, capsys, ROWS, "--model", "gemini")
    note = f"**{summarize.GENERALIZATION_NOTE}**\n\n"
    assert stopped == note + running, "Gemini の判定は1文字も変わらない(冒頭の注記だけ)"


# --- 記録 ---------------------------------------------------------------------------------
def test_the_plan_change_is_recorded():
    rows = [r for r in csv.reader(open(ROOT / "output" / "interventions.csv", encoding="utf-8"))
            if r and not r[0].startswith("#")]
    hit = [r for r in rows if "Claude API の全停止" in r[2]]
    assert len(hit) == 1 and hit[0][0] == STOP and hit[0][3] == "measurement" and hit[0][5] == "no"
    freeze = yaml.safe_load(open(ROOT / "config" / "experiment_freeze.yaml", encoding="utf-8"))
    change = [c for c in freeze["plan_changes"] if c["date"] == STOP]
    assert change and "判定対象外" in change[0]["change"] and "アフター期間の実験データを見る前" in change[0]["change"]
