"""取り下げたURLの引用カウントのテスト(A-011).

測りたいのは「ページを消してから、AIが引用をやめるまで何日か」。
そのため **引用が0の日も行を出す** ことが要件になる。行が消えると、
入れ替わったのか集計が止まったのかを後から区別できない。
"""
import looker_tabs
import retired_urls
from settings import RETIRED_URLS_FILE, load_yaml

DATE = "2026-09-05"
DELETED = "https://prtimes.jp/main/html/rd/p/000000003.000132405.html"
REPLACED = "https://prtimes.jp/main/html/searchrlp/company_id/132405"

RETIRED = [
    {"url": DELETED, "label": "削除したリリース", "retired_on": "2026-09-01",
     "action_id": "A-011", "status": "deleted"},
    {"url": REPLACED, "label": "企業ページ", "retired_on": "2026-09-01",
     "action_id": "A-011", "status": "replaced"},
]


def _obs(model, urls, prompt_id="E-1", date=DATE):
    """生データ(data/raw)1件の形。引用URLの全量はここにしかない。"""
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "cited_urls": list(urls)}


# --- 定義ファイル -----------------------------------------------------------
def test_the_config_lists_the_prtimes_urls_from_a011():
    data = load_yaml(RETIRED_URLS_FILE)["retired"]
    a011 = [r for r in data if r["action_id"] == "A-011"]
    assert len(a011) == 3
    assert all("prtimes.jp" in r["url"] for r in a011)


def test_every_entry_has_a_known_status():
    data = load_yaml(RETIRED_URLS_FILE)["retired"]
    assert data, "定義が空"
    assert {r["status"] for r in data} <= {"deleted", "replaced", "dead"}


def test_the_company_page_is_marked_replaced_not_deleted():
    """企業ページは404ではない(2026-09-01 時点で200)。同じ扱いにしない。"""
    data = {r["url"]: r for r in load_yaml(RETIRED_URLS_FILE)["retired"]}
    assert data[REPLACED]["status"] == "replaced"
    deleted = [r for r in data.values() if r["status"] == "deleted"]
    assert len(deleted) == 2


# --- カウント ---------------------------------------------------------------
def test_a_citation_of_a_deleted_url_is_counted():
    rows = [_obs("claude", [DELETED, "https://cross-com.jp/about/"])]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 1
    assert counts[DELETED]["models"] == ["claude"]


def test_citations_from_both_models_are_summed():
    rows = [_obs("claude", [DELETED]), _obs("gemini", [DELETED])]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 2
    assert counts[DELETED]["models"] == ["claude", "gemini"]


def test_zero_citations_still_produce_a_row():
    """0になった日が答えなので、行を消してはいけない。"""
    counts = retired_urls.count_citations([_obs("claude", [])], DATE, RETIRED)
    assert len(counts) == 2
    assert all(c["count"] == 0 for c in counts)


def test_only_e1_observations_are_counted():
    """指示は E-1 の引用を数えること。他のプロンプトは対象外。"""
    rows = [_obs("claude", [DELETED], prompt_id="A-1")]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 0


def test_other_days_are_not_counted():
    rows = [_obs("claude", [DELETED], date="2026-09-04")]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 0


def test_the_elapsed_days_since_retirement_are_computed():
    counts = retired_urls.count_citations([], DATE, RETIRED)
    assert all(c["days_since_retired"] == 4 for c in counts)


def test_the_self_domain_column_is_not_used_as_the_source():
    """cited_crosscom_urls は自社ドメインだけを残す列で、prtimes は入らない。

    ここを見ると常に0件になり「参照面が即日入れ替わった」と誤読する。
    生データの cited_urls を見ていることを固定する。
    """
    row = {"date": DATE, "prompt_id": "E-1", "model": "gemini",
           # 自社URLだけが入った列(シートの実態)と、全量が入った生データ
           "cited_crosscom_urls": "https://cross-com.jp/about/",
           "cited_urls": ["https://cross-com.jp/about/", DELETED]}
    counts = {c["url"]: c for c in retired_urls.count_citations([row], DATE, RETIRED)}
    assert counts[DELETED]["count"] == 1, "生データの cited_urls を見ていない"


def test_a_url_list_is_accepted_as_well_as_a_comma_string():
    """生レコード(リスト)とシート行(カンマ区切り)の両方を読む。"""
    rows = [{"date": DATE, "prompt_id": "E-1", "model": "claude",
             "cited_urls": [DELETED]}]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 1


# --- lk_events ---------------------------------------------------------------
def test_the_event_row_uses_the_looker_schema():
    rows = retired_urls.event_rows(DATE, [_obs("claude", [DELETED])], RETIRED)
    assert rows[0]["event_type"] == "retired_url_cited"
    assert rows[0]["event_name"] == "削除済みURLの引用"
    assert rows[0]["playbook_ref"] == "P-8"
    assert set(rows[0]) == {"date", "event_type", "event_name", "place",
                            "detail", "playbook_ref"}


def test_the_event_detail_says_whether_the_citation_continues():
    rows = {r["detail"] for r in
            retired_urls.event_rows(DATE, [_obs("claude", [DELETED])], RETIRED)}
    assert any("引用が続いている" in d and "取り下げから4日" in d for d in rows)
    assert any("引用なし" in d for d in rows)


def test_a_replaced_url_is_annotated_so_it_is_not_misread():
    rows = retired_urls.event_rows(DATE, [_obs("gemini", [REPLACED])], RETIRED)
    detail = next(r["detail"] for r in rows if "企業ページ" in r["detail"])
    assert "中身は現行事業に差し替え済み" in detail


def test_the_rows_are_merged_into_lk_events(monkeypatch):
    """既存の変化イベントと同じタブに合流する。"""
    monkeypatch.setattr(retired_urls, "load_retired", lambda force=False: RETIRED)
    payload = looker_tabs.build_all(
        DATE, observations=[], summary_rows=[],
        sov_rows=[], changes=[], action_rows=[], ga4_rows=[], gsc_rows=[],
        citation_rows=[], raw_records=[_obs("claude", [DELETED])],
    )
    events = payload["lk_events"]
    assert any(e["event_type"] == "retired_url_cited" for e in events)


# --- grounding のリダイレクト -----------------------------------------------
REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABCDEF"


def test_unresolved_redirects_are_counted_not_ignored():
    """解決しない設定では、見えていない件数を持ち回る。

    0件を「引用が止まった」と読ませないため。E-1 の引用の約6割が
    リダイレクトなので、黙って0に含めると測定そのものが嘘になる。
    """
    rows = [_obs("gemini", [REDIRECT, REDIRECT])]
    counts = retired_urls.count_citations(rows, DATE, RETIRED, resolve=False)
    assert all(c["count"] == 0 for c in counts)
    assert counts[0]["unresolved"] == 2


def test_a_resolved_redirect_is_matched(monkeypatch):
    monkeypatch.setattr(retired_urls, "resolve_redirect", lambda u: DELETED)
    counts = {c["url"]: c for c in retired_urls.count_citations(
        [_obs("gemini", [REDIRECT])], DATE, RETIRED, resolve=True)}
    assert counts[DELETED]["count"] == 1
    assert counts[DELETED]["unresolved"] == 0


def test_a_redirect_that_cannot_be_resolved_is_reported(monkeypatch):
    monkeypatch.setattr(retired_urls, "resolve_redirect", lambda u: None)
    counts = retired_urls.count_citations(
        [_obs("gemini", [REDIRECT])], DATE, RETIRED, resolve=True)
    assert counts[0]["unresolved"] == 1


def test_the_event_detail_warns_about_unresolved_redirects():
    rows = retired_urls.event_rows(DATE, [_obs("gemini", [REDIRECT])], RETIRED)
    assert any("未解決のリダイレクト1件" in r["detail"] for r in rows)


def test_resolution_never_runs_when_not_asked(monkeypatch):
    """テストと手元確認でネットワークに出ないこと。"""
    def boom(url):
        raise AssertionError("resolve=False なのに解決しようとした")

    monkeypatch.setattr(retired_urls, "resolve_redirect", boom)
    retired_urls.count_citations([_obs("gemini", [REDIRECT])], DATE, RETIRED)


# --- status: dead(サイトごと停止・自社では直せない)-------------------------
DEAD = "https://www.fsdg.jp/zoho/success/success-411/"
RETIRED_DEAD = RETIRED + [
    {"url": DEAD, "label": "第三者メディアの旧事業事例", "retired_on": "2026-09-01",
     "action_id": "—", "status": "dead"},
]


def test_a_dead_url_counts_as_stale():
    """自社が消したかどうかに関わらず、旧事業が引用されていれば問題。"""
    line = retired_urls.summary_line(DATE, [_obs("claude", [DEAD])], RETIRED_DEAD)
    assert "第三者メディアの旧事業事例 1回" in line


def test_a_dead_url_is_annotated_as_not_editable():
    rows = retired_urls.event_rows(DATE, [_obs("claude", [DEAD])], RETIRED_DEAD)
    detail = next(r["detail"] for r in rows if "第三者メディア" in r["detail"])
    assert "自社では編集不可" in detail


def test_replaced_is_still_excluded_from_stale():
    assert "replaced" not in retired_urls.STALE_STATUSES
    assert set(retired_urls.STALE_STATUSES) == {"deleted", "dead"}


# --- 月次も数える(要判断1の回答)---------------------------------------------
def test_the_daily_scope_only_looks_at_e1():
    """日次で会社そのものを聞くのは E-1 だけ。既定はここに絞る。"""
    assert retired_urls.DAILY_PROMPT_IDS == ("E-1",)
    rows = [_obs("claude", [DELETED], prompt_id="M-4")]
    counts = {c["url"]: c for c in retired_urls.count_citations(rows, DATE, RETIRED)}
    assert counts[DELETED]["count"] == 0


def test_the_monthly_scope_counts_every_prompt():
    """月次は12本すべてが自社を聞く面なので絞らない。

    fsdg.jp は日次 E-1 では一度も引用されず、月次 M-4 で初めて出た。
    日次だけを見ていると永久に0件と表示され「引用が止まった」と読めてしまう。
    """
    rows = [_obs("claude", [DELETED], prompt_id="M-4")]
    counts = {c["url"]: c for c in retired_urls.count_citations(
        rows, DATE, RETIRED, prompt_ids=retired_urls.ALL_PROMPTS)}
    assert counts[DELETED]["count"] == 1
    assert counts[DELETED]["prompts"] == ["M-4"]


def test_the_place_records_which_prompt_cited_it():
    rows = retired_urls.event_rows(
        DATE, [_obs("claude", [DELETED], prompt_id="M-4")], RETIRED,
        prompt_ids=retired_urls.ALL_PROMPTS, scope=retired_urls.SCOPE_MONTHLY)
    cited = next(r for r in rows if "1回" in r["detail"])
    assert cited["place"].startswith("月次 M-4")


def test_the_place_records_the_scope_when_nothing_was_cited():
    """0件のとき、どこを見て0だったのかが分からないと0の意味が変わる。"""
    rows = retired_urls.event_rows(DATE, [], RETIRED)
    assert all(r["place"].startswith("日次 E-1") for r in rows)


def test_daily_and_monthly_rows_do_not_collide_in_lk_events():
    """同じ日・同じURLでも、日次由来と月次由来は別の行として残る。"""
    obs = [_obs("claude", [DELETED], prompt_id="E-1"),
           _obs("gemini", [DELETED], prompt_id="M-4")]
    daily = retired_urls.event_rows(DATE, obs, RETIRED)
    monthly = retired_urls.event_rows(
        DATE, obs, RETIRED, prompt_ids=retired_urls.ALL_PROMPTS,
        scope=retired_urls.SCOPE_MONTHLY)
    # lk_events の鍵は date + event_type + place + detail
    keys = {(r["date"], r["event_type"], r["place"], r["detail"])
            for r in daily + monthly}
    assert len(keys) == len(daily) + len(monthly)


def test_the_summary_names_the_prompt_that_cited_it():
    line = retired_urls.summary_line(
        DATE, [_obs("claude", [DELETED], prompt_id="M-4")], RETIRED,
        prompt_ids=retired_urls.ALL_PROMPTS)
    assert "(M-4)" in line


# --- ジョブサマリ ------------------------------------------------------------
def test_the_summary_reports_zero_clearly():
    line = retired_urls.summary_line(DATE, [_obs("claude", [])], RETIRED)
    assert "0回" in line


def test_the_summary_names_the_urls_still_cited():
    line = retired_urls.summary_line(DATE, [_obs("claude", [DELETED])], RETIRED)
    assert "削除したリリース 1回" in line


def test_a_replaced_url_alone_does_not_count_as_still_cited():
    """存置URLの引用は「古い参照が残っている」ではない。"""
    line = retired_urls.summary_line(DATE, [_obs("gemini", [REPLACED])], RETIRED)
    assert "0回" in line and "存置URLの引用は1回" in line
