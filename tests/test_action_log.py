"""action_log のテスト(Phase 5 §4 / §5 / DoD 6)."""
import pytest

import action_log
import verdicts

DATE = "2026-08-31"

EXISTING = [
    {"action_id": "A-001", "内容": "外部プロフィール更新", "根拠rule_id": "R-P7",
     "状態": verdicts.STATUS_MEASURING},
    {"action_id": "A-007", "内容": "B-3対応の一次情報ページ更新", "根拠rule_id": "R-P2",
     "状態": verdicts.STATUS_ON_HOLD},
    {"action_id": "A-002", "内容": "完了済みの施策", "根拠rule_id": "R-P8",
     "状態": verdicts.STATUS_DONE},
]


# --- 重複防止(§5) ----------------------------------------------------------
def test_duplicate_proposal_is_not_appended():
    proposals = [{"内容": "外部プロフィール更新", "根拠rule_id": "R-P7"}]
    assert action_log.propose(proposals, EXISTING, DATE) == []


def test_same_content_with_a_different_rule_is_appended():
    proposals = [{"内容": "外部プロフィール更新", "根拠rule_id": "R-P8"}]
    assert len(action_log.propose(proposals, EXISTING, DATE)) == 1


def test_a_completed_action_does_not_block_a_new_proposal():
    """完了済みは「未完了状態で存在」に当たらないので、再提案できる。"""
    proposals = [{"内容": "完了済みの施策", "根拠rule_id": "R-P8"}]
    assert len(action_log.propose(proposals, EXISTING, DATE)) == 1


def test_on_hold_counts_as_open_and_blocks():
    proposals = [{"内容": "B-3対応の一次情報ページ更新", "根拠rule_id": "R-P2"}]
    assert action_log.propose(proposals, EXISTING, DATE) == []


def test_duplicates_within_one_batch_are_collapsed():
    proposals = [{"内容": "新しい施策", "根拠rule_id": "R-P7"},
                 {"内容": "新しい施策", "根拠rule_id": "R-P7"}]
    assert len(action_log.propose(proposals, EXISTING, DATE)) == 1


def test_matching_ignores_spacing_and_punctuation():
    proposals = [{"内容": "外部 プロフィール・更新", "根拠rule_id": "R-P7"}]
    assert action_log.propose(proposals, EXISTING, DATE) == []


# --- 採番と既定値 -------------------------------------------------------------
def test_new_id_continues_the_sequence():
    rows = action_log.propose([{"内容": "新しい施策", "根拠rule_id": "R-P7"}],
                              EXISTING, DATE)
    assert rows[0]["action_id"] == "A-008"


def test_first_id_when_the_log_is_empty():
    rows = action_log.propose([{"内容": "最初の施策", "根拠rule_id": "—"}], [], DATE)
    assert rows[0]["action_id"] == "A-001"


def test_proposed_rows_start_in_the_proposed_state():
    row = action_log.propose([{"内容": "新しい施策", "根拠rule_id": "R-P7"}],
                             EXISTING, DATE)[0]
    assert row["状態"] == verdicts.STATUS_PROPOSED
    assert row["提案日"] == DATE
    assert row["実施日"] == "—"


def test_row_uses_the_approved_columns():
    row = action_log.propose([{"内容": "新しい施策", "根拠rule_id": "R-P7"}], [], DATE)[0]
    assert set(row) == {"action_id", "優先度", "内容", "対象", "根拠rule_id",
                        "状態", "提案日", "実施日", "判断期限"}


# --- action_id / 状態 / 実施日 の明示指定 -------------------------------------
def test_an_explicit_action_id_is_used_as_is():
    """別系統で採番済みの番号や欠番を、自動採番に上書きさせない。"""
    row = action_log.propose(
        [{"action_id": "A-012", "内容": "番号を指定した施策", "根拠rule_id": "R-P7"}],
        EXISTING, DATE)[0]
    assert row["action_id"] == "A-012"


def test_the_auto_numbering_still_works_without_an_id():
    row = action_log.propose([{"内容": "新しい施策", "根拠rule_id": "R-P7"}],
                             EXISTING, DATE)[0]
    assert row["action_id"] == "A-008"


def test_a_colliding_action_id_raises():
    """黙って上書きすると本田さんが編集した状態列が消える。"""
    with pytest.raises(ValueError, match="既に存在"):
        action_log.propose(
            [{"action_id": "A-001", "内容": "衝突する施策", "根拠rule_id": "R-P8"}],
            EXISTING, DATE)


def test_a_malformed_action_id_raises():
    with pytest.raises(ValueError, match="形式"):
        action_log.propose(
            [{"action_id": "X-1", "内容": "不正な番号", "根拠rule_id": "R-P8"}],
            EXISTING, DATE)


def test_an_explicit_status_and_done_date_are_kept():
    """承認済み・実施済みの施策を後から記録できる。"""
    row = action_log.propose(
        [{"action_id": "A-011", "内容": "実施済みの施策", "根拠rule_id": "R-P7",
          "状態": verdicts.STATUS_MEASURING, "実施日": "2026-09-01"}],
        EXISTING, DATE)[0]
    assert row["状態"] == verdicts.STATUS_MEASURING
    assert row["実施日"] == "2026-09-01"


def test_the_status_defaults_to_proposed():
    row = action_log.propose([{"内容": "既定の施策", "根拠rule_id": "R-P7"}],
                             EXISTING, DATE)[0]
    assert row["状態"] == verdicts.STATUS_PROPOSED
    assert row["実施日"] == "—"


def test_ids_within_one_batch_do_not_collide():
    """明示した番号より後の自動採番は、その番号の次から続ける。

    A-008 に戻すと、次に自動採番したときに A-020 と衝突しうる。
    番号が飛んでも単調増加を保つほうが安全。
    """
    rows = action_log.propose(
        [{"action_id": "A-020", "内容": "施策X", "根拠rule_id": "R-P7"},
         {"内容": "施策Y", "根拠rule_id": "R-P7"}], EXISTING, DATE)
    assert [r["action_id"] for r in rows] == ["A-020", "A-021"]


# --- 所見文からの抽出(§5) --------------------------------------------------
REPORT = """## 3. 発火パターンと推奨アクション

**R-P8(旧事業URLの引用)**
状態: 旧パスが2件引用されている。
原因仮説: 旧記事が権威を持ったまま残っている。
アクション: 担当者が来週末までに2URLを301で現行ページに統合する。

**R-P2(言及消失)**
状態: B-3で6観測日連続の消失。
アクション: B-3対応の一次情報ページ更新。
"""


def test_actions_are_extracted_with_their_rule_id():
    proposals = action_log.extract_proposals(REPORT)
    assert len(proposals) == 2
    assert proposals[0]["根拠rule_id"] == "R-P8"
    assert "301で現行ページに統合する" in proposals[0]["内容"]
    assert proposals[1]["根拠rule_id"] == "R-P2"


def test_sync_skips_what_is_already_open():
    rows = action_log.sync_from_report(REPORT, DATE, existing=EXISTING)
    contents = [r["内容"] for r in rows]
    assert not any("B-3対応の一次情報ページ更新" in c for c in contents)
    assert len(rows) == 1


def test_report_without_actions_yields_nothing():
    assert action_log.extract_proposals("## 1. 今週のサマリ\n\n順調です。") == []


def test_the_recommended_action_label_is_also_extracted():
    """見出しは「推奨アクション:」に統一したが、過去の「アクション:」も読む。"""
    report = "**R-P7(x)**\n推奨アクション: 担当者がページを修正する。\n"
    proposals = action_log.extract_proposals(report)
    assert len(proposals) == 1
    assert proposals[0]["根拠rule_id"] == "R-P7"


# --- 実施済み施策の再提案の抑止(Phase 7 §A) --------------------------------
SETTLED_LOG = [
    {"action_id": "A-003", "内容": "/btob-marketing-strategy/ 過去形化改修",
     "対象": "E-1", "根拠rule_id": "R-P8", "状態": verdicts.STATUS_MEASURING,
     "提案日": "2026-08-24", "実施日": "2026-08-24"},
    {"action_id": "A-009", "内容": "B-3のCEP対応ページ新設", "対象": "B-3",
     "根拠rule_id": "R-P2", "状態": verdicts.STATUS_DONE,
     "提案日": "2026-08-10", "実施日": "2026-08-12"},
    {"action_id": "A-010", "内容": "承認だけ済んでいる施策", "対象": "A-1",
     "根拠rule_id": "R-P5", "状態": verdicts.STATUS_APPROVED,
     "提案日": "2026-08-29", "実施日": "—"},
    {"action_id": "A-011", "内容": "まだ保留の施策", "対象": "A-2",
     "根拠rule_id": "R-P4", "状態": verdicts.STATUS_ON_HOLD,
     "提案日": "2026-08-29", "実施日": "—"},
]

SETTLED_REPORT = """## 3. 発火パターンと推奨アクション

**R-P8(旧事業URLの引用)**
状態: AIの回答はE-1で旧パスを2件引用している。
推奨アクション: 担当者が来週末までに301統合する。

**R-P4(言及率の改善)**
状態: A-2で言及率が上がった。
推奨アクション: 担当者が来週末までに横展開する。
"""


def test_only_settled_states_are_collected():
    ids = [r["action_id"] for r in action_log.settled_actions(SETTLED_LOG)]
    assert ids == ["A-003", "A-009", "A-010"]


def test_the_note_names_the_action_and_its_date():
    assert action_log.settled_note(SETTLED_LOG[0]) == \
        "実施済み(A-003・2026-08-24)。効果測定中"


def test_a_completed_action_says_completed():
    assert action_log.settled_note(SETTLED_LOG[1]) == "実施済み(A-009・2026-08-12)。完了"


def test_an_approved_action_has_no_implementation_date():
    """承認だけ済んでいる施策に「実施済み」と書くと嘘になる。"""
    note = action_log.settled_note(SETTLED_LOG[2])
    assert note.startswith("承認済み(A-010・2026-08-29)")
    assert "実施済み" not in note


def test_a_settled_action_replaces_the_recommendation():
    text, notes = action_log.suppress_settled(SETTLED_REPORT, SETTLED_LOG)
    assert "推奨アクション: 実施済み(A-003・2026-08-24)。効果測定中" in text
    assert "301統合" not in text
    assert len(notes) == 1


def test_an_open_action_does_not_suppress_anything():
    """保留(A-011/R-P4/A-2)は決着していないので、提案を止める理由にならない。"""
    text, notes = action_log.suppress_settled(SETTLED_REPORT, SETTLED_LOG)
    assert "横展開する" in text
    assert not any("R-P4" in n for n in notes)


def test_the_same_rule_on_a_different_target_is_not_suppressed():
    report = ("**R-P8(旧事業URLの引用)**\n"
              "状態: AIの回答はB-1で旧パスを引用している。\n"
              "推奨アクション: 担当者が301統合する。\n")
    text, notes = action_log.suppress_settled(report, SETTLED_LOG)
    assert "301統合" in text
    assert notes == []


def test_the_note_is_added_when_the_model_wrote_no_action_line():
    """モデルが指示どおり提案を落とした場合も、実施済みであることは書く。"""
    report = ("**R-P8(旧事業URLの引用)**\n"
              "状態: AIの回答はE-1で旧パスを2件引用している。\n")
    text, notes = action_log.suppress_settled(report, SETTLED_LOG)
    assert "実施済み(A-003・2026-08-24)。効果測定中" in text
    assert len(notes) == 1


def test_an_empty_action_log_changes_nothing():
    assert action_log.suppress_settled(SETTLED_REPORT, []) == (SETTLED_REPORT, [])


def test_every_settled_action_is_listed_for_the_prompt():
    block = action_log.prompt_block(SETTLED_LOG)
    assert "A-003" in block and "A-010" in block
    assert "A-011" not in block, "保留は着手済みではない"


# --- 初期データ(§4) ---------------------------------------------------------
def test_seed_rows_match_the_spec():
    assert len(action_log.SEED_ROWS) == 7
    assert [r["action_id"] for r in action_log.SEED_ROWS] == [
        "A-001", "A-002", "A-003", "A-004", "A-005", "A-006", "A-007"]


def test_five_seed_actions_are_annotated_on_charts():
    """A-001〜A-005 は実施済みなのでR2・R3に縦線が出る(DoD 3)。"""
    annotated = verdicts.implemented_actions(action_log.SEED_ROWS)
    assert [a["action_id"] for a in annotated] == [
        "A-001", "A-002", "A-003", "A-004", "A-005"]
