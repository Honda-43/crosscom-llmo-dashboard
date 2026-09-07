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


def test_every_active_monthly_prompt_carries_the_classification():
    """active にしたのに分類を書き忘れたら落とす(M-13〜16 を有効化したとき)。"""
    for prompt in load_monthly_prompts(active_only=True):
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
])
def test_the_agreed_classification(prompt_id, funnel, layer, stage):
    meta = looker_tabs.prompt_meta()[prompt_id]
    assert (meta["funnel"], meta["layer"], meta["intent_stage"]) == (funnel, layer, stage)


def test_meta_covers_daily_and_monthly_in_one_table():
    meta = looker_tabs.prompt_meta()
    assert {"A-1", "B-1", "E-1"} <= set(meta)          # 日次
    assert {f"M-{n}" for n in range(1, 13)} <= set(meta)  # 月次
    # active: false の第2弾候補も引ける(過去に観測した行のラベルが消えないよう)
    assert "M-13" in meta


def test_prompt_text_is_the_full_prompt():
    meta = looker_tabs.prompt_meta()
    assert meta["A-1"]["prompt_text"] == (
        "Agentforceの導入支援をしてくれるおすすめの会社を教えてください")
    assert meta["M-8"]["prompt_text"].startswith("クロスコムとメンバーズ")


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
