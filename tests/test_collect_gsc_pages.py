"""記事単位のGSC(gsc_pages)のテスト(2026-09-14)。APIもシートも呼ばない。"""
import datetime as dt

import collect_gsc
import sheets_writer


def page_row(page, date, impressions, clicks, position):
    return {"keys": [page, date], "impressions": impressions,
            "clicks": clicks, "position": position}


def query_row(page, query, date):
    return {"keys": [page, query, date], "impressions": 1, "clicks": 0, "position": 1}


# --- 集計 ---------------------------------------------------------------------
def test_rows_use_the_tab_columns():
    rows = collect_gsc.aggregate_pages([page_row("https://cross-com.jp/a/", "2026-09-01", 10, 1, 5.0)])
    assert list(rows[0]) == sheets_writer.HEADERS_GSC_PAGES


def test_fragments_are_merged_into_one_article():
    """#見出し 付きの行が別記事に割れると、施策を打った記事の数字が薄まる。"""
    rows = collect_gsc.aggregate_pages([
        page_row("https://cross-com.jp/a/", "2026-09-01", 30, 3, 4.0),
        page_row("https://cross-com.jp/a/#price", "2026-09-01", 10, 1, 8.0),
    ])
    assert len(rows) == 1
    row = rows[0]
    assert row["page"] == "https://cross-com.jp/a/"
    assert (row["impressions"], row["clicks"]) == (40, 4)
    assert row["position"] == 5.0          # (4×30 + 8×10) / 40。単純平均の6.0ではない


def test_totals_come_from_the_page_rows_not_the_query_rows():
    """page×query は匿名化クエリが落ちるので、合計に使うと過少になる。"""
    rows = collect_gsc.aggregate_pages(
        [page_row("https://cross-com.jp/a/", "2026-09-01", 100, 7, 3.0)],
        [query_row("https://cross-com.jp/a/", "q1", "2026-09-01")],
    )
    assert (rows[0]["impressions"], rows[0]["clicks"]) == (100, 7)


def test_queries_counts_distinct_queries_per_day():
    rows = collect_gsc.aggregate_pages(
        [page_row("https://cross-com.jp/a/", "2026-09-01", 10, 0, 3.0),
         page_row("https://cross-com.jp/a/", "2026-09-02", 10, 0, 3.0)],
        [query_row("https://cross-com.jp/a/", "q1", "2026-09-01"),
         query_row("https://cross-com.jp/a/#x", "q1", "2026-09-01"),   # 同じクエリは1つ
         query_row("https://cross-com.jp/a/", "q2", "2026-09-01"),
         query_row("https://cross-com.jp/a/", "q3", "2026-09-02")],
    )
    assert [(r["date"], r["queries"]) for r in rows] == [("2026-09-01", 2), ("2026-09-02", 1)]


def test_a_page_without_visible_queries_has_zero():
    rows = collect_gsc.aggregate_pages([page_row("https://cross-com.jp/a/", "2026-09-01", 3, 0, 9.0)])
    assert rows[0]["queries"] == 0


# --- ページ送り ---------------------------------------------------------------
class FakeService:
    """rowLimit ちょうどで返したら続きを取りに来るかを確かめる。"""

    def __init__(self, total):
        self.total, self.calls = total, []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.calls.append(body)
        start, limit = body["startRow"], body["rowLimit"]
        count = max(0, min(limit, self.total - start))
        rows = [{"keys": [f"p{start + i}", body["startDate"]]} for i in range(count)]
        return type("Req", (), {"execute": lambda _self: {"rows": rows}})()


def test_query_all_follows_the_pages(monkeypatch):
    monkeypatch.setattr(collect_gsc, "ROW_LIMIT", 3)
    service = FakeService(total=7)
    rows = collect_gsc.query_all(service, {"startDate": "2026-09-01", "endDate": "2026-09-01"})
    assert len(rows) == 7
    assert [c["startRow"] for c in service.calls] == [0, 3, 6]


def test_query_all_asks_once_more_when_the_last_page_is_exactly_full(monkeypatch):
    """ちょうど上限で終わったとき、続きが無いことは次の空応答でしか分からない。"""
    monkeypatch.setattr(collect_gsc, "ROW_LIMIT", 3)
    service = FakeService(total=6)
    assert len(collect_gsc.query_all(service, {"startDate": "d", "endDate": "d"})) == 6
    assert len(service.calls) == 3


# --- 期間 ---------------------------------------------------------------------
def test_date_chunks_cover_the_range_without_gaps():
    chunks = collect_gsc.date_chunks("2026-01-01", "2026-03-05", days=30)
    assert chunks[0] == ("2026-01-01", "2026-01-30")
    assert chunks[-1][1] == "2026-03-05"
    for (_, hi), (lo, _) in zip(chunks, chunks[1:]):
        assert dt.date.fromisoformat(lo) - dt.date.fromisoformat(hi) == dt.timedelta(days=1)


def test_a_single_day_is_one_chunk():
    assert collect_gsc.date_chunks("2026-09-11", "2026-09-11") == [("2026-09-11", "2026-09-11")]


def test_retention_start_is_sixteen_months_back():
    assert collect_gsc.retention_start(dt.date(2026, 9, 14)) == "2025-05-14"


def test_retention_start_clamps_to_the_end_of_a_short_month():
    assert collect_gsc.retention_start(dt.date(2026, 6, 30)) == "2025-02-28"


def test_collect_pages_splits_into_chunks_and_aggregates(monkeypatch):
    seen = []

    def fake_query_all(service, body):
        seen.append((body["startDate"], body["endDate"], tuple(body["dimensions"])))
        if body["dimensions"] == ["page", "date"]:
            return [page_row("https://cross-com.jp/a/", body["startDate"], 5, 1, 2.0)]
        return []

    monkeypatch.setattr(collect_gsc, "query_all", fake_query_all)
    monkeypatch.setattr(collect_gsc, "GSC_SITE_URL", "sc-domain:cross-com.jp")
    rows = collect_gsc.collect_pages("2026-01-01", "2026-02-15", service=object())
    assert len(seen) == 4                          # 2区間 × (page / page×query)
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-01-31"]


# --- 書き込みの範囲 ------------------------------------------------------------
def test_consecutive_rows_share_one_range():
    writes = [{"row": n, "values": [n]} for n in (5, 2, 3, 4, 9)]
    ranges = sheets_writer.contiguous_writes(writes)
    assert [(r["row"], len(r["values"])) for r in ranges] == [(2, 4), (9, 1)]
    assert ranges[0]["values"] == [[2], [3], [4], [5]]


def test_a_long_run_is_split_at_the_chunk_size():
    writes = [{"row": n, "values": [n]} for n in range(2, 12)]
    ranges = sheets_writer.contiguous_writes(writes, chunk=4)
    assert [(r["row"], len(r["values"])) for r in ranges] == [(2, 4), (6, 4), (10, 2)]
