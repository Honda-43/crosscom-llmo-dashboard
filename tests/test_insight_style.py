"""週次所見の記述ルールのテスト(Phase 7 §B).

禁止語の検査は tests/display_text.py の英字検査と同じ方式:
許可語と判定を1か所(src/insight_style.py)に置き、テストは
「画面/配信に出る文字列」をそこに通すだけにする。所見文はLLMが書くので
出力そのものは固定できないが、**所見の語彙の出どころ**は固定できる。

 - config/playbook.md  … 原因仮説・改善アクションの文言はここから写される
 - rules_engine の detail … 状態の1行はここから写される
 - fallback_report      … LLMが落ちた週に配信される本文
 - 後処理の出力          … 実際に配信される最終形

この4つに禁止語が無ければ、所見に比喩が入る経路はプロンプト外の
モデルの言い回しだけになる。それは postprocess の warnings で検出する。
"""
import json

import generate_insight
import insight_style
import rules_engine
from settings import PLAYBOOK_FILE, RULES_THRESHOLDS_FILE, load_yaml

THRESHOLDS = load_yaml(RULES_THRESHOLDS_FILE)

STATS = {
    "date": "2026-08-31",
    "mention_rate": {
        "all": {"this_week": 0.4818, "prev_week": 0.5, "delta": -0.0182},
        "pillar_a": {"this_week": 0.5953, "prev_week": 0.6429, "delta": -0.0476},
        "pillar_b": {"this_week": 0.3452, "prev_week": 0.3571, "delta": -0.0119},
    },
    "sov": {"all": {"observed_total": 77, "prev_week_competitor_count": 9, "entities": [
        {"entity": "クロスコム", "mention_count": 37, "share": 0.4805,
         "prev_week_count": 42, "delta": -5},
    ]}},
    "kgi": {
        "ai_sessions": {"this_week": 10, "prev_week": 4, "delta": 6, "noise_zone": False},
        "branded_clicks": {"this_week": 2, "prev_week": 2, "delta": 0, "noise_zone": True},
        "noise_floor": 10, "noise_zone_metrics": ["branded_clicks"],
    },
    "data_quality": {"observation_days_this_week": 7, "observation_days_prev_week": 7},
    "rules": [
        {"rule_id": "R-P2", "status": "fired", "fired": True, "detail": "1系列で言及消失",
         "evidence": [{"prompt_id": "B-3", "model": "gemini"}]},
        {"rule_id": "R-P15", "status": "fired", "fired": True, "detail": "1件の競合",
         "evidence": [{"prompt_id": "B-3", "entity": "テクノデジタルコンサルティング"}]},
    ],
    "fired_rules": ["R-P2", "R-P15"],
    "insufficient_rules": [],
}


# --------------------------------------------------------------------------
# 1-2. 数値の表記
# --------------------------------------------------------------------------
def test_rates_are_written_as_whole_percentages():
    assert insight_style.rate_text(0.4818) == "48%"
    assert insight_style.rate_text(0.5) == "50%"
    assert insight_style.rate_text(None) == "データなし"


def test_rate_deltas_are_written_in_points():
    assert insight_style.points_text(0.0714, flat=5) == "前週比 +7ポイント"
    assert insight_style.points_text(-0.20, flat=5) == "前週比 -20ポイント"


def test_a_small_move_is_called_flat_but_keeps_the_number():
    """丸めた言葉だけにすると、翌週に何ポイント動いたのか遡れない。"""
    assert insight_style.points_text(-0.0182, flat=5) == "前週比 横ばい(-2ポイント)"
    assert insight_style.points_text(0.05, flat=5) == "前週比 横ばい(+5ポイント)"
    assert insight_style.points_text(0.0, flat=5) == "前週比 横ばい(±0ポイント)"


def test_the_flat_threshold_comes_from_the_yaml():
    assert insight_style.flat_delta_points(THRESHOLDS) == 5
    assert insight_style.flat_delta_points({"insight": {"flat_delta_points": 3}}) == 3


def test_counts_never_use_points():
    assert insight_style.count_delta_text(6, "セッション") == "前週比 +6セッション"
    assert insight_style.count_delta_text(0) == "前週比 ±0件"


def test_raw_decimals_are_rewritten_to_their_display_form():
    replacements = insight_style.number_replacements(STATS)
    text = "言及率(全体)は0.4818(前週0.5、-0.0182)。"
    out = insight_style.apply_number_format(text, replacements)
    assert out == "言及率(全体)は48%(前週50%、-2ポイント)。"


def test_rewriting_leaves_numbers_that_are_not_rates_alone():
    """順位中央値 4.5 は率ではない。stats に無い小数は触らない。"""
    replacements = insight_style.number_replacements(STATS)
    text = "順位中央値は4.5から3.0になった。"
    assert insight_style.apply_number_format(text, replacements) == text


def test_a_share_that_prefixes_another_value_is_not_partially_replaced():
    replacements = insight_style.number_replacements(STATS)
    assert insight_style.apply_number_format("0.4805", replacements) == "48%"


def test_observation_day_counts_are_not_treated_as_rates():
    """mention_rate.days_observed は率ではない。7 を「700%」にしない。"""
    stats = json.loads(json.dumps(STATS))
    stats["mention_rate"]["days_observed"] = {"this_week": 7, "prev_week": 7}
    replacements = insight_style.number_replacements(stats)
    assert "7" not in replacements
    assert insight_style.apply_number_format("R-P7は直近7日で発火", replacements) \
        == "R-P7は直近7日で発火"


def test_only_decimals_are_rewritten():
    """整数を置換対象にすると rule_id の数字に当たる。"""
    assert all("." in raw for raw in insight_style.number_replacements(STATS))


def test_bare_decimals_are_detected():
    assert insight_style.bare_decimals("率は0.42です") == [(1, "0.42")]
    assert insight_style.bare_decimals("率は42%です") == []


# --------------------------------------------------------------------------
# 3. パターンの日本語説明
# --------------------------------------------------------------------------
def test_every_rule_has_a_japanese_gloss():
    gloss = insight_style.pattern_gloss(THRESHOLDS)
    for rule_id in ("R-P2", "R-P4", "R-P5", "R-P7", "R-P8", "R-P15", "R-DROP"):
        assert rule_id in gloss, rule_id
        assert gloss[rule_id].strip()


def test_the_gloss_uses_the_configured_threshold():
    """説明文に数を書き写すと、閾値を変えたとき説明だけが古くなる。"""
    gloss = insight_style.pattern_gloss(
        {"rules": {"R-P2": {"consecutive_absent_observations": 5}}})
    assert "5観測日以上" in gloss["R-P2"]


def test_the_gloss_is_added_only_on_the_first_mention():
    gloss = {"R-P2": "言及消失:同一プロンプトで3観測日以上言及がない"}
    out = insight_style.gloss_first_mentions("R-P2が発火。R-P2は先週も発火。", gloss)
    assert out.count("言及消失:") == 1
    assert out.startswith("R-P2(言及消失:同一プロンプトで3観測日以上言及がない)が発火。")


def test_an_existing_gloss_is_not_duplicated():
    gloss = {"R-P2": "言及消失:3観測日以上"}
    text = "R-P2(言及消失:3観測日以上)が発火。"
    assert insight_style.gloss_first_mentions(text, gloss) == text


def test_a_rule_id_written_inside_parentheses_is_left_alone():
    """「言及消失(R-P2)」に説明を足すと二重括弧になって読めなくなる。"""
    gloss = {"R-P2": "言及消失:3観測日以上"}
    text = "クロスコムは言及消失(R-P2)を検知した。"
    assert insight_style.gloss_first_mentions(text, gloss) == text


def test_a_rule_id_at_the_start_of_the_text_still_gets_its_gloss():
    gloss = {"R-P2": "言及消失:3観測日以上"}
    out = insight_style.gloss_first_mentions("R-P2が発火。", gloss)
    assert out == "R-P2(言及消失:3観測日以上)が発火。"


# --------------------------------------------------------------------------
# 4. 禁止語 — display_text の英字検査と同じ方式
# --------------------------------------------------------------------------
def test_banned_words_are_detected_with_their_line():
    found = insight_style.banned_words("1行目\n競合に押し出された\n3行目")
    assert found == [(2, "押し出", "競合に押し出された")]


def test_the_service_name_is_not_a_banned_word():
    """「Agentforce導入・定着支援」は事業名であって比喩ではない。"""
    assert insight_style.banned_words("クロスコムはAgentforce導入・定着支援を提供する") == []


def test_the_metaphor_use_of_the_same_word_is_still_banned():
    assert insight_style.banned_words("競合がB-3に定着している")


def test_the_playbook_states_the_same_thresholds_as_the_yaml():
    """プロンプトは所見の定義文をプレイブックの「状態」から書かせる。

    その定義に書かれた数がYAMLの閾値とずれると、所見が誤った定義を
    載せることになる。プレイブックは手で編集するファイルなので、
    ずれたことに気付ける形にしておく。
    """
    text = PLAYBOOK_FILE.read_text(encoding="utf-8")
    rules = THRESHOLDS["rules"]
    expected = [
        (f"直近{rules['R-P2']['consecutive_absent_observations']}観測日連続", "P-2"),
        (f"+{insight_style.points(rules['R-P4']['mention_rate_delta'])}ポイント以上", "P-4"),
        (f"中央値が {rules['R-P5']['rank_threshold']:g} 位以下", "P-5"),
        (f"週が{rules['R-P5']['consecutive_weeks']}週連続", "P-5"),
        (f"{rules['R-P15']['consecutive_weeks']}週連続で出現", "P-15"),
        (f"上位{rules['R-DROP']['top_n']}の競合", "P-DROP"),
    ]
    for phrase, pattern in expected:
        assert phrase in text, f"{pattern}: 「{phrase}」がプレイブックに無い"


def test_the_playbook_has_no_banned_words():
    """所見の言い回しはプレイブックから写される。元を断つ。"""
    text = PLAYBOOK_FILE.read_text(encoding="utf-8")
    assert insight_style.banned_words(text) == []


def test_rule_details_have_no_banned_words():
    """状態の1行は rules_engine の detail から写される。"""
    observations = [
        {"date": f"2026-08-{day:02d}", "prompt_id": "B-3", "pillar": "B",
         "model": model, "mention": "FALSE", "rank": "", "competitors_mentioned": "A社",
         "negative_or_outdated": "FALSE", "negative_detail": "",
         "cited_crosscom_urls": ""}
        for day in range(4, 32) for model in ("claude", "gemini")
    ]
    stats = rules_engine.build_stats(
        "2026-08-31", {"llm_observations": observations}, THRESHOLDS, ["/btob-crm/"])
    for rule in stats["rules"]:
        assert insight_style.banned_words(rule["detail"]) == [], rule


def test_the_fallback_report_has_no_banned_words():
    report = generate_insight.fallback_report(STATS, THRESHOLDS)
    assert insight_style.banned_words(report) == []


def test_the_postprocessed_report_reports_a_surviving_metaphor():
    """機械で直せない比喩は消さずに警告に積む。消えないことが分かるほうがよい。"""
    result = generate_insight.postprocess(
        "## 1. 今週のサマリ\nクロスコムは競合に押し出された。", STATS, [], THRESHOLDS)
    assert any("押し出" in w for w in result["warnings"])


# --------------------------------------------------------------------------
# 3行の箇条書き / 矢印記法
# --------------------------------------------------------------------------
def test_arrow_labels_are_normalised_to_colons():
    text = "状態→B-3で消失\n原因仮説→競合が増えた\nアクション→ページを更新する"
    out = insight_style.normalize_labels(text)
    assert out.splitlines() == [
        "状態: B-3で消失",
        "原因仮説: 競合が増えた",
        "推奨アクション: ページを更新する",
    ]


def test_a_bare_action_label_becomes_the_recommended_action_label():
    assert insight_style.normalize_labels("アクション: 更新する") == "推奨アクション: 更新する"


def test_a_surviving_arrow_is_reported():
    assert insight_style.arrows("Aが増えた→Bが減った") == [(1, "Aが増えた→Bが減った")]
    assert insight_style.arrows("Aが増え、Bが減った") == []


# --------------------------------------------------------------------------
# 5. R-P2 と R-P15 の同時発火
# --------------------------------------------------------------------------
def test_co_fired_prompts_are_found_from_the_evidence():
    assert insight_style.co_fired_prompts(STATS) == ["B-3"]


def test_a_rule_that_did_not_fire_is_not_counted():
    stats = json.loads(json.dumps(STATS))
    stats["rules"][1]["fired"] = False
    assert insight_style.co_fired_prompts(stats) == []


CO_FIRED_REPORT = """## 3. 発火パターンと推奨アクション

**R-P2(言及消失)**
状態: クロスコムはB-3(gemini)で11観測日連続で言及されていない
原因仮説: 競合の候補社数が増えた
推奨アクション: 担当者が来週末までにB-3対応の自社ページを更新する

**R-P15(競合の連続出現)**
状態: 競合のテクノデジタルコンサルティングがB-3で4週連続で出ている
原因仮説: 競合がB-3に専用の一次情報を持っている
推奨アクション: 担当者が来週末までに競合の引用ページを読む

## 4. ウォッチ項目
"""


def test_co_fired_patterns_are_merged_into_one_item():
    out = insight_style.merge_co_fired(CO_FIRED_REPORT, ["B-3"])
    assert out.count("**R-P2") == 1
    assert "**R-P15(" not in out
    assert "**R-P2・R-P15 — B-3" in out


def test_the_merged_actions_are_ordered_competitor_first():
    """自社のページを直す前に、競合が何を書いているかを見る。"""
    out = insight_style.merge_co_fired(CO_FIRED_REPORT, ["B-3"])
    action = next(l for l in out.splitlines() if l.startswith("推奨アクション:"))
    assert action.index("競合の引用ページを読む") < action.index("自社ページを更新する")
    assert action.startswith("推奨アクション: ①")


def test_the_merged_lines_do_not_double_the_full_stop():
    """元の行が「。」で終わっていても、つないだ結果を「。。」にしない。"""
    report = CO_FIRED_REPORT.replace("言及されていない", "言及されていない。")
    out = insight_style.merge_co_fired(report, ["B-3"])
    assert "。。" not in out


def test_the_merge_keeps_the_rest_of_the_report():
    out = insight_style.merge_co_fired(CO_FIRED_REPORT, ["B-3"])
    assert "## 4. ウォッチ項目" in out
    assert "## 3. 発火パターンと推奨アクション" in out


def test_a_report_already_merged_is_left_alone():
    text = "**R-P2・R-P15 — B-3**\n状態: 統合済み\n"
    assert insight_style.merge_co_fired(text, ["B-3"]) == text
