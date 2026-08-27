"""app/ の表示文言が日本語であることを固定するテスト.

tests/test_verdicts.py の英字検出と同じ方式(表示位置の文字列リテラルから
英単語を拾い、許可語に無ければ落とす)を app/ 配下に適用する。判定は
tests/display_text.py に集約していて、判定文テンプレートと同じ語彙で見る。

これは「画面に英語が出ていないこと」の全数保証ではない。走査できるのは
ソース上の表示位置のリテラルだけで、シートの値やデータ由来の文字列は
対象外(それらは製品名・識別コードとして英字のまま出る)。
"""
from pathlib import Path

import pytest

import display_text
from display_text import ALLOWED_WORDS, english_words

APP_DIR = Path(__file__).resolve().parent.parent / "app"
APP_FILES = sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_app_actually_has_files_to_scan():
    """走査対象が0件でテストが素通りするのを防ぐ。"""
    assert len(APP_FILES) >= 10


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.name)
def test_display_strings_are_japanese(path):
    offenders = display_text.offending_words(path.read_text(encoding="utf-8"))
    assert not offenders, "\n".join(
        f"{path.name}:{line} 「{word}」 in {text!r}" for line, word, text in offenders
    )


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.name)
def test_kgi_is_written_out_only_once_per_screen(path):
    """「成果指標(KGI)」の併記は各画面の初出だけ。2回目以降は「成果指標」。

    許可語に KGI を入れている以上、走査だけでは併記の乱発を止められない。
    """
    shown = [text for _, text in display_text.display_strings(
        path.read_text(encoding="utf-8")) if "KGI" in text]
    assert len(shown) <= 1, shown
    for text in shown:
        assert "成果指標(KGI)" in text, text


# --- 検出方式そのものの確認 --------------------------------------------------
def test_scanner_finds_english_in_a_display_call():
    assert display_text.offending_words('st.caption("rank の推移")')


def test_scanner_ignores_schema_names_that_never_reach_the_screen():
    """カラム名・タブ名は変更禁止。表示位置に無い限り検出しない。"""
    source = 'frame = common.to_frame(rows, numeric=["mention_rate_all"])'
    assert not display_text.offending_words(source)


def test_scanner_ignores_code_notation_and_markup():
    source = (
        'st.caption("`llm_observations` にデータがありません。")\n'
        "st.markdown(f\"<div style='border-left:4px solid {c}'>本文</div>\", "
        "unsafe_allow_html=True)\n"
    )
    assert not display_text.offending_words(source)


def test_scanner_reads_graph_labels_and_hover_text():
    source = 'figure.update_layout(yaxis=dict(title="rank"))'
    assert [w for _, w, _ in display_text.offending_words(source)] == ["rank"]
    source = 'go.Scatter(hovertemplate="<b>%{x}</b><br>rank %{y}<extra></extra>")'
    assert [w for _, w, _ in display_text.offending_words(source)] == ["rank"]


def test_identifier_values_stay_in_english():
    """R1〜R8・A-001・R-P7・E-1 は値なので検出しない(ラベルは日本語)。"""
    assert english_words("R3の判定、A-001とR-P7、E-1 × P4") == []


def test_established_abbreviations_are_allowed():
    for word in ("AI", "KBF", "CEP", "URL"):
        assert word in ALLOWED_WORDS


# --- ラベル辞書 --------------------------------------------------------------
def test_column_labels_cover_the_headers_shown_in_tables():
    import labels

    for column in ("date", "prompt_id", "model", "action_id", "rank", "mention"):
        assert column in labels.COLUMN_LABELS, column


def test_ja_columns_renames_only_what_it_knows():
    import pandas as pd

    import labels

    frame = pd.DataFrame([{"date": "2026-08-24", "内容": "x", "未知の列": 1}])
    renamed = labels.ja_columns(frame)
    assert list(renamed.columns) == ["日付", "内容", "未知の列"]
    assert list(frame.columns) == ["date", "内容", "未知の列"]  # 元は変えない


def test_pillar_labels_say_what_the_pillar_contains():
    import labels

    assert labels.pillar("A") == "Agentforce系(A)"
    assert labels.pillar("B") == "Agentic CRM系(B)"
    assert labels.pillar("all").startswith("全体")
    assert labels.pillar("Z") == "Z"  # 未知の値はそのまま


def test_rule_status_values_display_as_japanese():
    import labels

    assert labels.status("fired") == "発火"
    assert labels.status("not_fired") == "非発火"
    assert labels.status("insufficient_data") == "判定不能"
    assert labels.status("unknown") == "unknown"  # 未知の値はそのまま


def test_change_rows_translate_the_type_and_the_boolean_sides():
    import labels

    rows = [
        {"change_type": "mention_lost", "before": "True", "after": "False",
         "detail": ""},
        {"change_type": "rank_up", "before": "4", "after": "2", "detail": ""},
    ]
    shown = labels.change_rows(rows)
    assert shown[0]["change_type"] == "言及が消えた"
    assert (shown[0]["before"], shown[0]["after"]) == ("あり", "なし")
    # 順位の行は値が真偽値ではないので触らない
    assert shown[1]["change_type"] == "順位が上がった"
    assert (shown[1]["before"], shown[1]["after"]) == ("4", "2")
    assert rows[0]["change_type"] == "mention_lost"  # 元の行は変えない


def test_boolean_values_display_as_japanese():
    import labels

    assert labels.yes_no("TRUE") == "あり"
    assert labels.yes_no("FALSE") == "なし"
    assert labels.yes_no("") == ""
