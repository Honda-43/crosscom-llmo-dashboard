"""action_log のテスト(Phase 5 §4 / §5 / DoD 6)."""
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
