"""collect_gsc.py — Search Console (§5, daily).

Two independent collections from the same API:

* **branded queries** (``collect``) — the date 3 days ago (GSC data-finalisation
  lag), branded queries only, clicks / impressions. Unchanged since §5.
* **pages** (``collect_pages``, 2026-09-14) — article-level rows for the
  gsc_pages tab: date × page with impressions / clicks / position / queries.
  This is the unit of the difference-in-differences analysis
  (output/reports/measurement_design_2026-09-14.md §3-1).
"""
from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urldefrag

from settings import BRANDED_QUERY_FRAGMENTS, GSC_SITE_URL, google_credentials

# 1リクエストで返る行の上限(API仕様)。これちょうど返ってきたら続きがある。
ROW_LIMIT = 25000
# GSC が保持している期間。これより前はAPIが何も返さない。
RETENTION_MONTHS = 16
# 期間をまとめて取るときの1リクエストあたりの日数。
# page × query × date は行数が多いので、月単位より細かくはしない程度に割る。
CHUNK_DAYS = 30
FINALISATION_LAG_DAYS = 3


def _three_days_ago_utc() -> str:
    return (dt.datetime.utcnow().date()
            - dt.timedelta(days=FINALISATION_LAG_DAYS)).strftime("%Y-%m-%d")


def _is_branded(query: str) -> bool:
    low = query.lower()
    return any(frag.lower() in low for frag in BRANDED_QUERY_FRAGMENTS)


def _service():
    from googleapiclient.discovery import build

    return build("searchconsole", "v1", credentials=google_credentials())


def collect(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return rows: {date, query, clicks, impressions}."""
    date = date or _three_days_ago_utc()
    if not GSC_SITE_URL:
        print("[warn] GSC_SITE_URL not set — skipping GSC collection.")
        return []

    service = _service()
    body = {
        "startDate": date,
        "endDate": date,
        "dimensions": ["query", "date"],
        "rowLimit": 25000,
    }
    response = (
        service.searchanalytics()
        .query(siteUrl=GSC_SITE_URL, body=body)
        .execute()
    )

    rows: List[Dict[str, Any]] = []
    for row in response.get("rows", []):
        query = row["keys"][0]
        if not _is_branded(query):
            continue
        rows.append(
            {
                "date": date,
                "query": query,
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
            }
        )
    print(f"[ok] GSC {date}: {len(rows)} branded-query rows")
    return rows


# --------------------------------------------------------------------------
# 記事単位(gsc_pages)
# --------------------------------------------------------------------------
def query_all(service, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``startRow`` で送りながら全行を取る。

    上限ちょうどで打ち切られた応答をそのまま使うと、記事の一部が
    黙って欠ける(0 クリックと区別できない)。
    """
    rows: List[Dict[str, Any]] = []
    start = 0
    while True:
        response = (
            service.searchanalytics()
            .query(siteUrl=GSC_SITE_URL,
                   body=dict(body, rowLimit=ROW_LIMIT, startRow=start))
            .execute()
        )
        batch = response.get("rows", [])
        rows.extend(batch)
        if len(batch) < ROW_LIMIT:
            return rows
        start += len(batch)


def normalize_page(url: str) -> str:
    """``#見出し`` を落とす。

    GSC はジャンプリンク付きの URL を別ページとして返す。記事単位で見る
    ときに同じ記事が2行に割れると、施策を打った記事の数字が薄まる。
    """
    return urldefrag(str(url or "").strip())[0]


def aggregate_pages(page_rows: Iterable[Dict[str, Any]],
                    query_rows: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """API の生行を gsc_pages の行(date × page)にまとめる。

    ``page_rows``  … dimensions=['page', 'date'] の応答行
    ``query_rows`` … dimensions=['page', 'query', 'date'] の応答行

    - impressions / clicks は ``page_rows`` から取る。``query_rows`` は匿名化
      クエリが落ちるので、合計に使うと過少になる。
    - position は impressions で重み付けした平均(# 違いを合わせたとき用)。
    - queries はその日にその記事が表示された**匿名化されていない**クエリの種類数。
    - # 違いを合わせると、同じ検索結果に両方出た表示は2回に数えられる
      (GSC のページ別集計の仕様)。記事単位の比較では割れるより害が小さい。
    """
    totals: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
        lambda: {"impressions": 0.0, "clicks": 0.0, "weighted_position": 0.0})
    for row in page_rows:
        page, date = row["keys"][0], row["keys"][1]
        key = (date, normalize_page(page))
        impressions = float(row.get("impressions", 0) or 0)
        entry = totals[key]
        entry["impressions"] += impressions
        entry["clicks"] += float(row.get("clicks", 0) or 0)
        entry["weighted_position"] += float(row.get("position", 0) or 0) * impressions

    queries: Dict[Tuple[str, str], set] = defaultdict(set)
    for row in query_rows:
        page, query, date = row["keys"][0], row["keys"][1], row["keys"][2]
        queries[(date, normalize_page(page))].add(query)

    out: List[Dict[str, Any]] = []
    for (date, page), entry in sorted(totals.items()):
        impressions = entry["impressions"]
        out.append({
            "date": date,
            "page": page,
            "impressions": int(impressions),
            "clicks": int(entry["clicks"]),
            "position": (round(entry["weighted_position"] / impressions, 2)
                         if impressions else ""),
            "queries": len(queries.get((date, page), ())),
        })
    return out


def date_chunks(start: str, end: str, days: int = CHUNK_DAYS) -> List[Tuple[str, str]]:
    """[start, end] を ``days`` 日ずつの閉区間に割る。"""
    lo, hi = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    chunks = []
    while lo <= hi:
        top = min(lo + dt.timedelta(days=days - 1), hi)
        chunks.append((lo.isoformat(), top.isoformat()))
        lo = top + dt.timedelta(days=1)
    return chunks


def retention_start(today: Optional[dt.date] = None) -> str:
    """GSC に残っている最古の日(今日から16か月前)。"""
    today = today or dt.datetime.utcnow().date()
    month_index = today.year * 12 + (today.month - 1) - RETENTION_MONTHS
    year, month = divmod(month_index, 12)
    month += 1
    # 月末をまたぐ日(例 31日)は、その月の末日に寄せる
    next_month = dt.date(year + (month // 12), month % 12 + 1, 1)
    last_day = (next_month - dt.timedelta(days=1)).day
    return dt.date(year, month, min(today.day, last_day)).isoformat()


def collect_pages(start: Optional[str] = None, end: Optional[str] = None,
                  service=None) -> List[Dict[str, Any]]:
    """記事単位の行を返す。既定は3日前の1日分(日次)。"""
    end = end or _three_days_ago_utc()
    start = start or end
    if not GSC_SITE_URL:
        print("[warn] GSC_SITE_URL not set — skipping GSC page collection.")
        return []

    service = service or _service()
    rows: List[Dict[str, Any]] = []
    for lo, hi in date_chunks(start, end):
        base = {"startDate": lo, "endDate": hi}
        page_rows = query_all(service, dict(base, dimensions=["page", "date"]))
        query_rows = query_all(service, dict(base, dimensions=["page", "query", "date"]))
        chunk = aggregate_pages(page_rows, query_rows)
        rows.extend(chunk)
        print(f"[ok] GSC pages {lo}..{hi}: {len(chunk)} rows")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="GSC collector (branded queries / pages)")
    ap.add_argument("--date", help="YYYY-MM-DD (default: 3 days ago UTC)")
    ap.add_argument("--pages", action="store_true",
                    help="記事単位(gsc_pages)を取る。未指定なら指名検索")
    ap.add_argument("--since", help="--pages の開始日(YYYY-MM-DD)")
    ap.add_argument("--until", help="--pages の終了日(既定: 3日前)")
    ap.add_argument("--backfill", action="store_true",
                    help="--pages を GSC の保持期間(16か月)いっぱいまで遡る")
    ap.add_argument("--write", action="store_true",
                    help="gsc_pages タブに書き込む(未指定なら件数を表示するだけ)")
    args = ap.parse_args()

    if not args.pages:
        collect(args.date)
        return

    until = args.until or args.date or _three_days_ago_utc()
    since = args.since or (retention_start() if args.backfill else until)
    rows = collect_pages(since, until)
    dates = sorted({r["date"] for r in rows})
    print(f"[summary] {since}..{until}: {len(rows)} rows / "
          f"{len({r['page'] for r in rows})} pages / {len(dates)} days"
          + (f"(実データ {dates[0]}〜{dates[-1]})" if dates else ""))
    if not args.write:
        print("[dry-run] 書き込みなし。書き込むには --write")
        return

    import sheets_writer

    sheets_writer.write_gsc_pages(rows)


if __name__ == "__main__":
    main()
