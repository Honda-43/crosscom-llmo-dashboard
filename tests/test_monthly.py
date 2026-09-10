"""月次観測のテスト(Phase 3 DoD 1・3・4).

固定したいのは3つ:

1. プロンプトが xlsx のとおりであること。文言が変わると前月と比較できない。
2. Gemini の1日の枠(20リクエスト/モデル)を、日次7本と足して超えないこと。
   これは設計の制約で、超えた瞬間に観測が欠測になる。
3. 日次・週次のスキーマに触れていないこと。
"""
import pytest

import collect_llm
import notify_slack
import run_monthly
import settings
import sheets_writer

MONTHLY = settings.load_monthly_prompts(active_only=False)
ACTIVE = settings.load_monthly_prompts()

# クロスコム_月次観測プール設計_v1.xlsx シート「月次観測プール_第1弾」の原文。
# yaml を書き換えたらここも落ちる(意図しない編集の検知)。
XLSX_PROMPTS = {
    "M-1": "クロスコムの評判を教えてください。",
    "M-2": "クロスコムのAgentforce導入支援の費用を教えてください。",
    "M-3": "クロスコムのAgentforce導入支援の実績を教えてください。",
    "M-4": "クロスコムのAgentic CRM設計支援の評判を教えてください。",
    "M-5": "クロスコムのCRMデータ設計の専門性を教えてください。",
    "M-6": "クロスコムのAgentforce定着支援について教えてください。",
    "M-7": "クロスコムとテクノデジタルコンサルティングのAIエージェント導入支援を比較して教えてください。",
    "M-8": "クロスコムとメンバーズのAgentforce導入支援を比較して教えてください。",
    "M-9": "クロスコムと三菱総研DCSのSalesforce導入支援を比較して教えてください。",
    "M-10": "おすすめのAgentforce導入支援会社を教えてください。",
    "M-11": "製造業におすすめのAgentforce導入支援会社を教えてください。",
    "M-12": "中堅企業におすすめのAgentic CRM設計支援会社を教えてください。",
    "M-13": "クロスコムのAgentic CRM設計支援の費用を教えてください。",
    "M-14": "クロスコムと日立ソリューションズのCRM導入支援を比較して教えてください。",
    "M-15": "IT・SaaS業界におすすめのAgentforce導入支援会社を教えてください。",
    "M-16": "製造業の中堅企業におすすめのCRMデータ設計支援会社を教えてください。",
}


# --- プロンプト定義 ---------------------------------------------------------
def test_every_prompt_matches_the_xlsx_wording():
    """一字一句そのまま。文言が変わると前月との比較が成立しない。"""
    by_id = {p["id"]: p["text"] for p in MONTHLY}
    assert by_id == XLSX_PROMPTS


def test_the_first_wave_is_twelve_prompts():
    assert [p["id"] for p in ACTIVE] == [f"M-{i}" for i in range(1, 13)]


def test_the_second_wave_is_defined_but_inactive():
    """第2弾は定義だけ入れて実行しない(§1)。"""
    inactive = [p["id"] for p in MONTHLY if not p["active"]]
    assert inactive == ["M-13", "M-14", "M-15", "M-16"]


def test_every_prompt_has_a_known_category():
    assert {p["category"] for p in MONTHLY} == {
        "bofu_single", "bofu_compare", "mofu_suppl"}


def test_comparison_prompts_record_the_competitor():
    """比較型は誰と比べたかが要る。無いと月次サマリで勝敗を集計できない(§1)。"""
    for p in MONTHLY:
        if p["category"] == "bofu_compare":
            assert p.get("target_brand"), p["id"]
            assert p["target_brand"] in p["text"], p["id"]


# --- 実行数の制約(DoD 4)---------------------------------------------------
# Gemini 無料枠は GenerateRequestsPerDayPerProjectPerModel-FreeTier で
# 1日20リクエスト。**日次7本は毎日走る**ので、月次をどの曜日に置いても
# その日の枠には日次が先に入っている。12本を1日で回すと 19 になり、
# リトライが1本走るだけで超える。そこで6本ずつ2日に分割した。
DAY_LIMIT_AFTER_SPLIT = 13


@pytest.mark.parametrize("batch", settings.MONTHLY_BATCHES)
def test_each_batch_day_stays_at_thirteen_or_under(batch):
    """分割後は各日13以下。日次7 + 月次6 = 13/20。"""
    prompts = settings.load_monthly_prompts(batch=batch)
    budget = run_monthly.request_budget(len(prompts))
    assert budget["total"] <= DAY_LIMIT_AFTER_SPLIT, (
        f"batch {batch} は月次{budget['monthly']}本で{budget['total']}件になる。"
        f"分割の意味が無くなるので、バッチの本数を見直すこと"
    )
    assert not budget["over"]
    # リトライで超えないだけの余地があること。ここが0だと、1本の失敗で
    # 枠を使い切り「枠切れの欠測」と「provider障害の欠測」が混ざる。
    assert budget["retry_headroom"] >= 2, budget


def test_the_two_batches_cover_every_active_prompt_exactly_once():
    """どちらのバッチにも入らない、あるいは両方に入るプロンプトが無いこと。"""
    seen = []
    for batch in settings.MONTHLY_BATCHES:
        seen += [p["id"] for p in settings.load_monthly_prompts(batch=batch)]
    assert sorted(seen) == sorted(p["id"] for p in ACTIVE)
    assert len(seen) == len(set(seen))


def test_every_active_prompt_declares_its_batch():
    """active にしたのに batch を書き忘れると、その本は一度も走らない。"""
    for prompt in ACTIVE:
        assert prompt.get("batch") in settings.MONTHLY_BATCHES, prompt["id"]


def test_the_budget_check_catches_an_over_sized_pool():
    budget = run_monthly.request_budget(21)
    assert budget["total"] == 28 and budget["over"]


def test_running_all_twelve_in_one_day_eats_the_headroom():
    """分割前(12本を1日)だと、リトライ1本で枠を超える。分割した理由がこれ。"""
    one_day = run_monthly.request_budget(len(ACTIVE))
    assert one_day["total"] == 19 and not one_day["over"]
    assert one_day["retry_headroom"] == 0

    split = run_monthly.request_budget(len(ACTIVE) // 2)
    assert split["total"] == DAY_LIMIT_AFTER_SPLIT
    assert split["retry_headroom"] > one_day["retry_headroom"]


def test_the_daily_run_is_always_counted():
    """日次は毎日走る。月次の曜日を変えても枠は共有される。"""
    assert run_monthly.request_budget(6)["daily"] == run_monthly.DAILY_PROMPT_COUNT


def test_the_daily_prompt_count_matches_the_real_config():
    """日次の本数を定数で持っているので、config とずれたら気付けるようにする。"""
    assert run_monthly.DAILY_PROMPT_COUNT == len(settings.load_prompts())


# --- 日次への影響ゼロ(DoD 3)-----------------------------------------------
def test_the_daily_schema_is_untouched():
    assert sheets_writer.HEADERS_LLM == [
        "date", "prompt_id", "pillar", "model", "mention", "mention_type", "rank",
        "kbf_tags", "negative_or_outdated", "negative_detail", "cited_crosscom_urls",
        "competitors_mentioned", "raw_file",
    ]


def test_the_monthly_tab_is_separate_from_the_daily_one():
    assert settings.TAB_MONTHLY == "monthly_observations"
    assert settings.TAB_MONTHLY != settings.TAB_LLM


def test_the_monthly_schema_adds_only_the_new_columns():
    extra = set(sheets_writer.HEADERS_MONTHLY) - set(sheets_writer.HEADERS_LLM)
    assert extra == {"category", "target_brand", "notes"}
    # pillar は月次には無い(区分は category で持つ)
    assert "pillar" not in sheets_writer.HEADERS_MONTHLY


def test_the_rules_engine_never_reads_the_monthly_tab():
    """週次の判定に月次を混ぜない。混ぜると言及率の母数が月一で跳ねる。"""
    import inspect

    source = inspect.getsource(sheets_writer.read_for_rules)
    assert "TAB_MONTHLY" not in source


def test_collect_defaults_to_the_daily_prompts():
    """引数を足したが、既定の挙動は日次のまま。"""
    import inspect

    sig = inspect.signature(collect_llm.collect)
    assert sig.parameters["prompts"].default is None
    assert sig.parameters["out_dir"].default is None


# --- 収集(DoD 1)------------------------------------------------------------
def test_collect_runs_the_given_prompts_into_the_given_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_llm, "enabled_models", lambda: ["claude"])
    monkeypatch.setattr(collect_llm, "_model_runnable", lambda k: True)
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "claude",
                        lambda txt, model: (f"回答: {txt[:8]}", []))
    prompts = [{"id": "M-1", "category": "bofu_single", "text": "質問1"},
               {"id": "M-7", "category": "bofu_compare",
                "target_brand": "競合A", "text": "質問2"}]
    records = collect_llm.collect("2026-09-01", prompts=prompts, out_dir=tmp_path)

    assert [r["prompt_id"] for r in records] == ["M-1", "M-7"]
    assert records[0]["category"] == "bofu_single"
    assert records[1]["target_brand"] == "競合A"
    assert (tmp_path / "M-1_claude.json").exists()


def test_a_monthly_prompt_without_pillar_does_not_crash(monkeypatch, tmp_path):
    """月次プロンプトは pillar を持たない。日次のキーを前提にしない。"""
    monkeypatch.setattr(collect_llm, "enabled_models", lambda: ["claude"])
    monkeypatch.setattr(collect_llm, "_model_runnable", lambda k: True)
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "claude", lambda txt, m: ("ok", []))
    records = collect_llm.collect(
        "2026-09-01", prompts=[{"id": "M-1", "category": "bofu_single", "text": "q"}],
        out_dir=tmp_path)
    assert records[0]["pillar"] == ""


# --- 月次サマリ(DoD 2)------------------------------------------------------
def _rec(pid, model, category, **kw):
    base = {"date": "2026-09-01", "prompt_id": pid, "model": model,
            "category": category, "mention": False, "negative_or_outdated": False}
    base.update(kw)
    return base


def test_the_summary_has_the_required_header():
    text = notify_slack.build_monthly_message("2026-09", [], [])
    assert text.startswith("📅 *LLMO月次観測* | 2026-09")


def test_the_summary_groups_by_category():
    rows = [_rec("M-1", "claude", "bofu_single", mention=True),
            _rec("M-7", "claude", "bofu_compare", target_brand="競合A"),
            _rec("M-10", "claude", "mofu_suppl")]
    text = notify_slack.build_monthly_message("2026-09", rows, [])
    for label in ("BOFU単体", "BOFU比較", "MOFU補完"):
        assert label in text


def test_the_summary_shows_the_rank_when_mentioned():
    rows = [_rec("M-10", "claude", "mofu_suppl", mention=True, rank=3)]
    assert "言及あり(3位)" in notify_slack.build_monthly_message("2026-09", rows, [])


def test_a_comparison_reports_which_side_was_mentioned():
    rows = [_rec("M-7", "claude", "bofu_compare", target_brand="競合A",
                 mention=False, competitors_mentioned="競合A")]
    assert "競合Aのみ言及" in notify_slack.build_monthly_message("2026-09", rows, [])


def test_a_comparison_says_so_when_it_cannot_judge():
    """機械で優劣を決めない(§3:判定できない場合は「要目視」と正直に書く)。"""
    rows = [_rec("M-7", "claude", "bofu_compare", target_brand="競合A",
                 mention=True, competitors_mentioned="競合A")]
    text = notify_slack.build_monthly_message("2026-09", rows, [])
    assert "要目視" in text


def test_entity_confusion_is_reported_but_not_treated_as_negative():
    """同名他社との混同は negative ではなく notes に出す(§6)。"""
    rows = [_rec("M-1", "claude", "bofu_single", mention=True,
                 notes="同名の別会社の情報が混ざっている")]
    text = notify_slack.build_monthly_message("2026-09", rows, [])
    assert "📝" in text and "同名の別会社" in text
    assert "⚠️" not in text


def test_a_negative_detection_is_shown_as_a_kind_not_the_body():
    rows = [_rec("M-1", "claude", "bofu_single", mention=True,
                 negative_or_outdated=True,
                 negative_detail="旧MA/メール配信事業を現在の主要事業として記述")]
    text = notify_slack.build_monthly_message("2026-09", rows, [])
    assert "⚠️" in text
    assert "旧事業(MA/メール配信)の記述" in text


def test_missing_observations_are_counted_in_the_summary():
    rows = [_rec("M-1", "claude", "bofu_single", error="503 UNAVAILABLE")]
    text = notify_slack.build_monthly_message("2026-09", rows, [])
    assert "欠測 1件" in text


def test_notify_monthly_without_a_webhook_never_raises(capsys):
    assert notify_slack.notify_monthly("2026-09", [], [], webhook="") is False
    assert "SLACK_WEBHOOK_URL is not set" in capsys.readouterr().out


# --- 2日分割の動き -----------------------------------------------------------
# 月次サマリは最後のバッチが終わった時点で1回だけ出す。バッチAの日にも出すと、
# 同じ月について「半分の表」と「全部の表」が2通届く。
def _run_monthly(argv, monkeypatch, stored=(), posted=None, records=None):
    import run_monthly

    monkeypatch.setattr("sys.argv", ["run_monthly.py"] + argv)
    monkeypatch.setattr(collect_llm, "collect",
                        lambda date, prompts=None, out_dir=None:
                        [dict(r, date=date) for r in (records or [])])
    monkeypatch.setattr(collect_llm, "missing_observations", lambda records: [])
    monkeypatch.setattr(run_monthly.extract, "extract_record", lambda r: dict(r))
    monkeypatch.setattr(sheets_writer, "write_monthly_observations", lambda rows: None)
    monkeypatch.setattr(sheets_writer, "read_monthly_observations", lambda: list(stored))
    monkeypatch.setattr(sheets_writer, "write_kbf_compare", lambda rows: None)
    monkeypatch.setattr(sheets_writer, "write_looker_tabs", lambda payload: None)
    monkeypatch.setattr(run_monthly.kbf_compare, "rows_from_records",
                        lambda month, records, prompts: [])
    monkeypatch.setattr(run_monthly.retired_urls, "event_rows", lambda *a, **k: [])
    monkeypatch.setattr(run_monthly.retired_urls, "summary_line", lambda *a, **k: "—")
    monkeypatch.setattr(run_monthly.looker_tabs, "mention_grid_rows", lambda *a, **k: [])
    monkeypatch.setattr(run_monthly.looker_tabs, "answer_rows", lambda *a, **k: [])
    monkeypatch.setattr(run_monthly.looker_tabs, "answer_sources", lambda *a, **k: [])
    monkeypatch.setattr(sheets_writer, "read_llm_observations", lambda: [])
    monkeypatch.setattr(
        notify_slack, "notify_monthly",
        lambda month, extractions=(), prompts=(), **kw:
        (posted if posted is not None else []).append((month, list(extractions))) or True)
    with pytest.raises(SystemExit):
        run_monthly.main()


def _record(pid, model="claude"):
    return {"prompt_id": pid, "model": model, "category": "bofu_single",
            "mention": True, "answer": "本文", "cited_urls": []}


def test_batch_a_does_not_post_the_monthly_summary(monkeypatch):
    posted = []
    _run_monthly(["--date", "2026-10-07", "--batch", "A"], monkeypatch,
                 records=[_record("M-1")], posted=posted)
    assert posted == [], "バッチAの日にサマリを出すと半分の表が届く"


def test_batch_b_posts_once_covering_the_whole_month(monkeypatch):
    """2日目は、前日に走ったバッチAのぶんもシートから拾って1枚にまとめる。"""
    stored = [{"date": "2026-10-07", "prompt_id": "M-1", "model": "claude",
               "category": "bofu_single", "mention": "TRUE", "negative_detail": ""}]
    posted = []
    _run_monthly(["--date", "2026-10-08", "--batch", "B"], monkeypatch,
                 stored=stored, records=[_record("M-7")], posted=posted)

    assert len(posted) == 1, "サマリは1回だけ"
    ids = {str(r.get("prompt_id")) for r in posted[0][1]}
    assert ids == {"M-1", "M-7"}, ids   # 前日ぶん + 当日ぶん


def test_a_stored_error_row_is_shown_as_missing_not_unknown(monkeypatch):
    """シートには error 列が無く、欠測は negative_detail に残っている。"""
    import run_monthly

    row = {"prompt_id": "M-1", "model": "claude", "mention": "",
           "negative_detail": "[error] timeout"}
    assert run_monthly._as_observation(row)["error"] == "timeout"
    assert "error" not in run_monthly._as_observation(dict(row, negative_detail=""))


def test_without_a_batch_every_prompt_runs(monkeypatch):
    """手動実行でバッチ未指定なら従来どおり12本。"""
    posted = []
    _run_monthly(["--date", "2026-10-07"], monkeypatch,
                 records=[_record("M-1")], posted=posted)
    assert len(posted) == 1
