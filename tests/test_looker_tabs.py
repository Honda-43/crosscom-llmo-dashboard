"""Looker 用タブのテスト(Phase 6 §4).

固定するのは3つ。
  1. スキーマ — 各ビルダーの返すキーがタブのヘッダと一致する
  2. 冪等性  — 同じ入力から同じ行が出る(鍵が重複しない)
  3. 整形    — Looker側で計算しなくて済む形になっている
"""
import datetime as dt

import pytest

import display_map
import looker_tabs
import sheets_writer
import verdicts
from settings import SELF_ENTITY

TODAY = "2026-08-24"
MODELS = ("claude", "gemini")


def observation(date, prompt_id, model, *, mention=True, rank=None,
                negative=False, detail="", competitors=(), pillar="A"):
    return {
        "date": date, "prompt_id": prompt_id, "pillar": pillar, "model": model,
        "mention": "TRUE" if mention else "FALSE",
        "mention_type": "", "rank": "" if rank is None else str(rank),
        "kbf_tags": "", "negative_or_outdated": "TRUE" if negative else "FALSE",
        "negative_detail": detail, "cited_crosscom_urls": "",
        "competitors_mentioned": ", ".join(competitors), "raw_file": "",
    }


def history(days=10):
    """``TODAY`` で終わる ``days`` 日分の観測。A-1/B-1/E-1 × 2モデル。"""
    rows = []
    end = dt.date.fromisoformat(TODAY)
    for offset in range(days):
        date = (end - dt.timedelta(days=offset)).isoformat()
        for model in MODELS:
            rows.append(observation(date, "A-1", model, mention=True, rank=2,
                                    competitors=("メンバーズ", "ウフル")))
            rows.append(observation(date, "B-1", model, mention=False,
                                    pillar="B", competitors=("メンバーズ",)))
            rows.append(observation(date, "E-1", model, mention=True, pillar="entity",
                                    negative=(offset < 3),
                                    detail="旧MA事業を現在の主要事業として記述している"))
    return rows


ACTIONS = [
    {"action_id": "A-001", "優先度": "高", "内容": "外部プロフィール更新", "対象": "E-1",
     "根拠rule_id": "R-P7", "状態": verdicts.STATUS_MEASURING,
     "提案日": "2026-08-08", "実施日": "2026-08-11", "判断期限": "2026-09-07"},
    {"action_id": "A-005", "優先度": "中", "内容": "フォームに認知経路を追加", "対象": "KGI",
     "根拠rule_id": "", "状態": verdicts.STATUS_PROPOSED,
     "提案日": "2026-08-24", "実施日": "", "判断期限": ""},
]


@pytest.fixture
def observations():
    return history()


@pytest.fixture
def sov_rows(observations):
    return looker_tabs.sov_rows_from_observations(observations)


@pytest.fixture
def payload(observations, sov_rows):
    return looker_tabs.build_all(
        TODAY, observations=observations,
        summary_rows=looker_tabs.summary_rows_from_observations(observations),
        sov_rows=sov_rows, action_rows=ACTIONS,
        changes=[{"date": TODAY, "prompt_id": "E-1", "model": "claude",
                  "change_type": "negative_flag_on", "before": "FALSE",
                  "after": "TRUE", "detail": "旧MA事業の記述"}],
        raw_records=[{"date": TODAY, "prompt_id": "A-1", "model": "claude",
                      "answer": "本文", "cited_urls": []}],
    )


# --- 1. スキーマ ------------------------------------------------------------
def test_every_tab_is_declared_with_headers_and_keys(payload):
    assert set(payload) == set(sheets_writer.LOOKER_TABS)


def test_rows_match_the_declared_headers_exactly(payload):
    for tab, rows in payload.items():
        headers, _ = sheets_writer.LOOKER_TABS[tab]
        assert rows, f"{tab} が空(テストデータで作れるはず)"
        for row in rows:
            assert list(row.keys()) == headers, tab


def test_key_columns_are_part_of_the_headers():
    for tab, (headers, keys) in sheets_writer.LOOKER_TABS.items():
        assert set(keys) <= set(headers), tab


# --- 2. 冪等性 --------------------------------------------------------------
def test_building_twice_gives_identical_rows(observations, sov_rows):
    def build():
        return looker_tabs.build_all(
            TODAY, observations=observations,
            summary_rows=looker_tabs.summary_rows_from_observations(observations),
            sov_rows=sov_rows, action_rows=ACTIONS)

    assert build() == build()


def test_keys_are_unique_within_one_build(payload):
    """鍵が重複すると upsert が同じ行を上書きし、行が消える。"""
    for tab, rows in payload.items():
        _, keys = sheets_writer.LOOKER_TABS[tab]
        seen = [tuple(str(r[k]) for k in keys) for r in rows]
        assert len(seen) == len(set(seen)), tab


def test_upsert_plan_updates_instead_of_appending_on_a_rerun():
    headers, keys = sheets_writer.LOOKER_TABS["lk_negative"]
    rows = [{"date": TODAY, "model": "claude", "detected": 1, "note": "検知"}]

    first = sheets_writer._plan_upsert([headers], headers, keys, rows)
    assert [w["row"] for w in first] == [2]

    existing = [headers, [str(rows[0][h]) for h in headers]]
    second = sheets_writer._plan_upsert(existing, headers, keys, rows)
    assert [w["row"] for w in second] == [2]   # 追記ではなく同じ行を上書き


def test_upsert_plan_appends_a_new_key_after_the_last_row():
    headers, keys = sheets_writer.LOOKER_TABS["lk_negative"]
    existing = [headers, [TODAY, "claude", "1", "検知"]]
    rows = [{"date": TODAY, "model": "gemini", "detected": 0, "note": ""}]
    assert [w["row"] for w in
            sheets_writer._plan_upsert(existing, headers, keys, rows)] == [3]


# --- 3. 整形 ----------------------------------------------------------------
def test_verdicts_cover_all_eight_faces_with_japanese_names(payload):
    rows = payload["lk_verdicts"]
    assert [r["face"] for r in rows] == list(looker_tabs.FACE_NAMES)
    assert all(r["face_name"] and not r["face_name"].isascii() for r in rows)
    assert all(r["verdict_text"].startswith(verdicts.VERDICT_PREFIX) for r in rows)


def test_heatgrid_labels_read_as_mentioned_over_observed(payload):
    rows = {(r["prompt_id"], r["model"]): r for r in payload["lk_heatgrid"]}
    a1 = rows[("A-1", "claude")]
    assert a1["cell_label"] == "7/7"          # 7日窓すべてで言及あり
    assert a1["days_mentioned_7d"] == 7
    assert rows[("B-1", "claude")]["cell_label"] == "0/7"
    assert a1["prompt_name"].startswith("A-1 ")   # cep 先頭の短縮名


def test_scatter_marks_which_rank_is_real_and_which_is_a_proxy(payload):
    rows = {r["entity"]: r for r in payload["lk_scatter"]}
    assert rows[SELF_ENTITY]["rank_source"] == looker_tabs.RANK_SOURCE_SELF
    assert rows[SELF_ENTITY]["is_crosscom"] == "TRUE"
    others = [r for e, r in rows.items() if e != SELF_ENTITY]
    assert others and all(r["rank_source"] == looker_tabs.RANK_SOURCE_PROXY
                          for r in others)
    assert all(r["is_crosscom"] == "FALSE" for r in others)


def test_scatter_quadrants_are_the_four_fixed_labels(payload):
    allowed = {"高シェア×上位", "高シェア×下位", "低シェア×上位", "低シェア×下位"}
    assert {r["quadrant"] for r in payload["lk_scatter"]} <= allowed


def test_sov_trend_is_limited_to_the_top_entities_plus_us(payload):
    entities = {r["entity"] for r in payload["lk_sov_trend"]}
    assert SELF_ENTITY in entities
    assert len(entities) <= looker_tabs.TREND_ENTITIES + 1


def test_sov_trend_shares_are_seven_day_averages(observations, sov_rows):
    rows = looker_tabs.sov_trend_rows(TODAY, sov_rows)
    ours = next(r for r in rows if r["entity"] == SELF_ENTITY)
    # A-1 は毎日2モデルで言及、B-1 は毎日言及なし。E-1 は母数から外れる。
    assert ours["share_7d"] == "0.5000"


def test_negative_rows_use_the_slack_kind_summary(payload):
    rows = {r["model"]: r for r in payload["lk_negative"]}
    assert rows["claude"]["detected"] == 1
    assert rows["claude"]["note"] == "旧事業(MA/メール配信)の記述"
    assert len(rows["claude"]["note"]) <= 20


def test_negative_rows_are_zero_when_nothing_was_detected():
    quiet = [observation("2026-08-24", "A-1", "claude", negative=False)]
    rows = looker_tabs.negative_rows(TODAY, quiet)
    assert rows == [{"date": TODAY, "model": "claude", "detected": 0, "note": ""}]


def test_events_are_named_in_japanese_and_point_at_the_playbook(payload):
    row = payload["lk_events"][0]
    assert row["event_name"] == "ネガ検知"
    assert row["playbook_ref"] == "P-7"
    assert row["place"] == "E-1 × claude"


def test_events_drop_change_types_that_are_not_material():
    changes = [{"date": TODAY, "prompt_id": "A-1", "model": "claude",
                "change_type": "rank_up", "detail": "順位 4 → 2"}]
    assert looker_tabs.event_rows(TODAY, changes) == []


def test_a_competitor_counts_as_an_event_only_when_it_is_in_the_top(sov_rows):
    changes = [
        {"date": TODAY, "prompt_id": "A-1", "model": "claude",
         "change_type": "competitor_added", "detail": "メンバーズ"},
        {"date": TODAY, "prompt_id": "A-1", "model": "claude",
         "change_type": "competitor_added", "detail": "一度だけ出た会社"},
    ]
    names = [r["detail"] for r in looker_tabs.event_rows(TODAY, changes, sov_rows)]
    assert names == ["メンバーズ"]


def test_actions_mirror_the_log_with_display_values_and_a_countdown():
    rows = {r["action_id"]: r for r in looker_tabs.action_display_rows(ACTIONS, TODAY)}
    assert rows["A-001"]["target_display"] == "E-1"        # 識別コードはそのまま
    assert rows["A-005"]["target_display"] == "成果指標"    # KGI は表示だけ訳す
    assert rows["A-001"]["days_to_deadline"] == 14         # 8/24 -> 9/7
    assert rows["A-005"]["days_to_deadline"] == ""         # 期限なし
    assert rows["A-001"]["rule_id"] == "R-P7"
    assert rows["A-005"]["rule_id"] == display_map.MISSING


def test_the_action_log_itself_is_untouched():
    """lk_actions はミラー。元の行を書き換えない。"""
    before = [dict(r) for r in ACTIONS]
    looker_tabs.action_display_rows(ACTIONS, TODAY)
    assert ACTIONS == before


def test_answers_are_limited_to_the_recent_window(observations):
    old = (dt.date.fromisoformat(TODAY) - dt.timedelta(days=20)).isoformat()
    records = [
        {"date": TODAY, "prompt_id": "A-1", "model": "claude", "answer": "新しい"},
        {"date": old, "prompt_id": "A-1", "model": "claude", "answer": "古い"},
    ]
    rows = looker_tabs.answer_rows(TODAY, records, observations)
    assert [r["date"] for r in rows] == [TODAY]


def test_answers_are_truncated_at_the_cell_limit(observations):
    records = [{"date": TODAY, "prompt_id": "A-1", "model": "claude",
                "answer": "あ" * 60_000}]
    text = looker_tabs.answer_rows(TODAY, records, observations)[0]["answer_text"]
    assert len(text) == looker_tabs.ANSWER_CHAR_LIMIT
    assert text.endswith(looker_tabs.TRUNCATION_MARK)


def test_answers_show_mention_in_japanese(observations):
    records = [
        {"date": TODAY, "prompt_id": "A-1", "model": "claude", "answer": "x"},
        {"date": TODAY, "prompt_id": "B-1", "model": "claude", "answer": "y"},
    ]
    rows = {r["prompt_id"]: r for r in
            looker_tabs.answer_rows(TODAY, records, observations)}
    assert rows["A-1"]["mention"] == "あり"
    assert rows["A-1"]["rank"] == 2
    assert rows["B-1"]["mention"] == "なし"


# --- 派生データの復元 -------------------------------------------------------
def test_mention_rate_is_restored_the_same_way_daily_summary_computes_it(observations):
    """lk_* は daily_summary を読み直さずに言及率を復元する。式は同じ。"""
    rows = {r["date"]: r for r in
            looker_tabs.summary_rows_from_observations(observations)}
    # A-1 は言及あり、B-1 は言及なし、E-1 は分母から外れる。
    assert rows[TODAY]["mention_rate_all"] == 0.5
    assert rows[TODAY]["mention_rate_pillar_a"] == 1.0
    assert rows[TODAY]["mention_rate_pillar_b"] == 0.0


def test_prompt_names_are_short_japanese_labels():
    names = looker_tabs.prompt_names()
    assert names["A-1"] == "A-1 導入検討初期"      # cep の先頭だけ
    assert names["B-1"] == "B-1 カテゴリ認知"
    assert all(len(v) <= 20 for v in names.values())


def test_display_values_come_from_the_shared_map():
    """アプリとLookerで同じ値が違う言葉にならないこと。"""
    import labels

    assert labels.TARGET_LABELS is display_map.TARGET_LABELS
    assert labels.STATUS_LABELS is display_map.STATUS_LABELS
    assert labels.CHANGE_TYPE_LABELS is display_map.CHANGE_TYPE_LABELS
    assert labels.PILLAR_LABELS is display_map.PILLAR_LABELS


def test_board_daily_carries_the_r1_verdict():
    assert sheets_writer.HEADERS_BOARD[-1] == "verdict_r1"
    # 既存カラムの並びは変えない(Looker のフィールド対応が壊れるため)
    assert sheets_writer.HEADERS_BOARD[:11] == [
        "date", "mention_rate_all_7d", "mention_rate_a_7d", "mention_rate_b_7d",
        "sov_rank", "sov_share", "negative_streak_days", "branded_clicks_wk",
        "ai_sessions_wk", "noise_flag", "material_events",
    ]


# --- 同じ日の再実行 ----------------------------------------------------------
def test_duplicated_observations_do_not_inflate_the_counts(observations):
    """同日を再実行しても「7日中12日言及」のような行にならないこと。

    run_daily は読み込んだ履歴に当日分を足してから集計する。履歴に既に当日が
    入っている(=再実行)ときは上書きしないと観測が二重になる。
    """
    doubled = list(observations) + list(observations)
    inflated = looker_tabs.heatgrid_rows(TODAY, doubled)
    assert any(int(r["cell_label"].split("/")[1]) > 7 for r in inflated)

    # run_daily と同じ鍵で重複を落としたら元に戻る
    index = {(r["date"], r["prompt_id"], r["model"]): r for r in doubled}
    fixed = looker_tabs.heatgrid_rows(TODAY, list(index.values()))
    assert fixed == looker_tabs.heatgrid_rows(TODAY, observations)


def test_a_rewrite_tab_is_never_cleared_by_an_empty_build():
    """元データが読めなかった日に lk_answers を空で上書きしないこと。"""
    assert "lk_answers" in sheets_writer.LOOKER_REWRITE_TABS
    assert looker_tabs.answer_rows(TODAY, [], []) == []
