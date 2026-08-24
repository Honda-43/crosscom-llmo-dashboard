"""判定欄テンプレートのテスト(Phase 5 §2 / DoD 2・6).

判定欄は毎週同じ基準で読まれる。同じ状態なら同じ文が出ること、
文面がテンプレート由来であること(YAMLを変えれば文が変わること)を固定する。
"""
import pytest

import verdicts

TODAY = "2026-08-24"

ACTIONS = [
    {"action_id": "A-001", "優先度": "高", "内容": "外部プロフィール更新", "対象": "E-1",
     "根拠rule_id": "R-P7", "状態": verdicts.STATUS_MEASURING,
     "提案日": "2026-08-08", "実施日": "2026-08-11", "判断期限": "2026-09-07"},
    {"action_id": "A-006", "優先度": "中", "内容": "外部プロフィール第2弾", "対象": "E-1",
     "根拠rule_id": "R-P7", "状態": verdicts.STATUS_ON_HOLD,
     "提案日": "2026-08-24", "実施日": "—", "判断期限": "2026-09-07"},
]


def context(**overrides):
    return verdicts.build_context(TODAY, ACTIONS, **overrides)


# --- 分岐 ------------------------------------------------------------------
def test_r3_within_effect_window_says_it_is_expected():
    """施策から28日以内に検知が続くのは想定内、と言い切る分岐。"""
    text = verdicts.render("R3", context(negative_streak_days=5))
    assert text.startswith(verdicts.VERDICT_PREFIX)
    assert "外部プロフィール更新" in text
    assert "13日" in text          # 8/11 -> 8/24
    assert "2026-09-07" in text    # 判断期限
    assert "想定内" in text


def test_r3_over_window_switches_to_the_next_action():
    late = verdicts.build_context("2026-09-30", ACTIONS, negative_streak_days=30)
    text = verdicts.render("R3", late)
    assert "外部プロフィール第2弾" in text   # 次の施策(保留中のもの)
    assert "想定内" not in text


def test_r3_stopped_declares_the_effect():
    text = verdicts.render("R3", context(negative_streak_days=0))
    assert "検知停止" in text
    assert verdicts.rule_id_for("R3", context(negative_streak_days=0)) == "r3_stopped"


def test_every_face_has_at_least_two_branches():
    """§2: 各面に最低2分岐(正常系/要対応系)。"""
    faces = verdicts.load_templates()["faces"]
    for face, rules in faces.items():
        assert len(rules) >= 2, face


def test_every_face_renders_for_an_empty_state():
    """データが無くても必ず何か1文は出る(既定分岐がある)。"""
    empty = verdicts.build_context(TODAY, [])
    for face in verdicts.load_templates()["faces"]:
        text = verdicts.render(face, empty)
        assert text and text.startswith(verdicts.VERDICT_PREFIX), face


def test_r4_branches_on_zero_cells():
    assert verdicts.rule_id_for("R4", context(zero_cells=3)) == "r4_has_zero_cells"
    assert verdicts.rule_id_for("R4", context(zero_cells=0)) == "r4_all_covered"


def test_r5_branches_on_share_rank():
    assert verdicts.rule_id_for("R5", context(self_share_rank=1)) == "r5_leader"
    assert verdicts.rule_id_for("R5", context(self_share_rank=3)) == "r5_challenger"
    assert verdicts.rule_id_for("R5", context(self_share_rank=8)) == "r5_behind"


def test_r7_branches_on_noise():
    assert verdicts.rule_id_for("R7", context(kgi_noise=True)) == "r7_noise"
    assert verdicts.rule_id_for("R7", context(kgi_noise=False)) == "r7_measurable"


# --- テンプレート由来であること(DoD 2) --------------------------------------
def test_text_comes_from_the_yaml_not_from_code():
    """YAMLを差し替えれば文面が変わる。コード側に文言を持たない。"""
    custom = {"faces": {"R3": [{"id": "x", "when": {}, "text": "差し替え {negative_streak_days}日"}]}}
    text = verdicts.render("R3", context(negative_streak_days=4), templates=custom)
    assert text == f"{verdicts.VERDICT_PREFIX}差し替え 4日"


def test_unknown_placeholder_is_an_error_not_a_blank():
    """テンプレートの変数名を間違えたら静かに空欄にせず落とす。"""
    broken = {"faces": {"R1": [{"id": "x", "when": {}, "text": "{存在しない変数}"}]}}
    with pytest.raises(verdicts.MissingPlaceholder):
        verdicts.render("R1", context(), templates=broken)


def test_shipped_templates_have_no_missing_placeholders():
    """出荷しているYAMLが、どの分岐でも埋められること。"""
    scenarios = [
        context(negative_streak_days=5, zero_cells=2, self_share_rank=1, kgi_noise=True),
        context(negative_streak_days=0, zero_cells=0, self_share_rank=3, kgi_noise=False,
                mention_rate_delta_7d=0.1),
        context(negative_streak_days=1, self_share_rank=9, absent_domains=4,
                mention_rate_delta_7d=-0.1),
        verdicts.build_context(TODAY, []),
    ]
    for scenario in scenarios:
        for face in verdicts.load_templates()["faces"]:
            verdicts.render(face, scenario)  # MissingPlaceholder が出ないこと


def test_no_english_or_metaphor_in_shipped_templates():
    """§8: 英語表記を使わない(rule_id と製品名を除く)。"""
    import re

    # 製品名・システム名は除外対象。Pillar はこのシステムの観測区分名。
    allowed = {"R", "P", "KGI", "SoV", "AI", "Looker", "Studio", "Agentforce",
               "CRM", "Organization", "MA", "TRUE", "FALSE", "Pillar"}
    for face, rules in verdicts.load_templates()["faces"].items():
        for rule in rules:
            body = re.sub(r"\{[^}]+\}", "", rule["text"])
            body = re.sub(r"R-P\d+|R-DROP", "", body)          # rule_id
            # スキーマのカラム名・タブ名はシステム名として扱う
            body = re.sub(r"prompt_id|action_log|mention_rate|sov_daily"
                          r"|llm_observations|rank", "", body)
            for word in re.findall(r"[A-Za-z]{2,}", body):
                assert word in allowed, f"{face}/{rule['id']}: {word}"


# --- 施策の縦線注釈(§4) ----------------------------------------------------
def test_only_implemented_actions_are_annotated():
    annotated = verdicts.implemented_actions(ACTIONS)
    assert [a["action_id"] for a in annotated] == ["A-001"]   # 保留は出さない
    assert annotated[0]["label"] == "外部プロフィール更新"[:12]


def test_annotation_label_is_truncated_to_twelve_characters():
    rows = [{"action_id": "A-999", "内容": "あ" * 30, "状態": verdicts.STATUS_MEASURING,
             "実施日": "2026-08-01", "判断期限": "—"}]
    assert verdicts.implemented_actions(rows)[0]["label"] == "あ" * 12


def test_actions_without_a_done_date_are_skipped():
    rows = [{"action_id": "A-998", "内容": "x", "状態": verdicts.STATUS_MEASURING,
             "実施日": "—", "判断期限": "—"}]
    assert verdicts.implemented_actions(rows) == []
