"""シートへの書き戻しと、シートの 403 の通知のテスト(2026-10-07).

1. raw はあるのにシートに無い観測だけを書く。既にある行は書き直さない・消さない・重複させない
2. 計画したのに raw も無い観測は、理由つきの欠測として残す
3. Sheets が 403 を返したら Slack に「シートの共有を確認」と1回だけ知らせる
4. 観測は raw に先に保存してからシートに書く(シートが落ちても raw は残る)
"""
import json

import pytest

import backfill_experiment_sheet as bf
import collect_llm
import settings
import sheets_writer

DATE = "2026-10-05"


def _raw(folder, pid, model="gemini", **extra):
    folder.mkdir(parents=True, exist_ok=True)
    rec = {"date": DATE, "prompt_id": pid, "model": model, "model_name": "m", "question": "Q",
           "answer": "答え", "cited_urls": [], "error": None, "attempts": 1, **extra}
    (folder / f"{pid}_{model}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_only_observations_missing_from_the_sheet_are_written(tmp_path):
    _raw(tmp_path / DATE, "E28")
    _raw(tmp_path / DATE, "E29")
    existing = {(DATE, "E28", "gemini")}
    got = bf.missing_from_sheet(DATE, existing, raw_dir=tmp_path, resolver=lambda u: None)
    assert [r["prompt_id"] for r in got] == ["E29"], "既にある行は書かない"
    assert got[0]["cited_article"] == 0 and got[0]["experiment_id"] == "E29", "判定列を付ける"
    assert got[0]["raw_file"] == f"data/raw/experiment/{DATE}/E29_gemini.json"


def test_the_upsert_never_duplicates_or_deletes_existing_rows():
    head = sheets_writer.HEADERS_EXPERIMENT
    existing = [head, [DATE, "E28", "gemini"] + [""] * (len(head) - 3),
                ["2026-10-04", "E01", "gemini"] + [""] * (len(head) - 3)]
    rows = [{"date": DATE, "experiment_id": "E28", "model": "gemini"},
            {"date": DATE, "experiment_id": "E29", "model": "gemini"}]
    writes = sheets_writer._plan_upsert(existing, head, sheets_writer.KEYS_EXPERIMENT, rows)
    assert sorted(w["row"] for w in writes) == [2, 4], "同じ鍵は同じ行(2行目)、新しい観測は末尾(4行目)"
    assert all(w["row"] != 3 for w in writes), "ほかの行(10/04)には触れない"


def test_planned_observations_without_raw_are_recorded_with_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_EXPERIMENT_CURSOR", {})
    _raw(tmp_path / DATE, "E28")
    gone = bf.unobserved(DATE, "job_timeout: 止まった", raw_dir=tmp_path)
    assert gone and all(r["error"] == "job_timeout: 止まった" and r["attempts"] == 0 for r in gone)
    assert ("E28", "gemini") not in {(r["prompt_id"], r["model"]) for r in gone}, "raw がある観測は欠測にしない"
    assert all(r["cited_article"] == "" for r in gone), "欠測は0(引用なし)ではなく空"


def test_a_403_from_sheets_posts_one_slack_alert(monkeypatch):
    import notify_slack
    posted = []
    monkeypatch.setattr(notify_slack, "_post", lambda text, hook: posted.append(text))
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setattr(sheets_writer, "_SHEET_403_NOTIFIED", [False])
    from gspread.exceptions import APIError

    class Resp:
        status_code = 403
        text = '{"error": {"code": 403, "message": "The caller does not have permission"}}'

        def json(self):
            return {"error": {"code": 403, "message": "The caller does not have permission", "status": "PERMISSION_DENIED"}}

    client_cls = sheets_writer._retrying_http_client()
    monkeypatch.setattr(client_cls.__mro__[1], "request", lambda self, *a, **k: (_ for _ in ()).throw(APIError(Resp())))
    client = client_cls.__new__(client_cls)
    for _ in range(2):
        with pytest.raises(APIError):
            client.request("get", "https://sheets.googleapis.com/x")
    assert len(posted) == 1 and "シートの共有を確認" in posted[0], "403 は1回だけ知らせる"


def test_observations_are_saved_to_raw_before_any_sheet_write(monkeypatch, tmp_path):
    """collect は1件ごとに raw を書く。シートへの書き込みは呼び出し側があとで行う(シートが落ちても raw は残る)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setitem(collect_llm._QUERY_FUNCS, "gemini", lambda text, model: ("答え", []))
    monkeypatch.setattr(sheets_writer, "_open_spreadsheet", lambda: pytest.fail("collect はシートに触れない"))
    collect_llm.collect(DATE, prompts=[{"id": "E28", "text": "Q"}], out_dir=tmp_path, models=["gemini"])
    assert (tmp_path / "E28_gemini.json").exists()
