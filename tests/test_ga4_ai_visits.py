"""AI 経由の訪問の一覧(src/ga4_ai_visits.py・手動実行のジョブ)。GA4 は呼ばず、作り物の結果で確かめる.

1. 単位は 日付 × 参照元 × 着地ページ。セッション数・閲覧ページ数・フォーム到達・キーイベント数
2. AI の参照元だけ(settings.AI_SOURCE_FRAGMENTS)。フォーム到達は /contact/・/download-paper/ で絞った2本目の問い合わせ
3. 月ごとの合計と、シート ga4_ai_traffic との日付ごとの違い(違う日だけ)
4. 手動実行だけのワークフロー。日次・実験のジョブは変えない
"""
import csv

import yaml

import ga4_ai_visits as g
import settings

BASE = [
    {"date": "2026-09-03", "source": "chatgpt.com", "landing_page": "/a/", "sessions": 2, "screenPageViews": 5, "keyEvents": 1},
    {"date": "2026-09-03", "source": "google", "landing_page": "/a/", "sessions": 9, "screenPageViews": 9, "keyEvents": 0},
    {"date": "2026-10-10", "source": "gemini.google.com", "landing_page": "/b/", "sessions": 1, "screenPageViews": 1, "keyEvents": 0},
]
FORM = [{"date": "2026-09-03", "source": "chatgpt.com", "landing_page": "/a/", "sessions": 1}]


def test_queries_ask_for_the_finest_unit_and_the_form_pages():
    q = g.queries("2026-09-01", "2026-11-16")
    assert q["base"]["dimensions"] == ["date", "sessionSource", "landingPagePlusQueryString"]
    assert q["base"]["metrics"] == ["sessions", "screenPageViews", "keyEvents"] and q["base"]["page_regex"] is None
    assert q["form"]["metrics"] == ["sessions"]
    import re
    rx = re.compile(q["form"]["page_regex"])
    assert all(rx.match(p) for p in ["/contact/", "/contact/thanks/", "/download-paper/agentforce/", "/contact"])
    assert not any(rx.match(p) for p in ["/agentforce-contact/", "/blog/contact/", "/"])
    assert g.ga4_date("20260903") == "2026-09-03"


def test_merge_keeps_ai_sources_and_adds_form_reach():
    rows = g.merge(BASE, FORM)
    assert rows == [
        {"date": "2026-09-03", "source": "chatgpt.com", "landing_page": "/a/", "sessions": 2, "page_views": 5,
         "form_reach_sessions": 1, "key_events": 1},
        {"date": "2026-10-10", "source": "gemini.google.com", "landing_page": "/b/", "sessions": 1, "page_views": 1,
         "form_reach_sessions": 0, "key_events": 0}]
    m = g.monthly(rows)
    assert m["2026-09"]["sessions"] == 2 and m["2026-09"]["form_reach_sessions"] == 1 and m["2026-10"]["by_source"]["gemini.google.com"] == 1


def test_compare_with_sheet_lists_only_days_that_differ():
    rows = g.merge(BASE, FORM)
    sheet = [{"date": "2026-09-03", "source": "chatgpt.com", "sessions": "2"},
             {"date": "2026-10-11", "source": "perplexity.ai", "sessions": "1"},
             {"date": "2026-12-01", "source": "chatgpt.com", "sessions": "5"}]           # 期間外
    assert g.compare_with_sheet(rows, sheet, "2026-09-01", "2026-11-16") == [
        {"date": "2026-10-10", "ga4": 1, "sheet": 0, "diff": 1},
        {"date": "2026-10-11", "ga4": 0, "sheet": 1, "diff": -1}]


def test_main_writes_the_csv_and_the_report(tmp_path):
    def runner(q):
        return FORM if q["page_regex"] else BASE
    assert g.main(["--start", "2026-09-01", "--end", "2026-11-16"], runner=runner,
                  sheet_reader=lambda: [], out_dir=tmp_path) == 0
    with open(tmp_path / "ai_visits_20260901_20261116.csv", encoding="utf-8", newline="") as fh:
        got = list(csv.DictReader(fh))
    assert list(got[0]) == g.FIELDS and len(got) == 2
    md = (tmp_path / "ai_visits_20260901_20261116.md").read_text(encoding="utf-8")
    assert g.UNIT_NOTE in md and "| 2026-09 | 2 | 5 | 1 | 1 | chatgpt.com 2 |" in md
    assert "| 2026-10-10 | 1 | 0 | +1 |" in md


def test_a_broken_sheet_does_not_stop_the_list(tmp_path):
    def broken():
        raise RuntimeError("no sheet")
    assert g.main([], runner=lambda q: [], sheet_reader=broken, out_dir=tmp_path) == 0
    assert "シートを読めなかったため比べていない" in (tmp_path / "ai_visits_20260901_20261116.md").read_text(encoding="utf-8")


def test_the_workflow_is_manual_only_and_uses_the_secrets():
    wf = yaml.safe_load((settings.ROOT_DIR / ".github/workflows/ga4_ai_visits.yml").read_text(encoding="utf-8"))
    on = wf[True] if True in wf else wf["on"]
    assert list(on) == ["workflow_dispatch"], "手動実行だけ(schedule なし)"
    assert on["workflow_dispatch"]["inputs"]["start"]["default"] == "2026-09-01"
    assert on["workflow_dispatch"]["inputs"]["end"]["default"] == "2026-11-16"
    env = wf["jobs"]["ga4_ai_visits"]["env"]
    assert env["GA4_PROPERTY_ID"] == "${{ secrets.GA4_PROPERTY_ID }}"
    steps = " ".join(str(s.get("run", "")) for s in wf["jobs"]["ga4_ai_visits"]["steps"])
    assert "python src/ga4_ai_visits.py" in steps and "git add output/reports/ai_visits_" in steps


def test_the_real_request_object_has_the_filters():
    import pytest
    pytest.importorskip("google.analytics.data_v1beta")
    q = g.queries("2026-09-01", "2026-11-16")
    base = g.build_request(q["base"], "123")
    assert base.property == "properties/123" and base.date_ranges[0].start_date == "2026-09-01"
    assert [d.name for d in base.dimensions] == ["date", "sessionSource", "landingPagePlusQueryString"]
    assert [m.name for m in base.metrics] == ["sessions", "screenPageViews", "keyEvents"]
    sources = [e.filter.string_filter.value for e in base.dimension_filter.or_group.expressions]
    assert sources == list(settings.AI_SOURCE_FRAGMENTS)
    form = g.build_request(q["form"], "123")
    parts = form.dimension_filter.and_group.expressions
    assert parts[1].filter.field_name == "pagePath" and parts[1].filter.string_filter.value == g.FORM_PAGE_REGEX
