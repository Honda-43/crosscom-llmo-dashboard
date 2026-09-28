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


# --------------------------------------------------------------------------
# プロンプトIDと自社ページの対応表(config/prompt_page_map.yaml)
# --------------------------------------------------------------------------
NOTE = "実験期間中(〜2026-12-31)のため、ページ更新を伴う施策は提案対象外。凍結対象外の施策のみ提案する"


def test_every_daily_prompt_has_pages_and_monthly_is_left_out():
    """対応表は日次プロンプトだけ。月次(ブランド指名)はページ単位の施策と対応しない。"""
    from settings import PROMPTS_FILE, load_yaml
    daily = {p["id"] for p in load_yaml(PROMPTS_FILE)["prompts"]}
    pages = experiment_freeze.load_prompt_pages()
    assert set(pages) == daily
    assert all(paths for paths in pages.values())


def test_only_a3_and_b1_map_to_frozen_pages(freeze):
    frozen = {pid for pid in freeze.prompt_pages if freeze.frozen_pages(pid)}
    assert frozen == {"A-3", "B-1"}
    assert freeze.frozen_pages("A-3") == ["/agentforce-pricing/"]


@pytest.mark.parametrize("line", [
    "推奨アクション: 担当者が来週末までにA-3の自社ページを更新する。",
    "推奨アクション: 担当者が2026/10/05までにB-1の記事にFAQを追記する。",
])
def test_a_page_update_without_a_path_is_judged_by_the_map(freeze, line):
    text, notes, _ = experiment_freeze.suppress_frozen(line, freeze)
    assert text == f"推奨アクション: {NOTE}"
    assert notes


@pytest.mark.parametrize("line", [
    # 凍結対象外の副ページをパスで指定している
    "推奨アクション: 担当者が来週末までにA-3の /service/agentforce-support/ を更新する。",
    # 対応ページが凍結対象外
    "推奨アクション: 担当者が来週末までにA-1の自社ページを更新する。",
    # 外部への修正依頼は自社ページの更新ではない
    "推奨アクション: 担当者が来週末までにA-3で引用された外部記事の運営者に修正を依頼する。",
    # 更新を伴わない
    "推奨アクション: 担当者が来週末までにA-3で引用されている競合ページを調査する。",
])
def test_other_actions_on_mapped_prompts_are_kept(freeze, line):
    text, notes, _ = experiment_freeze.suppress_frozen(line, freeze)
    assert text == line and not notes


def test_the_prompt_id_comes_from_the_item_heading(freeze):
    report = ("**R-P2(言及消失) — A-3**\n"
              "状態: A-3でClaudeの回答に3観測日以上言及がない。\n"
              "推奨アクション: 担当者が来週末までに対象ページの本文を更新する。\n"
              "**R-P2(言及消失) — A-1**\n"
              "推奨アクション: 担当者が来週末までに対象ページの本文を更新する。\n")
    text, notes, _ = experiment_freeze.suppress_frozen(report, freeze)
    lines = text.splitlines()
    assert lines[2] == f"推奨アクション: {NOTE}"
    assert lines[4].endswith("対象ページの本文を更新する。")
    assert len(notes) == 1


def test_the_models_own_note_and_alternative_are_kept(freeze):
    """注記の文面に「ページ更新」が入っているので、判定すると代替施策ごと消える。"""
    line = f"推奨アクション: {NOTE}。代わりにA-3について第三者メディアへ料金情報を提供する。"
    report = f"**R-P2(言及消失) — A-3**\n{line}"
    text, notes, _ = experiment_freeze.suppress_frozen(report, freeze)
    assert line in text.splitlines() and not notes


def test_the_prompt_names_the_mapped_frozen_prompts(freeze):
    block = experiment_freeze.prompt_block(freeze)
    assert "- A-3: /agentforce-pricing/" in block
    assert "- B-1: /agentic-crm/" in block
    assert "- A-1:" not in block
