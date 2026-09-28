"""実験期間中の編集凍結を週次所見に反映する(2026-09-28)。"""
import pytest

import action_log
import experiment_freeze
import generate_insight

REPORT = """## 3. 発火パターンと推奨アクション

**R-P2(言及消失) — A-3**
状態: A-3でClaudeの回答に3観測日以上言及がない。
推奨アクション: 担当者が来週末までに /agentforce-pricing/ に費用相場の表を追記する。

**R-P7(古い情報) — E-1**
推奨アクション: 担当者が来週末までに他記事から https://cross-com.jp/agentforce-guide/ へリンクを張る。
推奨アクション: 担当者が来週末までに /agentic-crm/ の本文を更新する。
推奨アクション: 担当者が来週末までに /service/btob-marketing-strategy/ を更新する。
"""


@pytest.fixture
def freeze():
    return experiment_freeze.load("2026-09-28")


def test_the_lists_come_from_the_seo_agent_files(freeze):
    """一覧は書き写さず、seo-agent と同じ targets.csv・link_ban.csv を読む。"""
    assert "agentforce-pricing" in freeze.edit_ban
    assert "agentforce-pricing" in freeze.link_ban
    # ピラー2本は編集禁止だが張り先にはしてよい
    assert freeze.edit_ban - freeze.link_ban == {"agentforce-guide", "agentic-crm"}
    # 2026-09-22 に実験から外した記事は凍結しない
    assert "agentforce-coworker" not in freeze.edit_ban


@pytest.mark.parametrize("date,active", [
    ("2026-09-14", False), ("2026-09-15", True), ("2026-12-31", True), ("2027-01-01", False),
])
def test_the_freeze_runs_from_09_15_to_12_31(date, active):
    assert (experiment_freeze.load(date) is not None) is active


def test_actions_on_frozen_pages_are_replaced_with_the_note(freeze):
    text, notes, written = experiment_freeze.suppress_frozen(REPORT, freeze)
    lines = text.splitlines()
    note = "実験期間中(〜2026-12-31)のため、ページ更新を伴う施策は提案対象外。凍結対象外の施策のみ提案する"
    assert f"推奨アクション: {note}" in lines
    assert not any("/agentforce-pricing/ に費用相場" in l for l in lines)
    assert not any("/agentic-crm/ の本文" in l for l in lines)
    # ピラーを張り先にするのは可、凍結対象外のページの更新も可
    assert any("agentforce-guide/ へリンク" in l for l in lines)
    assert any("/service/btob-marketing-strategy/" in l for l in lines)
    # 状態の行(引用の事実)は触らない
    assert "状態: A-3でClaudeの回答に3観測日以上言及がない。" in lines
    assert len(notes) == 2
    assert written == [note]


def test_a_similar_slug_is_not_mistaken_for_a_pillar(freeze):
    line = "推奨アクション: /agentic-crm-roadmap-2027/ を更新する。"
    assert experiment_freeze.violations(line, freeze) == []


def test_the_note_is_not_registered_as_a_new_proposal(freeze):
    """差し替えた注記が action_log に「提案中」で入ると、中身のない行が増える(A-016 と同じ)。"""
    result = generate_insight.postprocess(REPORT, {"date": "2026-09-28"}, [],
                                          thresholds={}, freeze=freeze)
    proposals = action_log.sync_from_report(
        result["report_md"], "2026-09-28", existing=[],
        settled_lines=result["settled_lines"])
    contents = [p["内容"] for p in proposals]
    assert not any("実験期間中" in c for c in contents), contents
    assert any("agentforce-guide" in c for c in contents)
    assert len(result["frozen"]) == 2


def test_the_prompt_carries_the_constraint_only_in_the_period(freeze):
    stats = {"date": "2026-09-28"}
    assert "凍結対象(49本)" in generate_insight.build_user_prompt(stats, [], {}, freeze=freeze)
    assert "/agentforce-pricing/" in generate_insight.build_user_prompt(stats, [], {}, freeze=freeze)
    assert "凍結対象" not in generate_insight.build_user_prompt(stats, [], {}, freeze=None)


def test_an_unreadable_list_degrades_to_the_numeric_report(monkeypatch, tmp_path):
    """期間内に一覧が読めなければ、制約なしで書かせず数値だけの所見に落とす。"""
    cfg = tmp_path / "freeze.yaml"
    cfg.write_text('experiment_start: "2026-09-29"\nexperiment_end: "2026-12-31"\n'
                   'freeze_start: "2026-09-15"\nedit_ban_file: missing.csv\n'
                   'link_ban_file: missing.csv\n', encoding="utf-8")
    real_load = experiment_freeze.load
    monkeypatch.setattr(experiment_freeze, "load",
                        lambda date: real_load(date, config_path=cfg))
    called = []
    monkeypatch.setattr(generate_insight, "_call_model",
                        lambda *a, **k: called.append(1) or REPORT)
    stats = {"date": "2026-09-28", "rules": [], "fired_rules": [], "insufficient_rules": [],
             "mention_rate": {}, "data_quality": {}}
    result = generate_insight.generate(stats, playbook="p", actions=[])
    assert result["source"] == "fallback"
    assert not called
