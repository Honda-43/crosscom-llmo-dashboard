"""実験の週次集計(experiment_weekly)のテスト(2026-09-22).

固定したいのは5つ:
1. 週の切り方(月曜生成・前の月〜日)とファイル名(experiment47_weekN_YYYYMMDD.md)
2. cited_article と cited_domain の率。分母は欠測を除いた観測
3. mentioned は参考欄に回す(全体の表には出さない)
4. プール外の記事(9/22 に除外した E37)の行は数えない
5. 毎週月曜の weekly.yml から呼ばれ、結果が commit される
"""
import datetime as dt
import json

import yaml

import experiment_weekly as ew
import settings

MON = dt.date(2026, 9, 28)
POOL = [{"id": "E01", "layer": "古", "url": "https://cross-com.jp/a/"},
        {"id": "E02", "layer": "中", "url": "https://cross-com.jp/b/"}]


def _row(date, pid, model, article=0, domain=0, mentioned=0, error=""):
    return {"date": date, "experiment_id": pid, "model": model, "cited_article": str(article),
            "cited_domain": str(domain), "mentioned": str(mentioned), "error": error}


def _build(rows, tmp_path):
    return ew.build(MON, rows, pool=POOL, raw_dir=tmp_path / "raw",
                    experiment_dir=tmp_path / "exp", monthly_dir=tmp_path / "monthly")


def test_the_week_is_the_monday_to_sunday_before_the_report():
    assert ew.week_window(MON) == (dt.date(2026, 9, 21), dt.date(2026, 9, 27))
    assert ew.week_number(MON) == 2
    assert ew.week_number(dt.date(2026, 10, 5)) == 3
    assert ew.report_path(MON).name == "experiment47_week2_20260928.md"


def test_the_rates_exclude_misses_and_include_the_domain_rate(tmp_path):
    rows = [_row("2026-09-22", "E01", "gemini", article=1, domain=1),
            _row("2026-09-23", "E02", "gemini", article=0, domain=1),
            _row("2026-09-24", "E02", "gemini", error="429 RESOURCE_EXHAUSTED PerDay"),
            _row("2026-09-24", "E01", "claude", article=0, domain=0)]
    text = _build(rows, tmp_path)
    assert "| Gemini | 3 | 1 | 2 | 1 | 50.0% | 2 | 100.0% |" in text, text
    assert "| Claude | 1 | 0 | 1 | 0 | 0.0% | 0 | 0.0% |" in text
    assert "記事URLが1回でも出た記事: 1本 / 2本" in text
    assert "cross-com.jp のどれかのURLが1回でも出た記事: 2本 / 2本" in text


def test_mentioned_is_only_in_the_reference_section(tmp_path):
    rows = [_row("2026-09-22", "E01", "gemini", mentioned=1),
            _row("2026-09-22", "E02", "gemini")]
    text = _build(rows, tmp_path)
    overall = text.split("## 2.")[0]
    assert "mentioned" not in overall and "言及" not in overall
    reference = text.split("## 4. 参考")[1]
    assert "Gemini: 1 / 2(50.0%) — E01" in reference


def test_rows_outside_the_pool_are_not_counted(tmp_path):
    rows = [_row("2026-09-21", "E01", "claude"), _row("2026-09-21", "E37", "claude", article=1)]
    text = _build(rows, tmp_path)
    assert "同期間 1行" in text and "プール外の記事の行 1件は数えていない" in text
    assert "記事URLが1回でも出た記事: 0本" in text


def test_rows_outside_the_week_are_not_counted(tmp_path):
    rows = [_row("2026-09-20", "E01", "gemini", article=1),     # 前の週
            _row("2026-09-28", "E01", "gemini", article=1)]     # 生成日当日
    assert "同期間 0行" in _build(rows, tmp_path)


def test_gemini_calls_add_daily_monthly_and_experiment_with_retries(tmp_path):
    def raw(folder, attempts):
        folder.mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(attempts):
            (folder / f"P{i}_gemini.json").write_text(json.dumps({"attempts": n}), encoding="utf-8")
    raw(tmp_path / "raw" / "2026-09-22", [1, 2, 1, 1, 1, 1, 1])        # 日次 8
    raw(tmp_path / "exp" / "2026-09-22", [1] * 10)                      # 実験 10
    text = _build([], tmp_path)
    assert "| 2026-09-22 | 火 | 8 | 0 | 10 | 18 |" in text, text


def test_old_raw_without_attempts_is_shown_as_a_lower_bound(tmp_path):
    folder = tmp_path / "exp" / "2026-09-23"
    folder.mkdir(parents=True)
    (folder / "E01_gemini.json").write_text(json.dumps({"prompt_id": "E01"}), encoding="utf-8")
    assert "| 2026-09-23 | 水 | 0 | 0 | ≥1 | ≥1 |" in _build([], tmp_path)


def test_miss_reasons_are_split(tmp_path):
    rows = [_row("2026-09-22", "E01", "gemini", error="429 RESOURCE_EXHAUSTED PerDay"),
            _row("2026-09-22", "E02", "gemini", error="503 UNAVAILABLE"),
            _row("2026-09-23", "E01", "gemini", error="skipped: 日次の実消費17回で枠が足りず")]
    text = _build(rows, tmp_path)
    assert "枠切れ(429)1件・503 1件・投げずに記録(日次・月次の実消費で枠が足りない日)1件" in text


def test_the_real_pool_is_46_without_e37():
    ids = [p["id"] for p in settings.load_experiment_prompts()]
    assert len(ids) == 46 and "E37" not in ids


def test_the_weekly_workflow_builds_and_commits_the_summary():
    doc = yaml.safe_load((settings.ROOT_DIR / ".github" / "workflows" / "weekly.yml")
                         .read_text(encoding="utf-8"))
    steps = doc["jobs"]["weekly"]["steps"]
    names = [s.get("name", "") for s in steps]
    build = names.index("Build experiment weekly summary")
    commit = names.index("Commit weekly stats.json")
    assert build < commit
    assert "experiment_weekly.py" in steps[build]["run"]
    assert steps[build].get("continue-on-error") is True
    assert "output/reports" in steps[commit]["run"]
