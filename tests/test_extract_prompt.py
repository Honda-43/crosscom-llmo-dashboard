"""抽出プロンプトの判定基準を固定するテスト（APIを呼ばない）。

R-P7調査で、E-1回答の96%が旧事業に言及しているのに
negative_or_outdated が立ったのは直近7日で1件だけ、という取りこぼしが判明した。
原因は判定基準の記述が曖昧だったこと。基準を明文化したので、
その文言が消えないようテストで固定する。

JSONスキーマ（§4承認済み）は不変であることも併せて検証する。
"""
import extract

E1_RECORD = {
    "date": "2026-08-17", "prompt_id": "E-1", "pillar": "entity", "model": "claude",
    "question": "合同会社クロスコムはどんな会社ですか。",
    "answer": "クロスコムはBtoB領域でMAやメールマーケティングを支援しています。",
}


def prompt() -> str:
    return extract._build_prompt(E1_RECORD)


# --- 新しい判定基準 ---------------------------------------------------------
def test_prompt_flags_ended_business_as_current():
    """終了事業を現在の事業として書いていればTRUE、という基準が入っていること。"""
    text = prompt()
    assert "【終了事業】" in text
    assert "クロスコムの現在の事業として現在形で記述している" in text
    for term in ("MA", "メールマーケティング", "メール配信"):
        assert term in text, term


def test_prompt_names_the_current_business():
    """何が現在の事業かを示さないとモデルは判断できない。"""
    text = prompt()
    assert "Agentforce導入・定着支援" in text
    assert "Agentic CRM設計支援" in text


def test_prompt_declares_the_three_business_tiers():
    """事業3区分（2026-08-24 確定）が前提として書かれていること。

    これが無いと、現行事業を現在形で語る回答まで過剰検知される。
    """
    text = prompt()
    for tier in ("【注力事業】", "【現行・非注力事業】", "【終了事業】"):
        assert tier in text, tier
    for current in ("BtoB Salesforce導入・構築支援", "BtoB MA導入・構築支援",
                    "メールマーケティング支援"):
        assert current in text, current


def test_prompt_separates_build_from_outsourcing():
    """「導入・構築＝現行」と「代行・運用＝終了」の分かれ目を明示していること。

    R-P8で判明した過剰検知の原因はここ。MA・メールは語そのものでは
    判定できず、導入・構築か代行・運用かで分かれる。
    """
    text = prompt()
    assert "導入・構築（＝現行）" in text
    assert "代行・運用（＝終了）" in text
    assert "「MAの導入・構築を支援している」→ false" in text
    assert "「MAの運用を代行している」→ true" in text


def test_prompt_does_not_flag_current_non_focus_business():
    """現行・非注力事業だけを挙げた回答をtrueにしない、という除外が入っていること。"""
    text = prompt()
    assert "非注力事業だけを挙げている回答も true にはしない" in text
    assert "「提供していないサービス」にあたらない" in text


def test_prompt_excludes_explicit_past_tense():
    """「過去に提供していた」と明示されている場合はFALSE、という除外条件。

    これが無いと、修正済みの /marketing-automation-btob/ のような
    正しく過去形にしたページまでネガティブ判定になる。
    """
    text = prompt()
    assert "過去に提供していた" in text
    assert "false" in text


def test_prompt_asks_for_a_quoted_detail():
    assert "引用して記載" in prompt()


# --- スキーマ不変の確認 -----------------------------------------------------
def test_json_schema_is_unchanged():
    """§4承認済みのJSONスキーマは変更しない。"""
    for key in ("mention", "mention_type", "rank", "kbf_tags", "negative_or_outdated",
                "negative_detail", "cited_crosscom_urls", "all_cited_urls",
                "competitors_mentioned"):
        assert f'"{key}"' in extract._SCHEMA_BLOCK, key


def test_validation_rules_are_unchanged():
    """_validate が要求するキーと型のルールも従来どおり。"""
    valid = {
        "mention": True, "mention_type": "recommended_list", "rank": 2,
        "kbf_tags": ["ベンダー中立"], "negative_or_outdated": True,
        "negative_detail": "旧MA事業の記述", "cited_crosscom_urls": [],
        "all_cited_urls": [], "competitors_mentioned": ["メンバーズ"],
    }
    assert extract._validate(dict(valid)) == valid


def test_entity_note_still_prioritises_negative_accuracy():
    """E-1では negative_or_outdated の精度を優先する、という既存の指示を維持。"""
    assert "negative_or_outdatedとkbf_tags" in prompt()
    assert "mention判定不要" in prompt()


def test_url_fields_are_still_delegated_to_code():
    """引用URLはコード側で機械的に補完する（既存仕様）。"""
    text = prompt()
    assert "cited_crosscom_urls: 空配列" in text
    assert "all_cited_urls: 空配列" in text
