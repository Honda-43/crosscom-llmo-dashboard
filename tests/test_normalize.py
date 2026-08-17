"""Unit tests for normalize_entity (Phase 1 §6-1)."""
import pytest

from normalize import normalize_entity


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
        ("100inc", "ゼロワングロース"),
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


def test_a_bare_legal_form_is_not_erased():
    """A model that answers only "株式会社" still produces a countable token."""
    assert normalize_entity("株式会社") == "株式会社"
    assert normalize_entity("Inc.") != ""


def test_normalize_entity_is_idempotent():
    for raw in ["株式会社メンバーズ サースプラスカンパニー", "三菱総研ＤＣＳ", "Some New Vendor"]:
        once = normalize_entity(raw)
        assert normalize_entity(once) == once


def test_aliases_reload_from_yaml():
    """The alias table is data, not code — reloading must keep working."""
    from normalize import reload_aliases

    table = reload_aliases()
    assert table  # the shipped YAML is non-empty
    assert normalize_entity("DCS") == "三菱総研DCS"
