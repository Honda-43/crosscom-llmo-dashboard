"""週次所見の記述ルール検査(scripts/check_insight_style.py)のテスト.

検査そのものが素通りしていないことを固定する。「OKと出た」だけでは、
検査が働いていないのか本当に満たしているのかが区別できない。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_insight_style as chk  # noqa: E402
import insight_style  # noqa: E402

GOOD = """## 1. 今週のサマリ
発火 2件。

## 2. 数値ハイライト
言及率は48%、前週比 横ばい(+2ポイント)。

## 3. 発火パターンと推奨アクション

**R-P7(ネガティブ・古い情報:直近7日の回答に終了事業または誤った記述がある)**
状態: 16件検知。
原因仮説: 旧事業の記述が残っている。
推奨アクション: 実施済み(A-001・2026-08-11)。効果測定中

## 4. ウォッチ項目
なし。

## 5. 判定不能・データ不足
なし。
"""

ACTIONS = [{"action_id": "A-001", "根拠rule_id": "R-P7", "対象": "E-1",
            "状態": "実施済み・効果測定中", "実施日": "2026-08-11"}]


def test_a_clean_report_passes_every_check():
    results = chk.run(GOOD, {"rules": []}, ACTIONS)
    assert [s for s, _ in results.values()].count(chk.NG) == 0


# --- 各検査が実際に落ちること ------------------------------------------------
@pytest.mark.parametrize("word", ["押し出", "定着", "供給", "浮上"])
def test_banned_words_are_caught(word):
    status, notes = chk.check_banned_words(f"状態: 競合が{word}している。")
    assert status == chk.NG and notes


def test_the_service_name_is_not_treated_as_a_metaphor():
    """「Agentforce導入・定着支援」は事業名。ここだけ「定着」を許す。"""
    assert chk.check_banned_words("Agentforce導入・定着支援の面。")[0] == chk.OK


def test_a_missing_bullet_label_is_caught():
    text = GOOD.replace("原因仮説: 旧事業の記述が残っている。\n", "")
    status, notes = chk.check_bullets(text)
    assert status == chk.NG
    assert any(insight_style.LABEL_CAUSE in n for n in notes)


def test_an_arrow_is_caught():
    text = GOOD.replace("推奨アクション: 実施済み", "推奨アクション → 実施済み")
    assert chk.check_bullets(text)[0] == chk.NG


def test_the_fallback_report_skips_the_bullet_check():
    """フォールバックは推奨アクションを書かない設計。3行の検査はかけない。"""
    text = f"この所見には{chk.FALLBACK_MARK}。\n\n**R-P7**\n状態: 16件。"
    status, notes = chk.check_bullets(text)
    assert status == chk.SKIP and "フォールバック" in notes[0]


def test_a_re_proposed_action_is_caught():
    """打ってある施策が推奨アクションとして出ていたら落とす。"""
    text = GOOD.replace("推奨アクション: 実施済み(A-001・2026-08-11)。効果測定中",
                        "推奨アクション: E-1の旧事業記述を直す。")
    status, notes = chk.check_suppression(text, ACTIONS)
    assert status == chk.NG
    assert any("A-001" in n for n in notes)


def test_suppression_is_skipped_when_nothing_has_been_done():
    assert chk.check_suppression(GOOD, [])[0] == chk.SKIP


CO_FIRED = {"rules": [
    {"rule_id": "R-P2", "status": "fired", "fired": True,
     "evidence": [{"prompt_id": "B-3"}]},
    {"rule_id": "R-P15", "status": "fired", "fired": True,
     "evidence": [{"prompt_id": "B-3"}]},
]}
SEPARATE = """## 3. 発火パターンと推奨アクション

**R-P2 — B-3**
状態: 言及消失。
原因仮説: 一次情報が薄い。
推奨アクション: ページを更新する。

**R-P15 — B-3**
状態: 競合が4週連続。
原因仮説: 競合の記述が厚い。
推奨アクション: 競合の引用ページを調べる。
"""


def test_separate_co_fired_items_are_caught():
    status, notes = chk.check_merged_heading(SEPARATE, CO_FIRED)
    assert status == chk.NG
    assert "別項目のまま" in notes[0]


def test_the_merge_makes_it_pass():
    """insight_style.merge_co_fired を通すと OK になる(検査と実装の整合)。"""
    merged = insight_style.merge_co_fired(
        SEPARATE, insight_style.co_fired_prompts(CO_FIRED))
    assert chk.check_merged_heading(merged, CO_FIRED)[0] == chk.OK


def test_the_merge_check_is_skipped_without_a_co_firing():
    assert chk.check_merged_heading(GOOD, {"rules": []})[0] == chk.SKIP


def test_a_bare_decimal_is_caught():
    assert chk.check_notation(GOOD.replace("48%", "0.4818"))[0] == chk.NG


def test_a_missing_section_is_caught():
    assert chk.check_notation(GOOD.replace("## 4. ウォッチ項目", "## 4. その他"))[0] == chk.NG


def test_a_rule_without_a_definition_is_caught():
    text = "**R-P7**\n状態: 16件検知。"
    status, notes = chk.check_glossary(text)
    assert status == chk.NG and "説明なし" in notes[0]


def test_a_summary_list_does_not_count_as_a_missing_definition():
    """「発火パターン 2件(R-P7)」のような列挙は説明の場ではない。

    本文のどこかに定義があれば満たしているとみなす。
    """
    text = "発火パターン 1件(R-P7)。\n\n**R-P7(ネガティブ・古い情報:直近7日の回答に終了事業または誤った記述がある)**"
    assert chk.check_glossary(text)[0] == chk.OK
