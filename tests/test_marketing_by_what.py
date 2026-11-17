"""第3観測層 MOFU を支援の種類で分けた月次の表(src/marketing_by_what.py・2026-11-17).

固定したいこと(作り物の観測だけを使う):
1. 支援の種類は質問文の語で決める(Agentforce導入支援／Agentforce活用定着支援／Agentic CRM設計支援／その他)
2. 対象は会社名を含まない MOFU(L0・L1・L2)だけ。BOFU とクロスコムの名前を含む質問は入れない
3. 何番目 = クロスコムの初出より前に初出する会社の数 + 1(marketing.mention_rank と同じ決め方)
4. 上位5社は「その会社が出た回答の本数」。5位と同数の会社は全部出す
5. 欠測の行は数えない。同じ月に2回あれば後の日
6. 本物の57本は全部どれかの種類に入る
"""
import collections
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


def _row(pid, date, answer, mentioned, cited, error=""):
    layer = next(p["layer"] for p in PROMPTS if p["id"] == pid)
    return {"prompt_id": pid, "layer": layer, "date": date, "model": "gemini", "answer_text": answer,
            "mentioned": str(mentioned), "cited_domain": str(cited), "error": error}


def test_what_comes_from_the_question_text():
    assert [mbw.what_of(p["prompt"]) for p in PROMPTS[:4]] == [
        "Agentforce導入支援", "Agentforce活用定着支援", "Agentic CRM設計支援", "その他"]
    assert mbw.what_of("おすすめのAgentforce設計レビュー会社を教えてください。") == "その他"


def test_only_mofu_questions_without_our_name():
    assert [p["id"] for p in PROMPTS if mbw.is_target(p)] == ["PM-L0-01", "PM-L0-02", "PM-L1-02", "PM-L2-03"]
    assert not mbw.is_target({"layer": "MOFU_L1", "prompt": "クロスコムと比べておすすめの会社は？"})


def test_rank_counts_companies_that_appear_before_us():
    answer = "1. 株式会社A 2. B株式会社 3. 合同会社クロスコム 4. C合同会社"
    pos = mbw.company_positions(answer, COMPANIES)
    assert set(pos) == {"A社", "B社", "C社"}
    assert mbw.rank_of(answer, pos) == 3
    assert mbw.rank_of("合同会社クロスコム、株式会社A", mbw.company_positions("合同会社クロスコム、株式会社A", COMPANIES)) == 1
    assert mbw.rank_of("株式会社Aだけ", {"A社": 0}) is None


def test_top_includes_ties_at_the_edge():
    c = collections.Counter({"a": 5, "b": 4, "c": 3, "d": 2, "e": 1, "f": 1, "g": 0})
    assert [n for n, _ in mbw.top_companies(c)] == ["a", "b", "c", "d", "e", "f", "g"][:6]
    assert mbw.top_companies(collections.Counter({"a": 1})) == [("a", 1)]


def test_summary_counts_by_what_and_skips_misses():
    rows = [
        _row("PM-L0-01", "2026-12-01", "株式会社A、合同会社クロスコム", 1, 1),
        _row("PM-L0-02", "2026-12-01", "", "", "", error="503 UNAVAILABLE"),       # 欠測は数えない
        _row("PM-L1-02", "2026-12-02", "B株式会社", 0, 0),
        _row("PM-L1-02", "2026-12-05", "合同会社クロスコム、B株式会社、株式会社A", 1, 0),  # 後の日を使う
        _row("PM-L2-03", "2026-12-03", "株式会社A、C合同会社", 0, 0),
        _row("PM-BS-01", "2026-12-03", "合同会社クロスコム", 1, 1),                  # BOFU は入れない
    ]
    cells = mbw.summarize(rows, PROMPTS, COMPANIES)["cells"]
    got = {w: (c["n"], c["mentioned"], c["cited"]) for w, c in cells.items()}
    assert got == {"Agentforce導入支援": (1, 1, 1), "Agentforce活用定着支援": (0, 0, 0),
                   "Agentic CRM設計支援": (1, 1, 0), "その他": (1, 0, 0)}
    assert [(h["id"], h["rank"]) for h in cells["Agentforce導入支援"]["hits"]] == [("PM-L0-01", 2)]
    assert [(h["id"], h["rank"], h["date"]) for h in cells["Agentic CRM設計支援"]["hits"]] == [("PM-L1-02", 1, "2026-12-05")]
    assert cells["その他"]["companies"] == collections.Counter({"A社": 1, "C社": 1})
    out = mbw.render("2026-12", mbw.summarize(rows, PROMPTS, COMPANIES))
    assert "| Agentforce導入支援 | PM-L0-01 |" in out and "| 計 | 3 | 2 | 1 |" in out
    assert "- その他：PM-L2-03" in out


def test_unknown_candidates_skip_listed_names():
    got = mbw.unknown_candidates("株式会社A、株式会社Zeta、合同会社クロスコム", COMPANIES)
    assert got == ["株式会社zeta"]


def test_every_real_mofu_question_gets_a_what_and_the_company_list_loads():
    prompts = [p for p in settings.load_marketing_prompts() if mbw.is_target(p)]
    assert len(prompts) == 37
    counts = collections.Counter(mbw.what_of(p["prompt"]) for p in prompts)
    assert counts == {"Agentforce導入支援": 10, "Agentforce活用定着支援": 1, "Agentic CRM設計支援": 10, "その他": 16}
    companies = mbw.load_companies()
    assert "メンバーズ" in companies and not any(rx.search("合同会社クロスコム") for rx in companies.values())
