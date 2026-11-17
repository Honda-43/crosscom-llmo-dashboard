"""ga4_ai_visits.py — AI 経由の訪問の一覧を GA4 Data API から取り直す(2026-11-17・戦略管制塔の採否).

手動実行のジョブ(.github/workflows/ga4_ai_visits.yml)だけが呼ぶ。日次ジョブ(collect_ga4.py・シート ga4_ai_traffic)は変えない。

    python src/ga4_ai_visits.py --start 2026-09-01 --end 2026-11-16

出すもの(output/reports/)
- ai_visits_<開始>_<終了>.csv:日付 × 参照元 × 着地ページごとに、セッション数・閲覧ページ数・フォーム到達・キーイベント数
- ai_visits_<開始>_<終了>.md:月ごとの合計(参照元別も)と、シート ga4_ai_traffic のセッション数との日付ごとの違い

GA4 では訪問1回ごとの記録は取り出せない(Data API は集計値だけを返す)。日付 × 参照元 × 着地ページが最も細かい単位。

- AI の参照元:settings.AI_SOURCE_FRAGMENTS(chatgpt.com・chat.openai.com・perplexity.ai・gemini.google.com・
  copilot.microsoft.com・claude.ai・bing.com/chat)のどれかを sessionSource に含むもの(大文字小文字は無視)
- フォーム到達:そのセッションの中で、問い合わせフォームのページ(FORM_PAGE_REGEX:/contact/ と資料請求の /download-paper/)
  を見たセッションの数。ページ(pagePath)で絞った2本目の問い合わせで取る(1つのセッションで2ページ見ても1と数える)
- 閲覧ページ数:screenPageViews。キーイベント数:keyEvents
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings import AI_SOURCE_FRAGMENTS, GA4_PROPERTY_ID, ROOT_DIR  # noqa: E402

REPORTS_DIR = ROOT_DIR / "output" / "reports"
FORM_PAGE_REGEX = r"^/(contact|download-paper)(/.*)?$"
FIELDS = ["date", "source", "landing_page", "sessions", "page_views", "form_reach_sessions", "key_events"]
UNIT_NOTE = ("GA4 では訪問1回ごとの記録は取り出せない（Data API は集計値だけを返す）。"
             "日付 × 参照元 × 着地ページが最も細かい単位")

Key = Tuple[str, str, str]
Runner = Callable[[Dict[str, Any]], List[Dict[str, Any]]]


def is_ai_source(source: str) -> bool:
    low = str(source or "").lower()
    return any(frag in low for frag in AI_SOURCE_FRAGMENTS)


def ga4_date(value: str) -> str:
    """GA4 の date(YYYYMMDD)を YYYY-MM-DD に。"""
    v = str(value)
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else v


def queries(start: str, end: str) -> Dict[str, Dict[str, Any]]:
    """2本の問い合わせの中身(GA4 に依存しない形。テストで確かめる)。"""
    dims = ["date", "sessionSource", "landingPagePlusQueryString"]
    return {
        "base": {"start": start, "end": end, "dimensions": dims,
                 "metrics": ["sessions", "screenPageViews", "keyEvents"], "page_regex": None},
        "form": {"start": start, "end": end, "dimensions": dims,
                 "metrics": ["sessions"], "page_regex": FORM_PAGE_REGEX},
    }


def build_request(q: Dict[str, Any], property_id: str, offset: int = 0, limit: int = 100000):
    """GA4 Data API の RunReportRequest(参照元は AI だけ。フォーム到達はページでも絞る)。"""
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression,
                                                    FilterExpressionList, Metric, RunReportRequest)

    source_filter = FilterExpression(or_group=FilterExpressionList(expressions=[
        FilterExpression(filter=Filter(field_name="sessionSource", string_filter=Filter.StringFilter(
            match_type=Filter.StringFilter.MatchType.CONTAINS, value=frag, case_sensitive=False)))
        for frag in AI_SOURCE_FRAGMENTS]))
    flt = source_filter
    if q["page_regex"]:
        page = FilterExpression(filter=Filter(field_name="pagePath", string_filter=Filter.StringFilter(
            match_type=Filter.StringFilter.MatchType.FULL_REGEXP, value=q["page_regex"])))
        flt = FilterExpression(and_group=FilterExpressionList(expressions=[source_filter, page]))
    return RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=q["start"], end_date=q["end"])],
        dimensions=[Dimension(name=d) for d in q["dimensions"]],
        metrics=[Metric(name=m) for m in q["metrics"]],
        dimension_filter=flt, limit=limit, offset=offset)


def run_ga4(q: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GA4 Data API で1本の問い合わせを投げ、[{date, source, landing_page, <metric>...}] を返す(AI の参照元だけ)。"""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from settings import google_credentials

    client = BetaAnalyticsDataClient(credentials=google_credentials())
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = client.run_report(build_request(q, GA4_PROPERTY_ID, offset=offset))
        for row in resp.rows:
            rec = {"date": ga4_date(row.dimension_values[0].value), "source": row.dimension_values[1].value or "",
                   "landing_page": row.dimension_values[2].value or ""}
            for i, m in enumerate(q["metrics"]):
                rec[m] = int(float(row.metric_values[i].value or 0))
            out.append(rec)
        offset += len(resp.rows)
        if not resp.rows or offset >= resp.row_count:
            break
    return out


def merge(base: Iterable[Dict[str, Any]], form: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """2本の結果を 日付 × 参照元 × 着地ページ でまとめる(AI の参照元だけ・日付順)。"""
    rows: Dict[Key, Dict[str, Any]] = {}
    for r in base:
        if not is_ai_source(r["source"]):
            continue
        k = (r["date"], r["source"], r["landing_page"])
        rows[k] = {"date": k[0], "source": k[1], "landing_page": k[2], "sessions": r.get("sessions", 0),
                   "page_views": r.get("screenPageViews", 0), "form_reach_sessions": 0,
                   "key_events": r.get("keyEvents", 0)}
    for r in form:
        if not is_ai_source(r["source"]):
            continue
        k = (r["date"], r["source"], r["landing_page"])
        if k not in rows:            # 基本の問い合わせに無い組(起きないはず)も落とさない
            rows[k] = {"date": k[0], "source": k[1], "landing_page": k[2], "sessions": 0, "page_views": 0,
                       "form_reach_sessions": 0, "key_events": 0}
        rows[k]["form_reach_sessions"] += r.get("sessions", 0)
    return [rows[k] for k in sorted(rows)]


def monthly(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{月: {sessions, page_views, form_reach_sessions, key_events, by_source: Counter(セッション)}}。"""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m = out.setdefault(r["date"][:7], {"sessions": 0, "page_views": 0, "form_reach_sessions": 0,
                                           "key_events": 0, "by_source": collections.Counter()})
        for col in ("sessions", "page_views", "form_reach_sessions", "key_events"):
            m[col] += int(r[col])
        m["by_source"][r["source"]] += int(r["sessions"])
    return dict(sorted(out.items()))


def compare_with_sheet(rows: Iterable[Dict[str, Any]], sheet: Iterable[Dict[str, Any]],
                       start: str, end: str) -> List[Dict[str, Any]]:
    """日付ごとのセッション数(取り直し と シート ga4_ai_traffic)で、違う日だけ。"""
    ga4 = collections.Counter()
    for r in rows:
        ga4[r["date"]] += int(r["sessions"])
    sh = collections.Counter()
    for r in sheet:
        d = str(r.get("date", ""))[:10]
        if start <= d <= end and is_ai_source(r.get("source", "")):
            sh[d] += int(float(r.get("sessions") or 0))
    days = sorted(set(ga4) | set(sh))
    return [{"date": d, "ga4": ga4[d], "sheet": sh[d], "diff": ga4[d] - sh[d]} for d in days if ga4[d] != sh[d]]


def render(start: str, end: str, rows: List[Dict[str, Any]], diffs: Optional[List[Dict[str, Any]]],
           csv_name: str) -> str:
    lines = [f"# AI 経由の訪問の一覧（GA4 から取り直し・{start}〜{end}）", "",
             f"- 明細：`output/reports/{csv_name}`（{len(rows)}行）", f"- {UNIT_NOTE}",
             "- 参照元：sessionSource に " + "・".join(AI_SOURCE_FRAGMENTS) + " のどれかを含むもの",
             f"- フォーム到達：問い合わせフォームのページ（`{FORM_PAGE_REGEX}`：/contact/ と資料請求の /download-paper/）を見たセッションの数",
             "- 閲覧ページ数は screenPageViews、キーイベント数は keyEvents", "",
             "## 月ごとの合計", "",
             "| 月 | セッション | 閲覧ページ数 | フォーム到達 | キーイベント | 参照元ごとのセッション |", "|---|---|---|---|---|---|"]
    for month, m in monthly(rows).items():
        src = "・".join(f"{s} {c}" for s, c in m["by_source"].most_common())
        lines.append(f"| {month} | {m['sessions']} | {m['page_views']} | {m['form_reach_sessions']} | {m['key_events']} | {src} |")
    lines += ["", "## シート ga4_ai_traffic との違い（日付ごとのセッション数・違う日だけ）", ""]
    if diffs is None:
        lines.append("- シートを読めなかったため比べていない")
    elif not diffs:
        lines.append("- 違いなし")
    else:
        lines += ["| 日付 | 取り直し | シート | 差 |", "|---|---|---|---|"]
        lines += [f"| {d['date']} | {d['ga4']} | {d['sheet']} | {d['diff']:+d} |" for d in diffs]
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(argv: Optional[List[str]] = None, runner: Optional[Runner] = None,
         sheet_reader: Optional[Callable[[], List[Dict[str, Any]]]] = None,
         out_dir: Path = REPORTS_DIR) -> int:
    ap = argparse.ArgumentParser(description="AI 経由の訪問の一覧を GA4 から取り直す")
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-11-16")
    a = ap.parse_args(argv)
    dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    if runner is None:
        if not GA4_PROPERTY_ID:
            print("[error] GA4_PROPERTY_ID が無い(GitHub の secrets から渡す)", file=sys.stderr)
            return 1
        runner = run_ga4
    q = queries(a.start, a.end)
    rows = merge(runner(q["base"]), runner(q["form"]))
    diffs: Optional[List[Dict[str, Any]]]
    try:
        if sheet_reader is None:
            import sheets_writer
            sheet_reader = sheets_writer.read_ga4
        diffs = compare_with_sheet(rows, sheet_reader(), a.start, a.end)
    except Exception as exc:  # noqa: BLE001 - シートが読めなくても一覧は出す
        print(f"[warn] シート ga4_ai_traffic を読めなかった: {exc}", file=sys.stderr)
        diffs = None
    stem = f"ai_visits_{a.start.replace('-', '')}_{a.end.replace('-', '')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / f"{stem}.csv", rows)
    text = render(a.start, a.end, rows, diffs, f"{stem}.csv")
    (out_dir / f"{stem}.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
