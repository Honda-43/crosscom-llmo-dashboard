"""lk_mention_grid — プロンプト別の推移タブ.

固定するのは3つ。
  1. 分類メタが YAML から引けて、日次と月次の両方が同じタブに入ること
  2. mentioned が必ず 1/0 の数値で、Looker で合計すると言及日数になること
  3. 分類を足しても既存の観測設定(プロンプト文・active)が変わっていないこと
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_looker  # noqa: E402
import display_map  # noqa: E402
import looker_tabs  # noqa: E402
import sheets_writer  # noqa: E402
from settings import load_monthly_prompts, load_prompts  # noqa: E402

DATE = "2026-09-07"
HEADERS, KEYS = sheets_writer.LOOKER_TABS["lk_mention_grid"]


def obs(prompt_id, model, mention="TRUE", rank="", date=DATE):
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "mention": mention, "rank": rank}


# --- 1. 分類メタ ------------------------------------------------------------
def test_every_daily_prompt_carries_the_classification():
    for prompt in load_prompts():
        for field in looker_tabs.META_FIELDS:
            assert prompt.get(field), (prompt["id"], field)


def test_every_monthly_prompt_carries_the_classification():
    """第2弾候補(active: false)も含めて全件に分類がある。

    有効化した日から Looker の funnel / layer フィルタがそのまま効くように
    しておく。新しいプロンプトを分類なしで足したらここで落ちる。
    """
    for prompt in load_monthly_prompts(active_only=False):
        for field in looker_tabs.META_FIELDS:
            assert prompt.get(field), (prompt["id"], field)


@pytest.mark.parametrize("prompt_id,funnel,layer,stage", [
    ("A-1", "MOFU", "L1", "顕在"),
    ("A-2", "MOFU", "L1", "顕在"),
    ("A-3", "MOFU", "L1", "顕在"),
    ("B-1", "MOFU", "L0", "準顕在"),
    ("B-2", "MOFU", "L2", "顕在"),
    ("B-3", "MOFU", "L2", "顕在"),
    ("E-1", "BOFU", "brand_single", "指名"),
    ("M-1", "BOFU", "brand_single", "指名"),
    ("M-6", "BOFU", "brand_single", "指名"),
    ("M-7", "BOFU", "brand_compare", "指名"),
    ("M-9", "BOFU", "brand_compare", "指名"),
    ("M-10", "MOFU", "L0", "準顕在"),
    ("M-11", "MOFU", "L1", "顕在"),
    ("M-12", "MOFU", "L2", "顕在"),
    # 第2弾候補(active: false)。有効化しても分類はこのまま使える。
    ("M-13", "BOFU", "brand_single", "指名"),
    ("M-14", "BOFU", "brand_compare", "指名"),
    ("M-15", "MOFU", "L1", "顕在"),
    ("M-16", "MOFU", "L2", "顕在"),
])
def test_the_agreed_classification(prompt_id, funnel, layer, stage):
    meta = looker_tabs.prompt_meta()[prompt_id]
    assert (meta["funnel"], meta["layer"], meta["intent_stage"]) == (funnel, layer, stage)


def test_meta_covers_daily_and_monthly_in_one_table():
    meta = looker_tabs.prompt_meta()
    assert {"A-1", "B-1", "E-1"} <= set(meta)          # 日次
    assert {f"M-{n}" for n in range(1, 13)} <= set(meta)  # 月次
    # active: false の第2弾候補も引ける(過去に観測した行のラベルが消えないよう)
    assert {f"M-{n}" for n in range(13, 17)} <= set(meta)
    assert meta["M-14"]["short_label"] == "大手SIerと比較"


def test_prompt_text_is_the_full_prompt():
    meta = looker_tabs.prompt_meta()
    assert meta["A-1"]["prompt_text"] == (
        "Agentforceの導入支援をしてくれるおすすめの会社を教えてください")
    assert meta["M-8"]["prompt_text"].startswith("クロスコムとメンバーズ")


# --- 事業カテゴリ ------------------------------------------------------------
# Pillar A/B の既存集計とは別軸。二重管理にしないよう、board_daily と週次所見は
# 従来どおり Pillar で集計し、service_line は Looker の表示軸としてのみ持つ。
SERVICE_LINES = {
    "Agentforce": ["A-1", "A-2", "A-3", "M-2", "M-3", "M-6", "M-7", "M-8",
                   "M-10", "M-11", "M-15"],
    "AgenticCRM": ["B-1", "B-2", "B-3", "M-4", "M-5", "M-12", "M-13", "M-16"],
    "全社": ["E-1", "M-1", "M-9", "M-14"],
}


def test_the_agreed_service_lines():
    meta = looker_tabs.prompt_meta()
    for line, prompt_ids in SERVICE_LINES.items():
        for prompt_id in prompt_ids:
            assert meta[prompt_id]["service_line"] == line, prompt_id


def test_every_prompt_has_exactly_one_service_line():
    """23本すべてがどれか1つに入る(取りこぼしも重複もない)。"""
    assigned = [pid for ids in SERVICE_LINES.values() for pid in ids]
    assert len(assigned) == len(set(assigned)) == 23
    defined = {p["id"] for p in load_prompts()} | {
        p["id"] for p in load_monthly_prompts(active_only=False)}
    assert set(assigned) == defined


def test_the_column_carries_the_display_name():
    row = looker_tabs.mention_grid_rows(DATE, [obs("A-1", "claude")])[0]
    assert row["service_line"] == "Agentforce導入・定着支援"
    row = looker_tabs.mention_grid_rows(DATE, [obs("B-2", "claude")])[0]
    assert row["service_line"] == "Agentic CRM設計支援"
    row = looker_tabs.mention_grid_rows(DATE, [obs("E-1", "claude")])[0]
    assert row["service_line"] == "全社・その他"


def test_the_yaml_keeps_the_stable_identifier():
    """表示名を変えたくなったとき YAML と過去の観測を触らずに済ませる。"""
    assert looker_tabs.prompt_meta()["A-1"]["service_line"] == "Agentforce"
    assert display_map.service_line("Agentforce") == "Agentforce導入・定着支援"
    assert display_map.service_line("") == ""          # 未分類は空欄のまま


def test_a_cross_business_comparison_is_company_wide():
    """M-9(Salesforce導入比較)と M-14(CRM導入比較)は事業横断。"""
    meta = looker_tabs.prompt_meta()
    assert meta["M-9"]["service_line"] == "全社"
    assert meta["M-14"]["service_line"] == "全社"
    # 事業名が明示されている比較はその事業に入る
    assert meta["M-8"]["service_line"] == "Agentforce"


def test_the_pillar_based_aggregation_is_untouched():
    """service_line を足しても既存の Pillar 集計は別物のまま。"""
    assert "service_line" not in sheets_writer.HEADERS_BOARD
    assert "service_line" not in sheets_writer.HEADERS_SUMMARY
    assert "service_line" not in sheets_writer.HEADERS_LLM
    assert "service_line" not in sheets_writer.HEADERS_MONTHLY
    # 日次の pillar は従来どおり YAML に残っている
    assert {p["pillar"] for p in load_prompts()} == {"A", "B", "entity"}


# --- 2. 行の形 --------------------------------------------------------------
def test_rows_match_the_tab_schema():
    rows = looker_tabs.mention_grid_rows(DATE, [obs("A-1", "claude", rank="3")])
    assert [list(r.keys()) for r in rows] == [HEADERS]


def test_mentioned_is_always_a_number():
    rows = looker_tabs.mention_grid_rows(
        DATE, [obs("A-1", "claude"), obs("A-2", "claude", mention="FALSE")])
    assert [r["mentioned"] for r in rows] == [1, 0]
    assert all(isinstance(r["mentioned"], int) for r in rows)


def test_summing_mentioned_gives_the_number_of_mentioned_days():
    """Looker で SUM(mentioned) が言及日数になること。"""
    rows = []
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        rows.append(obs("A-1", "claude", mention="TRUE", date=day))
    rows.append(obs("A-1", "claude", mention="FALSE", date="2026-09-04"))

    built = []
    for day in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
        built += looker_tabs.mention_grid_rows(day, rows)
    assert sum(r["mentioned"] for r in built) == 3
    assert len(built) == 4          # 件数は観測日数


def test_an_unobserved_row_produces_no_row_at_all():
    """0 を置くと「観測したが言及なし」と区別できず、観測日数が水増しされる。"""
    assert looker_tabs.mention_grid_rows(DATE, [obs("A-1", "claude", mention="")]) == []
    assert looker_tabs.mention_grid_rows(
        DATE, [{"date": DATE, "prompt_id": "A-1", "model": "claude",
                "mention": "", "negative_detail": "[error] timeout"}]) == []


def test_rank_is_blank_when_the_answer_had_no_list_position():
    rows = looker_tabs.mention_grid_rows(
        DATE, [obs("A-1", "claude", rank="2"), obs("A-2", "claude", rank="")])
    assert [r["rank"] for r in rows] == [2, ""]


def test_rows_carry_the_classification_and_the_full_prompt():
    row = looker_tabs.mention_grid_rows(DATE, [obs("B-2", "gemini")])[0]
    assert row["funnel"] == "MOFU"
    assert row["layer"] == "L2"
    assert row["intent_stage"] == "顕在"
    assert row["short_label"] == "ベンダー中立の設計支援を探す"
    assert row["prompt_text"].startswith("中堅企業です。")


def test_an_unknown_prompt_id_still_produces_a_row():
    """観測が先、分類が後になっても行を落とさない(ラベルは prompt_id で代用)。"""
    row = looker_tabs.mention_grid_rows(DATE, [obs("Z-9", "claude")])[0]
    assert row["short_label"] == "Z-9"
    assert (row["funnel"], row["layer"], row["prompt_text"]) == ("", "", "")


def test_only_the_requested_date_is_built():
    rows = [obs("A-1", "claude", date="2026-09-06"), obs("A-1", "claude")]
    assert [r["date"] for r in looker_tabs.mention_grid_rows(DATE, rows)] == [DATE]


def test_extraction_records_work_as_input_too():
    """月次は抽出結果をそのまま渡す(mention が bool でも同じに読む)。"""
    rows = looker_tabs.mention_grid_rows(
        DATE, [{"date": DATE, "prompt_id": "M-1", "model": "claude",
                "mention": True, "rank": None}])
    assert rows[0]["mentioned"] == 1
    assert rows[0]["funnel"] == "BOFU"
    assert rows[0]["rank"] == ""


# --- 3. 日次と月次が同じタブに入る ------------------------------------------
def test_daily_and_monthly_share_the_tab_and_split_by_funnel():
    rows = looker_tabs.mention_grid_rows(
        DATE, [obs("A-1", "claude"), obs("M-1", "claude"), obs("M-10", "claude")])
    by_id = {r["prompt_id"]: r for r in rows}
    assert by_id["A-1"]["funnel"] == "MOFU"
    assert by_id["M-1"]["funnel"] == "BOFU"
    assert by_id["M-10"]["funnel"] == "MOFU"   # 月次でもMOFU補完はMOFU


def test_keys_are_unique_so_the_upsert_does_not_drop_rows():
    rows = looker_tabs.mention_grid_rows(
        DATE, [obs("A-1", "claude"), obs("A-1", "gemini"), obs("M-1", "claude")])
    seen = [tuple(str(r[k]) for k in KEYS) for r in rows]
    assert len(seen) == len(set(seen)) == 3


def test_building_twice_gives_identical_rows():
    rows = [obs("A-1", "claude"), obs("M-7", "gemini", rank="1")]
    assert (looker_tabs.mention_grid_rows(DATE, rows)
            == looker_tabs.mention_grid_rows(DATE, rows))


# --- バックフィル -----------------------------------------------------------
def test_the_backfill_covers_daily_and_monthly_history():
    daily = [obs("A-1", "claude", date=d) for d in ("2026-09-05", "2026-09-06")]
    monthly = [obs("M-1", "claude", date="2026-09-01")]
    payload = backfill_looker.build(daily, monthly_observations=monthly,
                                    tabs=("lk_mention_grid",))
    rows = payload["lk_mention_grid"]
    assert sorted({r["date"] for r in rows}) == [
        "2026-09-01", "2026-09-05", "2026-09-06"]
    assert {r["prompt_id"] for r in rows} == {"A-1", "M-1"}


def test_the_backfill_is_offered_for_this_tab():
    assert "lk_mention_grid" in backfill_looker.BACKFILLABLE


def test_the_backfill_runs_twice_without_changing_the_rows():
    daily = [obs("A-1", "claude", date="2026-09-05")]
    monthly = [obs("M-1", "claude", date="2026-09-01")]

    def build():
        return backfill_looker.build(daily, monthly_observations=monthly,
                                     tabs=("lk_mention_grid",))

    assert build() == build()


# --- 既存の観測設定を壊していないこと ---------------------------------------
def test_the_observed_prompts_are_unchanged():
    """分類を足しただけで、観測するプロンプト文は変えていない。"""
    texts = {p["id"]: p["text"] for p in load_prompts()}
    assert texts["A-1"] == "Agentforceの導入支援をしてくれるおすすめの会社を教えてください"
    assert texts["E-1"] == (
        "合同会社クロスコムはどんな会社ですか。強みと提供サービスを教えてください")
    assert len(texts) == 7


def test_the_monthly_active_set_is_unchanged():
    active = [p["id"] for p in load_monthly_prompts(active_only=True)]
    assert active == [f"M-{n}" for n in range(1, 13)]


# --- lk_answers(同じ分類メタを使う) ---------------------------------------
ANSWER_HEADERS, ANSWER_KEYS = sheets_writer.LOOKER_TABS["lk_answers"]


def raw(prompt_id, model, answer="本文", urls=(), date=DATE):
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "answer": answer, "cited_urls": list(urls)}


def test_answer_rows_match_the_tab_schema():
    rows = looker_tabs.answer_rows(DATE, [raw("A-1", "claude")],
                                   [obs("A-1", "claude", rank="3")])
    assert [list(r.keys()) for r in rows] == [ANSWER_HEADERS]


def test_answers_carry_the_classification():
    row = looker_tabs.answer_rows(DATE, [raw("B-2", "claude")],
                                  [obs("B-2", "claude")])[0]
    assert row["short_label"] == "ベンダー中立の設計支援を探す"
    assert row["service_line"] == "Agentic CRM設計支援"
    assert row["funnel"] == "MOFU"
    assert row["intent_stage"] == "顕在"
    assert row["prompt_text"].startswith("中堅企業です。")


def test_the_monthly_answers_land_in_the_same_tab():
    """月次12本の回答本文が Looker から読めていなかったのがこの列の目的。"""
    rows = looker_tabs.answer_rows(
        DATE,
        [raw("A-1", "claude"), raw("M-1", "claude"), raw("M-8", "gemini")],
        [obs("A-1", "claude"), obs("M-1", "claude"), obs("M-8", "gemini")])
    by_id = {r["prompt_id"]: r for r in rows}
    assert set(by_id) == {"A-1", "M-1", "M-8"}
    assert by_id["A-1"]["funnel"] == "MOFU"      # funnel で日次/月次を切り分ける
    assert by_id["M-1"]["funnel"] == "BOFU"
    assert by_id["M-8"]["service_line"] == "Agentforce導入・定着支援"


def test_the_head_is_flattened_and_capped():
    long_answer = "見出し\n\n本文です。" + "あ" * 1000
    row = looker_tabs.answer_rows(DATE, [raw("A-1", "claude", long_answer)],
                                  [obs("A-1", "claude")])[0]
    assert len(row["answer_head"]) == (
        looker_tabs.ANSWER_HEAD_CHARS + len(looker_tabs.TRUNCATION_MARK))
    assert "\n" not in row["answer_head"]        # 表のセルで1行に収まること
    assert row["answer_head"].startswith("見出し 本文です。")


def test_the_head_is_the_whole_answer_when_it_is_short():
    row = looker_tabs.answer_rows(DATE, [raw("A-1", "claude", "短い回答")],
                                  [obs("A-1", "claude")])[0]
    assert row["answer_head"] == "短い回答"
    assert row["answer_text"] == "短い回答"


def test_the_full_text_is_capped_at_thirty_thousand():
    row = looker_tabs.answer_rows(DATE, [raw("A-1", "claude", "あ" * 60_000)],
                                  [obs("A-1", "claude")])[0]
    assert looker_tabs.ANSWER_CHAR_LIMIT == 30_000
    assert len(row["answer_text"]) == 30_000
    assert row["answer_text"].endswith(looker_tabs.TRUNCATION_MARK)


def test_competitors_use_the_normalised_names():
    """lk_scatter や lk_sov_trend と同じ表記でないと突き合わせられない。"""
    observation = obs("A-1", "claude")
    observation["competitors_mentioned"] = "メンバーズ, Uhuru, クロスコム, メンバーズ"
    row = looker_tabs.answer_rows(DATE, [raw("A-1", "claude")], [observation])[0]
    # 表記ゆれは寄せ、重複は落とし、自社は除く
    assert row["competitors"] == "ウフル, メンバーズ"


def test_cited_urls_are_capped_and_drop_the_unresolvable_ones():
    urls = [f"https://example{n}.jp/a" for n in range(8)]
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/xyz"
    row = looker_tabs.answer_rows(
        DATE, [raw("A-1", "claude", urls=[redirect] + urls)],
        [obs("A-1", "claude")])[0]
    listed = row["cited_urls"].split(", ")
    assert len(listed) == looker_tabs.CITED_URL_LIMIT == 5
    assert redirect not in row["cited_urls"]     # 元ドメインが解決できない
    assert listed[0] == "https://example0.jp/a"


def test_the_window_is_thirty_days():
    assert looker_tabs.ANSWER_DAYS == 30


def test_building_the_answers_twice_gives_identical_rows():
    records = [raw("A-1", "claude"), raw("M-1", "gemini")]
    seen = [obs("A-1", "claude"), obs("M-1", "gemini")]
    assert (looker_tabs.answer_rows(DATE, records, seen)
            == looker_tabs.answer_rows(DATE, records, seen))


def test_the_answers_tab_is_replaced_not_appended():
    """入れ替え方式なので、書く側は日次と月次の両方を含める必要がある。"""
    from settings import TAB_LK_ANSWERS

    assert TAB_LK_ANSWERS in sheets_writer.LOOKER_REWRITE_TABS
