"""Unit tests for normalize_entity / resolve_entity (Phase 1 §6-1)."""
import pytest

from normalize import is_excluded, normalize_entity, resolve_entity


@pytest.mark.parametrize(
    "raw, expected",
    [
        # --- full-width -> half-width (NFKC) ---
        ("三菱総研ＤＣＳ", "三菱総研DCS"),
        ("ＤＣＳ", "三菱総研DCS"),
        # --- legal entity forms, head and tail ---
        ("合同会社クロスコム", "クロスコム"),
        ("クロスコム合同会社", "クロスコム"),
        ("株式会社日立ソリューションズ", "日立ソリューションズ"),
        ("(株)日立ソリューションズ", "日立ソリューションズ"),
        ("㈱日立ソリューションズ", "日立ソリューションズ"),
        ("Deloitte Tohmatsu Consulting LLC", "Deloitte Tohmatsu Consulting"),
        ("Accenture Inc.", "Accenture"),
        ("Fujitsu Co., Ltd.", "Fujitsu"),
        # --- alias table ---
        ("cross-com", "クロスコム"),
        ("CROSSCOM", "クロスコム"),
        ("Crosscom", "クロスコム"),
        ("船井総研", "船井総合研究所"),
        ("01GROWTH", "ゼロワングロース"),
        ("100inc", "ハンドレッド"),
        # --- the composite case from §6-1 ---
        ("株式会社メンバーズ サースプラスカンパニー", "メンバーズ"),
        ("メンバーズ・サースプラスカンパニー", "メンバーズ"),
        ("メンバーズサースプラスカンパニー", "メンバーズ"),
        ("　メンバーズ　サースプラスカンパニー　", "メンバーズ"),
        # --- unknown companies: normalised, kept as-is (§2-1) ---
        ("株式会社アクセンチュア", "アクセンチュア"),
        ("  ベイカレント・コンサルティング ", "ベイカレントコンサルティング"),
        ("Some New Vendor", "Some New Vendor"),
        # --- empty / junk ---
        ("", ""),
        ("   ", ""),
        (None, ""),
    ],
)
def test_normalize_entity(raw, expected):
    assert normalize_entity(raw) == expected


def test_latin_word_ending_in_legal_letters_is_not_truncated():
    """"Marco" must not lose "co", "Limitedly" must not lose "Limited"."""
    assert normalize_entity("Marco") == "Marco"
    assert normalize_entity("Incubate") == "Incubate"


def test_a_bare_legal_form_is_not_erased_but_is_not_counted():
    """正規化では消さない(情報を失わない)が、集計には入れない。"""
    assert normalize_entity("株式会社") == "株式会社"
    assert normalize_entity("Inc.") != ""
    assert resolve_entity("株式会社") is None
    assert resolve_entity("(株)") is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("株式会社100（100inc）", "ハンドレッド"),
        ("株式会社100 (100 Inc.)", "ハンドレッド"),
        ("三菱総研DCS(DCS)", "三菱総研DCS"),
        ("EYストラテジー・アンド・コンサルティング株式会社（EYSC）", "EYストラテジーアンドコンサルティング"),
    ],
)
def test_parenthetical_annotations_are_dropped(raw, expected):
    """「社名(略称)」形式の注記は名前の一部ではない。"""
    assert resolve_entity(raw) == expected


def test_a_fully_parenthesised_value_is_not_erased():
    """括弧しかない場合は削り切らない(除去して空になるなら元を残す)。"""
    assert normalize_entity("(株)") == "(株)"


def test_normalize_entity_is_idempotent():
    for raw in ["株式会社メンバーズ サースプラスカンパニー", "三菱総研ＤＣＳ", "Some New Vendor"]:
        once = normalize_entity(raw)
        assert normalize_entity(once) == once


# --- 「株式会社100」問題:法人格を取ると数字だけが残るケース ----------------
@pytest.mark.parametrize(
    "raw", ["株式会社100", "100inc", "100Inc", "100 Inc", "100 Inc.", "株式会社１００", "100"],
)
def test_hyaku_inc_resolves_to_one_entity(raw):
    """観測データ上の「株式会社100（100inc）」は全て同一企業に解決される。"""
    assert resolve_entity(raw) == "ハンドレッド"


def test_hyaku_inc_and_zeroone_growth_are_separate_companies():
    """株式会社100(100inc)とゼロワングロース(01GROWTH)は別会社。"""
    assert resolve_entity("01GROWTH") == "ゼロワングロース"
    assert resolve_entity("ゼロワングロース") == "ゼロワングロース"
    assert resolve_entity("100inc") != resolve_entity("01GROWTH")


def test_an_explicit_alias_beats_the_no_letter_guard():
    """YAMLに載っている値は、数字だけでもゴミ扱いしない。"""
    assert resolve_entity("100") == "ハンドレッド"
    assert resolve_entity("2018") is None


def test_stripping_a_legal_form_never_leaves_a_bare_number():
    """数字しか残らない除去は行わない(sov_dailyに「100」行が出た直接原因)。"""
    assert normalize_entity("株式会社2020") == "株式会社2020"
    assert normalize_entity("株式会社100") != "100"


def test_bare_numeric_fragments_are_excluded_from_aggregation():
    """エイリアスに載っていない数字・記号だけの断片は集計に入れない。"""
    for junk in ["2018", "―", "()", "", "   ", "999"]:
        assert resolve_entity(junk) is None, junk


# --- EY:Latin↔CJK境界の空白ゆれ -------------------------------------------
def test_latin_cjk_boundary_space_is_unified():
    spaced = "EY ストラテジー・アンド・コンサルティング株式会社"
    tight = "EYストラテジー・アンド・コンサルティング株式会社"
    assert normalize_entity(spaced) == normalize_entity(tight)
    assert normalize_entity(spaced) == "EYストラテジーアンドコンサルティング"


def test_latin_word_spacing_is_preserved():
    """英語社名の語間スペースは可読性のため残す。"""
    assert normalize_entity("Deloitte Tohmatsu Consulting") == "Deloitte Tohmatsu Consulting"


# --- Uhuru ------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["Uhuru", "uhuru", "UHURU", "株式会社ウフル", "ウフル"])
def test_uhuru_and_ufuru_are_one_entity(raw):
    assert normalize_entity(raw) == "ウフル"


# --- ストップリスト(一般名詞の除外) ---------------------------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "ブティック型DXコンサルティングファーム",
        "ブティック型コンサルティングファーム",
        "ブティックコンサルティングファーム",
        "コンサルティングファーム",
        "大手SIer",
        "SIer",
        "特定ベンダー",
        "その他",
        "該当なし",
    ],
)
def test_generic_phrases_are_excluded(phrase):
    assert is_excluded(normalize_entity(phrase)) is True
    assert resolve_entity(phrase) is None


def test_stoplist_matching_ignores_spacing_and_case():
    assert resolve_entity("ブティック型 DX コンサルティングファーム") is None
    assert resolve_entity("大手 SIer") is None


def test_real_companies_survive_the_stoplist():
    for name in ["クロスコム", "船井総研", "アクセンチュア", "日立ソリューションズ",
                 "EYストラテジー・アンド・コンサルティング株式会社", "Uhuru"]:
        assert resolve_entity(name) is not None, name


def test_stoplist_reload_from_yaml():
    from normalize import reload_stoplist

    table = reload_stoplist()
    assert table["exact"] and table["contains"]
    assert resolve_entity("ブティック型DXコンサルティングファーム") is None


def test_aliases_reload_from_yaml():
    """The alias table is data, not code — reloading must keep working."""
    from normalize import reload_aliases

    table = reload_aliases()
    assert table  # the shipped YAML is non-empty
    assert normalize_entity("DCS") == "三菱総研DCS"
