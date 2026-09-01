"""比較型観測のKBF別集計のテスト(Phase 3 追加).

**優劣は判定しない。**入るのは「その軸を誰が語ったか」だけ。
月次サマリが比較を「要目視」と出しているのと揃えている。
"""
import kbf_compare
import sheets_writer
from extract import KBF_TAG_OPTIONS

RIVAL = "テクノデジタルコンサルティング"


def _rec(answer, model="claude", pid="M-7", category="bofu_compare"):
    return {"prompt_id": pid, "model": model, "category": category,
            "target_brand": RIVAL, "answer": answer, "error": None}


# --- 手がかり語の定義 -------------------------------------------------------
def test_every_pattern_maps_to_an_approved_kbf_tag():
    """§4の選択肢は変更禁止。勝手なタグを増やさない。"""
    assert set(kbf_compare.KBF_PATTERNS) <= KBF_TAG_OPTIONS


def test_the_other_tag_is_not_aggregated():
    """「その他」は手がかり語を定義できないので集計しない。"""
    assert "その他" not in kbf_compare.KBF_PATTERNS


# --- 文脈の切り分け ---------------------------------------------------------
def test_a_kbf_near_our_name_is_ours():
    text = "クロスコムはベンダー中立の立場で設計から入ります。"
    assert kbf_compare.classify(text, RIVAL)["ベンダー中立"] == "self"


def test_a_kbf_near_the_rival_is_theirs():
    text = f"{RIVAL}はベンダーニュートラルな立場を取ります。"
    assert kbf_compare.classify(text, RIVAL)["ベンダー中立"] == "rival"


def test_a_kbf_claimed_by_both_is_both():
    text = (f"クロスコムは定着支援に強みがあります。"
            f"一方{RIVAL}も定着まで伴走します。")
    assert kbf_compare.classify(text, RIVAL)["定着支援"] == "both"


def test_an_absent_kbf_is_neither():
    text = "クロスコムとテクノデジタルコンサルティングを比較します。"
    assert kbf_compare.classify(text, RIVAL)["実績・事例"] == "neither"


def test_the_nearest_company_wins_when_both_appear():
    """比較回答は社ごとの節に分かれるので、近さで切り分けられる。"""
    text = ("クロスコムの説明です。" + "あ" * 300
            + f"{RIVAL}は20年以上・100社以上の実績があります。")
    assert kbf_compare.classify(text, RIVAL)["実績・事例"] == "rival"


# --- 行の生成 ---------------------------------------------------------------
def test_rows_cover_every_kbf_for_each_model():
    rows = kbf_compare.rows_from_records(
        "2026-09", [_rec("クロスコムは設計支援を行います。", model="claude"),
                    _rec("クロスコムは設計支援を行います。", model="gemini")])
    assert len(rows) == 2 * len(kbf_compare.KBF_PATTERNS)
    assert {r["model"] for r in rows} == {"claude", "gemini"}


def test_non_comparison_records_are_ignored():
    rows = kbf_compare.rows_from_records(
        "2026-09", [_rec("クロスコムの評判です。", pid="M-1", category="bofu_single")])
    assert rows == []


def test_a_failed_observation_is_skipped():
    rec = _rec("")
    rec["error"] = "503 UNAVAILABLE"
    assert kbf_compare.rows_from_records("2026-09", [rec]) == []


def test_the_row_matches_the_sheet_schema():
    rows = kbf_compare.rows_from_records("2026-09", [_rec("クロスコムは定着支援。")])
    assert set(rows[0]) == set(sheets_writer.HEADERS_KBF_COMPARE)
    assert rows[0]["month"] == "2026-09"


def test_self_and_rival_flags_follow_diff():
    rows = kbf_compare.rows_from_records(
        "2026-09", [_rec(f"クロスコムは定着支援。{RIVAL}も定着支援。")])
    row = next(r for r in rows if r["kbf"] == "定着支援")
    assert (row["diff"], row["self_eval"], row["rival_eval"]) == ("both", "TRUE", "TRUE")


def test_the_target_brand_falls_back_to_the_prompt_definition():
    """生レコードに target_brand が無くても、プロンプト定義から引ける。"""
    rec = _rec(f"{RIVAL}はベンダーニュートラルです。")
    rec.pop("target_brand")
    rows = kbf_compare.rows_from_records(
        "2026-09", [rec], [{"id": "M-7", "target_brand": RIVAL}])
    assert next(r for r in rows if r["kbf"] == "ベンダー中立")["diff"] == "rival"


# --- サマリ -----------------------------------------------------------------
def test_the_summary_names_axes_only_the_rival_used():
    """埋めるべき軸を出すのがこの集計の目的。"""
    rows = kbf_compare.rows_from_records(
        "2026-09", [_rec(f"{RIVAL}はベンダーニュートラルな立場です。")])
    assert any("競合のみが語った軸" in s and "ベンダー中立" in s
               for s in kbf_compare.summary(rows))


def test_the_summary_is_explicit_when_there_is_no_difference():
    assert kbf_compare.summary([]) == ["比較型のKBF差分なし"]


# --- スキーマ ---------------------------------------------------------------
def test_the_sheet_keys_make_rows_idempotent():
    assert sheets_writer.KEYS_KBF_COMPARE == ["month", "prompt_id", "model", "kbf"]


def test_no_verdict_column_exists():
    """優劣は機械で取れない。取れたことにしない。"""
    assert not {"winner", "score", "verdict"} & set(sheets_writer.HEADERS_KBF_COMPARE)
