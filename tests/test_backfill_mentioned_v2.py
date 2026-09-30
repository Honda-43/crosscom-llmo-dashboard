"""mentioned_v2 の遡及再計算(backfill_mentioned_v2.py)のテスト(2026-10-01).

固定したいのは4つ:
1. 9/15 以降の行だけを、保存されている answer_text から数え直す(欠測・9/15 より前は空)
2. 旧 mentioned は変えず、違った行と該当箇所(前後20字)を報告に出す
3. セルで切れた answer_text は raw_file の全文で数える
4. 本文中の cross-com.jp の URL だけで当たった行は、報告で別に数える
"""
import json

import backfill_mentioned_v2 as bf


def _row(date="2026-09-20", answer="", mentioned="0", error="", raw_file="", eid="E01"):
    return {"date": date, "experiment_id": eid, "model": "gemini", "answer_text": answer,
            "mentioned": mentioned, "error": error, "raw_file": raw_file}


def test_only_rows_from_0915_without_errors_are_recounted():
    assert bf.recount(_row(answer="CrossCom")) == "1"
    assert bf.recount(_row(answer="Salesforce")) == "0"
    assert bf.recount(_row(answer="CrossCom", error="429")) == ""
    assert bf.recount(_row(date="2026-09-14", answer="CrossCom")) == ""


def test_changed_rows_are_reported_with_20_chars_around_the_hit():
    rows = [_row(answer="あ" * 30 + "Cross-Com社の解説" + "い" * 30, eid="E01"),
            _row(answer="合同会社クロスコムの記事", mentioned="1", eid="E02"),
            _row(answer="Salesforce", eid="E03")]
    items = bf.plan(rows)
    assert [(x["row"], x["mentioned_v2"], x["changed"]) for x in items] == [
        (2, "1", True), (3, "1", False), (4, "0", False)]
    assert items[0]["snippets"] == ["…" + "あ" * 20 + "Cross-Com社の解説" + "い" * 16 + "…"]
    text = bf.report(items)
    assert "mentioned と mentioned_v2 が違った行: 1行" in text
    assert "旧0→新1 1行" in text and "| 2 | 2026-09-20 | E01 | gemini | 0 | 1 |" in text


def test_a_truncated_cell_is_recounted_from_the_raw_file(tmp_path):
    raw = tmp_path / "data" / "E01_gemini.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"answer": "長い本文 … 最後に クロス・コム"}, ensure_ascii=False),
                   encoding="utf-8")
    row = _row(answer="長い本文 " + bf.TRUNCATED_MARK, raw_file="data/E01_gemini.json")
    assert bf.recount(row, root=tmp_path) == "1"
    assert bf.recount(dict(row, answer_text="長い本文"), root=tmp_path) == "0"


def test_hits_only_in_a_self_url_are_counted_separately():
    items = bf.plan([_row(answer="出典: https://cross-com.jp/agentforce-rag/ を参照")])
    assert items[0]["changed"]
    assert "cross-com.jp の URL だけの行: 1行" in bf.report(items)
