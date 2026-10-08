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
    import collect_llm
    import settings
    collect_llm.set_deadline(None)      # 観測ジョブの時間の予算はテストごとに外す(2026-10-08)
    # Gemini の呼び出しの間隔(13秒)はテストでは空けない(間隔そのものは test_gemini_pacing で確かめる)
    monkeypatch.setattr(collect_llm, "GEMINI_MIN_INTERVAL_SECONDS", 0.0)
    collect_llm.note_gemini_call(0.0)
    # 作成中の再ランダム化プール(experiment_2x2/results/rerandomization_pool.csv)を既定では読まない(2026-10-08)。
    # 作成中は行が増え続け、2,000件を超えると判定の出力が変わるため、テストの結果が実行の時刻で揺れる。
    # パスを渡して読むテスト(test_rerandomize)には影響しない
    rr = sys.modules.get("rerandomize")
    if rr is not None:
        monkeypatch.setattr(rr.load, "__defaults__", (str(tmp_path_factory.mktemp("no_pool") / "none.csv"),))
    monkeypatch.setattr(claude_budget, "USAGE_DIR", tmp_path / "claude_usage")
    # Claude の計画的停止(2026-10-06)は既定で外す(既存のテストは再開したときの動きを確かめる)。
    # 停止中の動きは tests/test_claude_stop.py が claude_stop で入れて確かめる
    off = tmp_path_factory.mktemp("claude_running") / "claude_budget.yaml"   # テスト自身の tmp_path を汚さない
    off.write_text("planned_stop_from: null" + chr(10), encoding="utf-8")
    monkeypatch.setattr(settings, "CLAUDE_BUDGET_FILE", off)
    # 抽出保留の台帳(data/extract_pending)も本物を触らない(2026-10-06:run_daily のテストが本物の台帳を
    # 後日抽出して消していた)
    import extract_pending
    monkeypatch.setattr(extract_pending, "PENDING_DIR", tmp_path_factory.mktemp("extract_pending"))
    monkeypatch.delenv("CLAUDE_DAILY_CAP", raising=False)
    # テストから本物の API を呼ばない(2026-10-06:抽出を Gemini に移したあと、手元の GEMINI_API_KEY で
    # 本物の抽出が走りかけた)。鍵が要るテストは monkeypatch.setenv で偽の鍵を入れ、呼び出しも差し替える
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    claude_budget.reset()
    yield
    claude_budget.reset()
