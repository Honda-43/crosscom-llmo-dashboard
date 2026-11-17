"""第3観測層の月次報告(src/marketing_by_what.py・2026-11-17 確定).

固定したいこと(判定の出力は作り物の観測だけで確かめる):
1. 報告の順番:(1) Agentforce導入支援・活用定着支援 → ChatGPT(B-2・手作業) → (2) Agentic CRM設計支援 →
   (3) 外部サイトの言及による推薦 → (4) BOFU → (5) 層ごとの上位5社。件数で出し、率は出さない
2. What は config/marketing_what.yaml(57本すべて・2026-10-10 の重複調査の表)。prompts_marketing.csv は変えない
3. 何番目 = クロスコムの初出より前に初出する会社の数 + 1(marketing.mention_rank と同じ決め方)
4. 上位5社は「その会社が出た回答の本数」。5位と同数の会社は全部出す
5. 欠測の行は数えない。同じ月に2回あれば後の日
6. B-2 の ChatGPT は手入力の CSV から読み、無い月は「未入力」
"""
import collections
import csv
import re

import marketing_by_what as mbw
import settings

COMPANIES = {"A社": re.compile("株式会社a"), "B社": re.compile("b株式会社"), "C社": re.compile("c合同")}
PROMPTS = [
    {"id": "PM-L0-01", "layer": "MOFU_L0", "prompt": "おすすめのAgentforce導入支援会社を教えてください。"},
    {"id": "PM-L0-02", "layer": "MOFU_L0", "prompt": "おすすめのAgentforce活用定着支援会社を教えてください。"},
    {"id": "PM-L1-02", "layer": "MOFU_L1", "prompt": "住宅業界におすすめのAgentic CRM設計支援会社を教えてください。"},
    {"id": "PM-L2-03", "layer": "MOFU_L2", "prompt": "中小企業におすすめのSalesforce導入支援会社を教えてください。"},
    {"id": "PM-BS-01", "layer": "BOFU_single", "prompt": "合同会社クロスコムのAgentforce導入支援の評判を教えてください。"},
]
WHAT = {"PM-L0-01": "Agentforce導入支援", "PM-L0-02": "Agentforce活用定着支援", "PM-L1-02": "Agentic CRM設計支援",
        "PM-L2-03": "Salesforce導入支援", "PM-BS-01": "Agentforce導入支援"}


def _row(pid, date, answer, mentioned, cited, domains=(), error=""):
    layer = next(p["layer"] for p in PROMPTS if p["id"] == pid)
    return {"prompt_id": pid, "layer": layer, "date": date, "model": "gemini", "answer_text": answer,
            "mentioned": str(mentioned), "cited_domain": str(cited), "cited_domains": str(list(domains)), "error": error}


ROWS = [
    _row("PM-L0-01", "2026-12-01", "株式会社A、合同会社クロスコム", 1, 1, ["cross-com.jp", "a.co.jp"]),
    _row("PM-L0-02", "2026-12-01", "", "", "", error="503 UNAVAILABLE"),                       # 欠測は数えない
    _row("PM-L1-02", "2026-12-02", "B株式会社", 0, 0),
    _row("PM-L1-02", "2026-12-05", "合同会社クロスコム、B株式会社、株式会社A", 1, 0, ["b.co.jp", "a.co.jp"]),  # 後の日
    _row("PM-L2-03", "2026-12-03", "株式会社A、C合同会社、株式会社Zeta", 0, 0),
    _row("PM-BS-01", "2026-12-03", "合同会社クロスコム", 1, 1, ["cross-com.jp"]),
]


def _report(b2=None):
    obs = mbw.observations(ROWS, PROMPTS, WHAT, COMPANIES)
    return obs, mbw.build(obs, b2 or {})


def test_rank_counts_companies_that_appear_before_us():
    answer = "1. 株式会社A 2. B株式会社 3. 合同会社クロスコム 4. C合同会社"
    pos = mbw.company_positions(answer, COMPANIES)
    assert set(pos) == {"A社", "B社", "C社"} and mbw.rank_of(answer, pos) == 3
    assert mbw.rank_of("株式会社Aだけ", {"A社": 0}) is None


def test_top_includes_ties_at_the_edge():
    c = collections.Counter({"a": 5, "b": 4, "c": 3, "d": 2, "e": 1, "f": 1, "g": 0})
    assert [n for n, _ in mbw.top_companies(c)] == ["a", "b", "c", "d", "e", "f"]
    assert mbw.top_companies(collections.Counter({"a": 1})) == [("a", 1)]


def test_sections_follow_what_and_skip_misses():
    obs, rep = _report()
    assert [o["id"] for o in obs] == ["PM-BS-01", "PM-L0-01", "PM-L1-02", "PM-L2-03"]
    assert [(o["id"], o["mentioned"], o["rank"]) for o in rep["section1"]] == [("PM-L0-01", True, 2)]
    assert [(o["id"], o["rank"], o["date"]) for o in rep["section2"]] == [("PM-L1-02", 1, "2026-12-05")]
    assert {k: len(v) for k, v in rep["bofu"].items()} == {"BOFU_single": 1, "BOFU_compare": 0}


def test_external_recommendation_counts_named_answers_without_our_citation():
    _, rep = _report()
    assert [o["id"] for o in rep["named_mofu"]] == ["PM-L0-01", "PM-L1-02"]
    assert [o["id"] for o in rep["named_without_self_citation"]] == ["PM-L1-02"]
    assert rep["external_domains"] == collections.Counter({"a.co.jp": 2, "b.co.jp": 1})


def test_render_order_counts_not_rates_and_b2():
    b2 = {"②導入支援のおすすめ": {"mentioned": "出た", "rank": "3", "cited_crosscom": "なし"}}
    text = mbw.render("2026-12", _report(b2)[1])
    heads = ["## (1) Agentforce導入支援・Agentforce活用定着支援", "### ChatGPT（B-2・手作業）", "## (2) Agentic CRM設計支援",
             "## (3) 外部サイトの言及による推薦", "## (4) BOFU", "## (5) 層ごとに多く挙げられた会社"]
    assert [text.index(h) for h in heads] == sorted(text.index(h) for h in heads)
    assert text.count("※ 2か月続けて変わったときだけ変化と読む") == 2
    assert "%" not in text and "率は出さない" in text
    assert "| Agentforce導入支援 | 1 | 1 |" in text and "| Agentforce活用定着支援 | 0 | 0 |" in text
    assert "| ②導入支援のおすすめ | 出た | 3 | なし |" in text and "| P2-1 定着 | 未入力 | 未入力 | 未入力 |" in text
    assert "| 2 | 1 |" in text and "- a.co.jp（2）" in text
    assert "| MOFU_L2 | 1 | C社 1・A社 1 |" in text or "| MOFU_L2 | 1 | A社 1・C社 1 |" in text
    assert "- 株式会社zeta（1本）" in text


def test_b2_csv_is_read_by_month(tmp_path):
    path = tmp_path / "b2.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(mbw.B2_HEADERS)
        w.writerow(["2026-11", "P2-1 定着", "出ない", "", "なし", ""])
        w.writerow(["2026-12", "P2-1 定着", "出た", "2", "あり", ""])
    assert mbw.load_b2("2026-12", path)["P2-1 定着"]["rank"] == "2"
    assert mbw.load_b2("2027-01", path) == {} and mbw.load_b2("2026-12", tmp_path / "none.csv") == {}


def test_the_real_files_have_the_agreed_shape():
    prompts = settings.load_marketing_prompts()
    what = mbw.load_what()
    assert set(what) == {p["id"] for p in prompts}, "57本すべてに What が1つ"
    mofu = [p for p in prompts if mbw.is_target(p)]
    assert len(mofu) == 37
    counts = collections.Counter(what[p["id"]] for p in mofu)
    assert (counts["Agentforce導入支援"], counts["Agentforce活用定着支援"], counts["Agentic CRM設計支援"],
            counts["Salesforce導入支援"]) == (10, 1, 10, 10)
    for p in prompts:                                           # What の語は質問文に書かれている
        assert what[p["id"]].replace("支援", "") in p["prompt"], p["id"]
    with open(mbw.B2_FILE, encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == mbw.B2_HEADERS
    companies = mbw.load_companies()
    assert "メンバーズ" in companies and not any(rx.search("合同会社クロスコム") for rx in companies.values())
