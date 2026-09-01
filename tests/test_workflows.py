"""GitHub Actions のワークフロー定義の検査.

2026-09-01 に monthly.yml を構文エラーのまま push した。`on:` の直下に
`schedule:` を置かず `- cron:` を直接書いたため、シーケンスとマッピングが
同じ階層で混ざって ParserError になっていた。

GitHub 側の症状は分かりにくい:
  - Actions 画面にワークフロー名ではなく**ファイルパス**が表示される
  - push のたびに Failure になる
  - **Run workflow ボタンが出ない**(workflow_dispatch が読めていないため)

壊れていることに気付くまでに1往復かかったので、手元で落とすようにする。
"""
import pytest
import yaml

from settings import ROOT_DIR

WORKFLOW_DIR = ROOT_DIR / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
NAMES = [p.name for p in WORKFLOWS]


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(doc):
    """``on:`` は YAML 1.1 で真偽値 True に解釈される。両方を受ける。"""
    return doc.get(True) if True in doc else doc.get("on")


def test_there_are_workflow_files():
    assert WORKFLOWS, "ワークフローが1つも見つからない"


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_the_workflow_is_valid_yaml(path):
    """構文エラーだと Actions がファイルパス表示になり、実行もできない。"""
    try:
        doc = _load(path)
    except yaml.YAMLError as exc:
        pytest.fail(f"{path.name} が YAML として読めない: {exc}")
    assert isinstance(doc, dict), f"{path.name} の最上位がマッピングでない"


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_the_workflow_has_a_name(path):
    """名前が無いと Actions 画面にファイルパスが出る。"""
    assert str(_load(path).get("name") or "").strip(), f"{path.name} に name: が無い"


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_the_triggers_are_a_mapping(path):
    """`on:` の下は必ずマッピング。

    `- cron:` を直接書くとシーケンスになり、`workflow_dispatch:` と
    同じ階層で混ざって構文エラーになる。cron は `schedule:` の下に置く。
    """
    triggers = _triggers(_load(path))
    assert isinstance(triggers, dict), (
        f"{path.name} の on: がマッピングでない({type(triggers).__name__})。"
        "cron は schedule: の下に置くこと"
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_a_cron_lives_under_schedule(path):
    triggers = _triggers(_load(path))
    if "schedule" not in triggers:
        pytest.skip("定期実行のないワークフロー")
    schedule = triggers["schedule"]
    assert isinstance(schedule, list) and schedule, f"{path.name}: schedule: がリストでない"
    for entry in schedule:
        assert isinstance(entry, dict) and entry.get("cron"), \
            f"{path.name}: schedule の要素に cron が無い"


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_the_workflow_can_be_run_by_hand(path):
    """Run workflow ボタンが出ること。手動実行できないと初回実行ができない。"""
    triggers = _triggers(_load(path))
    assert "workflow_dispatch" in triggers, \
        f"{path.name} に workflow_dispatch が無く、手動実行できない"


@pytest.mark.parametrize("path", WORKFLOWS, ids=NAMES)
def test_every_job_has_steps(path):
    doc = _load(path)
    jobs = doc.get("jobs") or {}
    assert jobs, f"{path.name} に jobs が無い"
    for name, job in jobs.items():
        assert job.get("steps"), f"{path.name} の {name} に steps が無い"
        assert job.get("runs-on"), f"{path.name} の {name} に runs-on が無い"


def test_the_monthly_workflow_matches_the_others():
    """monthly は daily / weekly と同じ構造にする(構文エラーの再発防止)。"""
    monthly = _triggers(_load(WORKFLOW_DIR / "monthly.yml"))
    weekly = _triggers(_load(WORKFLOW_DIR / "weekly.yml"))
    assert set(monthly) == set(weekly) == {"schedule", "workflow_dispatch"}


def test_the_monthly_run_is_gated_on_the_first_tuesday():
    """毎週火曜に起動して guard で絞る。cron では第1火曜を書けないため。"""
    doc = _load(WORKFLOW_DIR / "monthly.yml")
    assert _triggers(doc)["schedule"] == [{"cron": "30 22 * * 1"}]
    assert doc["jobs"]["monthly"]["if"] == "needs.guard.outputs.run == 'true'"
