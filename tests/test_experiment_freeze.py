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
def real_freeze():
    return experiment_freeze.load("2026-10-05")


@pytest.fixture
def freeze():
    """仕組みのテスト用の凍結（固定）。2026-10-02 に実ファイルの凍結は統計46本だけになり、
    pricing・ピラーが外れて「対応表で凍結ページに当たるプロンプト」が無くなった。
    差し替えの仕組みは、pricing を46本の1本の代わりに凍結して確かめる。
    ピラー2本は 10/02 以降の形（凍結を解いた・編集可。46本へのリンクの増減だけ注意）。"""
    return experiment_freeze.Freeze(
        experiment_start="2026-09-29", experiment_end="2026-12-31",
        edit_ban=frozenset({"agentforce-pricing", "agentforce-rag"}),
        link_ban=frozenset({"agentforce-pricing", "agentforce-rag"}),
        prompt_pages=experiment_freeze.load_prompt_pages(),
        pillars=frozenset({"agentforce-guide", "agentic-crm"}),
        unfrozen=frozenset({"agentforce-guide", "agentic-crm"}))


def test_the_lists_come_from_the_seo_agent_files(real_freeze):
    """一覧は書き写さず、seo-agent と同じ targets.csv・link_ban.csv を読む。
    2026-10-02：統計46本だけに縮小（pricing・ピラー2本を外した・本田さん決定）。"""
    assert len(real_freeze.edit_ban) == 46
    assert real_freeze.edit_ban == real_freeze.link_ban
    assert not ({"agentforce-pricing", "agentforce-guide", "agentic-crm"} & real_freeze.edit_ban)
    assert "agentforce-rag" in real_freeze.edit_ban
    # 2026-09-22 に実験から外した記事は凍結しない
    assert "agentforce-coworker" not in real_freeze.edit_ban


def test_since_10_02_no_daily_prompt_maps_to_a_frozen_page(real_freeze):
    """A-3（pricing）・B-1（agentic-crm）は凍結から外れた。ページ更新の提案は差し替えない。"""
    assert {pid for pid in real_freeze.prompt_pages if real_freeze.frozen_pages(pid)} == set()
    line = "推奨アクション: 担当者が来週末までに /agentforce-pricing/ に費用相場の表を追記する。"
    assert experiment_freeze.suppress_frozen(line, real_freeze)[0] == line


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
    # ピラーは 2026-10-02 に凍結を解いた：本文の更新も、張り先にするのも可。凍結対象外のページの更新も可
    assert any("/agentic-crm/ の本文" in l for l in lines)
    assert any("agentforce-guide/ へリンク" in l for l in lines)
    assert any("/service/btob-marketing-strategy/" in l for l in lines)
    # 状態の行(引用の事実)は触らない
    assert "状態: A-3でClaudeの回答に3観測日以上言及がない。" in lines
    assert len(notes) == 1
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
    assert len(result["frozen"]) == 1


def test_the_prompt_carries_the_constraint_only_in_the_period(freeze):
    stats = {"date": "2026-09-28"}
    assert f"凍結対象({len(freeze.edit_ban)}本)" in generate_insight.build_user_prompt(stats, [], {}, freeze=freeze)
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


def test_only_a3_maps_to_a_frozen_page(freeze):
    """B-1 の対応ページ（ピラー agentic-crm）は 2026-10-02 に凍結を解いたので当たらない。"""
    frozen = {pid for pid in freeze.prompt_pages if freeze.frozen_pages(pid)}
    assert frozen == {"A-3"}
    assert freeze.frozen_pages("A-3") == ["/agentforce-pricing/"]


@pytest.mark.parametrize("line", [
    "推奨アクション: 担当者が来週末までにA-3の自社ページを更新する。",
    "推奨アクション: 担当者が2026/10/05までにA-3の記事にFAQを追記する。",
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
    # 対応ページがピラー（2026-10-02 に凍結を解いた）
    "推奨アクション: 担当者が2026/10/05までにB-1の記事にFAQを追記する。",
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
    assert "- B-1:" not in block
    assert "- A-1:" not in block


# --------------------------------------------------------------------------
# ピラーの規則(2026-10-22。10/02 の凍結の縮小にコードを追いつかせた)
# ピラー2本・pricing は編集可。違反は統計46本(targets.csv)への提案だけ。
# ピラーから46本へのリンクを足す・外す提案は注意だけ(apply_gate が書き込み時に止める)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("line", [
    "推奨アクション: 担当者が来週末までに /agentforce-guide/ の本文に最新の料金体系の節を追記する。",
    "推奨アクション: 担当者が来週末までに https://cross-com.jp/agentic-crm/ の見出しとFAQを更新する。",
    "推奨アクション: 担当者が来週末までにピラーの本文を書き換える。",
])
def test_editing_a_pillar_is_not_a_violation(real_freeze, line):
    text, notes, _ = experiment_freeze.suppress_frozen(line, real_freeze)
    assert text == line and not notes
    assert experiment_freeze.pillar_cautions(line, real_freeze) == []


def test_editing_pricing_is_not_a_violation(real_freeze):
    line = "推奨アクション: 担当者が来週末までに /agentforce-pricing/ に費用相場の表を追記する。"
    assert experiment_freeze.suppress_frozen(line, real_freeze)[0] == line


@pytest.mark.parametrize("line,target", [
    ("推奨アクション: 担当者が来週末までに /agentforce-guide/ から /agentforce-rag/ へのリンクを追加する。",
     "/agentforce-rag/"),
    ("推奨アクション: 担当者が来週末までに /agentic-crm/ の本文から /agentforce-rag/ へのリンクを外す。",
     "/agentforce-rag/"),
    ("推奨アクション: 担当者が来週末までにピラーから関連記事へのリンクを張る。", "46本"),
])
def test_a_pillar_link_change_to_the_46_gives_a_caution(real_freeze, line, target):
    text, notes, _ = experiment_freeze.suppress_frozen(line, real_freeze)
    assert text == line and not notes, "違反ではない(差し替えない)"
    cautions = experiment_freeze.pillar_cautions(line, real_freeze)
    assert len(cautions) == 1
    assert f"46本({target})へのリンクを足す・外す" in cautions[0]
    assert "apply_gate が書き込み時に止める" in cautions[0] and cautions[0].startswith("注意(違反ではない)")


def test_a_pillar_link_to_somewhere_else_gives_no_caution(real_freeze):
    line = ("推奨アクション: 担当者が来週末までに /agentforce-guide/ から "
            "/service/agentforce-support/ へのリンクを追加する。")
    assert experiment_freeze.pillar_cautions(line, real_freeze) == []


def test_the_caution_reaches_the_job_summary(real_freeze):
    report = "推奨アクション: 担当者が来週末までに /agentforce-guide/ から /agentforce-rag/ へのリンクを追加する。"
    result = generate_insight.postprocess(report, {"date": "2026-10-19"}, [], thresholds={}, freeze=real_freeze)
    assert any(w.startswith("注意(違反ではない): ピラー(/agentforce-guide/)") for w in result["warnings"])
    assert result["frozen"] == []


@pytest.mark.parametrize("line", [
    "推奨アクション: 担当者が来週末までに /agentforce-rag/ の本文を更新する。",
    "推奨アクション: 担当者が来週末までに他記事から /agentforce-rag/ へリンクを張る。",
    # ピラーのリンクの提案でも、46本そのものを編集する書き方なら違反
    "推奨アクション: 担当者が来週末までに /agentforce-guide/ から /agentforce-rag/ へリンクを張り、"
    "/agentforce-rag/ の本文も更新する。",
])
def test_proposals_on_the_46_are_still_violations(real_freeze, line):
    text, notes, _ = experiment_freeze.suppress_frozen(line, real_freeze)
    assert text == f"推奨アクション: {NOTE}" and notes


def test_the_real_config_names_the_pillars_and_the_unfrozen_pages(real_freeze):
    assert real_freeze.pillars == {"agentforce-guide", "agentic-crm"}
    assert real_freeze.unfrozen == {"agentforce-guide", "agentic-crm", "agentforce-pricing"}
    block = experiment_freeze.prompt_block(real_freeze)
    assert "2026-10-02 に凍結を解いた(編集してよい)" in block and "/agentforce-guide/" in block
    assert "ピラー:張り先にするのは可" not in block


def test_nothing_is_a_violation_or_a_caution_after_the_release():
    freeze = experiment_freeze.load("2027-01-01")
    assert freeze is None
    for line in ("推奨アクション: 担当者が来週末までに /agentforce-rag/ の本文を更新する。",
                 "推奨アクション: 担当者が来週末までに /agentforce-guide/ から /agentforce-rag/ へのリンクを追加する。",
                 "推奨アクション: 担当者が来週末までに /agentforce-guide/ の本文を更新する。"):
        assert experiment_freeze.suppress_frozen(line, freeze) == (line, [], [])
        assert experiment_freeze.pillar_cautions(line, freeze) == []
