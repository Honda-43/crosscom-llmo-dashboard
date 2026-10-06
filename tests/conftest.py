"""Make ``src/`` and ``app/`` importable — the pipeline modules import each
other flatly (``import settings``) because GitHub Actions runs them from
inside ``src/``, and the dashboard pages do the same from inside ``app/``."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for directory in (ROOT / "src", ROOT / "app"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _claude_budget_isolated(tmp_path, tmp_path_factory, monkeypatch):
    """Claude の1日の上限(claude_budget)の回数をテストごとに数え直し、repo の data/claude_usage に書かない。"""
    import claude_budget
    import settings
    monkeypatch.setattr(claude_budget, "USAGE_DIR", tmp_path / "claude_usage")
    # Claude の計画的停止(2026-10-06)は既定で外す(既存のテストは再開したときの動きを確かめる)。
    # 停止中の動きは tests/test_claude_stop.py が claude_stop で入れて確かめる
    off = tmp_path_factory.mktemp("claude_running") / "claude_budget.yaml"   # テスト自身の tmp_path を汚さない
    off.write_text("planned_stop_from: null" + chr(10), encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", off)
    monkeypatch.delenv("CLAUDE_DAILY_CAP", raising=False)
    claude_budget.reset()
    yield
    claude_budget.reset()
