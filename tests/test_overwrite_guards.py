"""出力の上書き防止(2026-10-01).

既にあるものを置き換えるときは止まる。--force を付けた場合だけ置き換え、
理由を日誌に自動で1行記録する。
1. 同じ日の観測の再実行(成功した raw と行を、欠測や取り直しで置き換えない)
2. 割付(allocate_47.py。実験期間中は --force でも止まる)
3. ドリフト検知の処置後の基準(drift_check.py --post-baseline)
4. 層ファイルの採用固定は tests/test_experiment_2x2.py
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

import collect_llm
import force_log
import run_experiment
import sheets_writer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
import allocate_47  # noqa: E402
import drift_check  # noqa: E402
import pool  # noqa: E402


@pytest.fixture
def diary(tmp_path, monkeypatch):
    path = tmp_path / "experiment47_diary.md"
    path.write_text("# 日誌\n\n既存の記録\n", encoding="utf-8")
    monkeypatch.setattr(force_log, "DIARY_FILE", path)
    return path


# --------------------------------------------------------------------------
# 1. 同じ日の観測の再実行
# --------------------------------------------------------------------------
PROMPTS = [{"id": "E01", "text": "質問1"}, {"id": "E02", "text": "質問2"}]


def _write_raw(out_dir, pid, model, answer=None, error=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {"date": "2026-10-01", "prompt_id": pid, "model": model, "answer": answer,
           "error": error, "cited_urls": [], "timestamp": "2026-10-01T00:00:00Z"}
    (out_dir / f"{pid}_{model}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


@pytest.fixture
def api(monkeypatch):
    """API 呼び出しの代わり。呼ばれた観測を数え、指定どおり成功か欠測を返す。"""
    calls = []
    outcome = {"error": "429 RESOURCE_EXHAUSTED"}

    def fake_attempt(record, question, **kw):
        calls.append(f"{record['prompt_id']}/{record['model']}")
        if outcome.get("error"):
            record.update(error=outcome["error"], answer=None)
            return False
        record.update(error=None, answer=outcome["answer"])
        return True

    monkeypatch.setattr(collect_llm, "_attempt", fake_attempt)
    monkeypatch.setattr(collect_llm, "enabled_models", lambda: ["gemini"])
    monkeypatch.setattr(collect_llm, "_model_runnable", lambda m: True)
    return calls, outcome


def test_a_rerun_does_not_replace_a_successful_observation_with_a_miss(tmp_path, api):
    calls, _ = api                      # 再実行では 429 しか返らない
    out = tmp_path / "2026-10-01"
    _write_raw(out, "E01", "gemini", answer="先に取れていた回答")
    _write_raw(out, "E02", "gemini", error="503 UNAVAILABLE")

    records = collect_llm.collect("2026-10-01", prompts=PROMPTS, out_dir=out, sweep=False)

    assert calls == ["E02/gemini"], "成功した観測は投げない(枠も使わない)"
    kept = json.loads((out / "E01_gemini.json").read_text(encoding="utf-8"))
    assert kept["answer"] == "先に取れていた回答" and not kept["error"]
    by_id = {r["prompt_id"]: r for r in records}
    assert by_id["E01"]["reused"] is True
    # シートに書き直すのは欠測だった E02 だけ
    assert [r["prompt_id"] for r in collect_llm.fresh(records)] == ["E02"]


def test_a_failed_observation_is_replaced(tmp_path, api):
    calls, outcome = api
    outcome.update(error=None, answer="取り直した回答")
    out = tmp_path / "2026-10-01"
    _write_raw(out, "E02", "gemini", error="503 UNAVAILABLE")

    collect_llm.collect("2026-10-01", prompts=PROMPTS[1:], out_dir=out, sweep=False)

    assert calls == ["E02/gemini"]
    assert json.loads((out / "E02_gemini.json").read_text(encoding="utf-8"))["answer"] == "取り直した回答"


def test_save_never_overwrites_success_with_a_miss(tmp_path):
    """枠の都合で投げなかった記録(quota_skipped)なども、成功した raw を消さない。"""
    out = tmp_path / "2026-10-01"
    _write_raw(out, "E01", "gemini", answer="先に取れていた回答")
    miss = {"date": "2026-10-01", "prompt_id": "E01", "model": "gemini", "answer": None,
            "error": "quota_skipped"}

    collect_llm._save(miss, out)

    assert json.loads((out / "E01_gemini.json").read_text(encoding="utf-8"))["answer"] == "先に取れていた回答"
    assert miss["kept_existing"] is True
    assert collect_llm.fresh([miss]) == []


def test_force_replaces_a_successful_observation(tmp_path, api):
    calls, outcome = api
    outcome.update(error=None, answer="取り直した回答")
    out = tmp_path / "2026-10-01"
    _write_raw(out, "E01", "gemini", answer="先に取れていた回答")

    collect_llm.collect("2026-10-01", prompts=PROMPTS[:1], out_dir=out, sweep=False, force=True)

    assert calls == ["E01/gemini"]
    assert json.loads((out / "E01_gemini.json").read_text(encoding="utf-8"))["answer"] == "取り直した回答"


def test_the_experiment_plan_drops_what_was_already_observed(tmp_path):
    out = tmp_path / "2026-10-01"
    _write_raw(out, "E01", "gemini", answer="回答")
    _write_raw(out, "E02", "gemini", error="429")
    plan = {"gemini": [{"id": "E01"}, {"id": "E02"}], "claude": [{"id": "E01"}]}

    rest, already = run_experiment.split_observed(plan, out)

    assert rest == {"gemini": [{"id": "E02"}], "claude": [{"id": "E01"}]}
    assert [(r["prompt_id"], r["model"]) for r in already] == [("E01", "gemini")]
    assert run_experiment.split_observed(plan, out, force=True) == (plan, [])


def test_the_sheet_row_of_a_successful_observation_is_left_alone(monkeypatch, tmp_path):
    """llm_experiment に書くのは fresh() だけ。成功した行を欠測で上書きしない。"""
    from test_carry_forward import FakeSpreadsheet, FakeWorksheet

    h = sheets_writer.HEADERS_EXPERIMENT
    good = {"date": "2026-10-01", "experiment_id": "E01", "model": "gemini",
            "cited_article": "1", "answer_text": "先に取れていた回答"}

    class Ws(FakeWorksheet):
        def get(self, rng):
            return [r[:3] for r in self.values]

    ws = Ws([h, [good.get(c, "") for c in h]])
    written = []

    class Ss(FakeSpreadsheet):
        def values_batch_update(self, body):
            for d in body["data"]:
                written.append(d)
                ws.update(d["values"], d["range"].split("!")[1])

    monkeypatch.setattr(sheets_writer, "_open_spreadsheet", lambda: Ss({"llm_experiment": ws}))
    miss = {"date": "2026-10-01", "experiment_id": "E01", "prompt_id": "E01", "model": "gemini",
            "error": "429", "kept_existing": True}
    sheets_writer.write_experiment(collect_llm.fresh([miss]))

    assert written == []
    assert ws.values[1][h.index("answer_text")] == "先に取れていた回答"


def test_force_needs_a_reason():
    with pytest.raises(force_log.ForceRequired):
        force_log.require_reason(True, "  ", "その日の成功した観測")
    assert force_log.require_reason(False, None, "x") == ""


def test_force_log_appends_one_line(diary):
    line = force_log.record("run_experiment.py", "2026-10-01 の成功した観測 3件", "API の不具合で回答が壊れていた",
                            now=dt.datetime(2026, 10, 1, 12, 0, tzinfo=force_log.JST))
    text = diary.read_text(encoding="utf-8")
    assert text.startswith("# 日誌\n\n既存の記録\n")
    assert text.rstrip().endswith(line)
    assert "2026-10-01 12:00 JST" in line and "理由：API の不具合で回答が壊れていた" in line


# --------------------------------------------------------------------------
# 2. 割付(allocate_47.py)
# --------------------------------------------------------------------------
@pytest.fixture
def allocation(tmp_path):
    csv_path = tmp_path / "allocation_v1.csv"
    md_path = tmp_path / "experiment47_allocation_v1_20260928.md"
    csv_path.write_text("id,url,group,seed\nE01,https://x/,①対照,20270135\n", encoding="utf-8")
    md_path.write_text("# 割付\n", encoding="utf-8")
    return [str(md_path), str(csv_path)]


def test_an_existing_allocation_stops_write(allocation):
    stop = allocate_47.overwrite_guard(allocation, False, "", dt.date(2026, 10, 1))
    assert stop and "書き直さない" in stop


@pytest.mark.parametrize("today", [dt.date(2026, 10, 1), dt.date(2026, 12, 31)])
def test_force_cannot_replace_the_allocation_during_the_experiment(allocation, today):
    stop = allocate_47.overwrite_guard(allocation, True, "シードを変えたい", today)
    assert stop and "実験期間中" in stop


def test_after_the_experiment_force_needs_a_reason(allocation):
    assert "--reason" in allocate_47.overwrite_guard(allocation, True, "", dt.date(2027, 1, 1))
    assert allocate_47.overwrite_guard(allocation, True, "次の実験", dt.date(2027, 1, 1)) is None


def test_a_first_write_is_allowed(tmp_path):
    assert allocate_47.overwrite_guard([str(tmp_path / "none.csv")], False, "", dt.date(2026, 9, 28)) is None


def test_main_stops_before_doing_anything(allocation, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["allocate_47.py", "--write",
                                      "--out", allocation[0], "--out-csv", allocation[1]])
    monkeypatch.setattr(allocate_47, "load_articles",
                        lambda: pytest.fail("止まる前に割付の計算に入った"))
    assert allocate_47.main() == 3
    assert "20270135" in Path(allocation[1]).read_text(encoding="utf-8")


def test_the_old_seed_is_read_for_the_diary(allocation):
    assert allocate_47.old_seed(allocation[1]) == "20270135"


def test_the_experiment_end_matches_the_freeze_config():
    from settings import EXPERIMENT_FREEZE_FILE, load_yaml
    assert pool.EXPERIMENT_END == str(load_yaml(EXPERIMENT_FREEZE_FILE)["experiment_end"])


# --------------------------------------------------------------------------
# 3. ドリフト検知の処置後の基準
# --------------------------------------------------------------------------
@pytest.fixture
def post(tmp_path, monkeypatch):
    d = tmp_path / "post_treatment"
    (d / "snapshots").mkdir(parents=True)
    (d / "html").mkdir()
    monkeypatch.setattr(drift_check, "POST_DIR", str(d))
    monkeypatch.setattr(drift_check, "POST_MANIFEST", str(d / "manifest.json"))
    monkeypatch.setattr(drift_check, "POST_SNAP_DIR", str(d / "snapshots"))
    monkeypatch.setattr(drift_check, "POST_HTML_DIR", str(d / "html"))
    return d


def _existing_post(d):
    (d / "manifest.json").write_text(json.dumps(
        {"agentforce-rag": {"url": "u", "sha256": "abc", "bytes": 1, "checked": "2026-09-30"}}),
        encoding="utf-8")
    (d / "snapshots" / "agentforce-rag.txt").write_text("9/30 の本文", encoding="utf-8")


def test_the_post_baseline_is_not_retaken(post, monkeypatch):
    _existing_post(post)
    monkeypatch.setattr(sys, "argv", ["drift_check.py", "--post-baseline"])
    monkeypatch.setattr(drift_check, "targets", lambda: pytest.fail("取り直しに入った"))

    assert drift_check.main() == 3
    assert (post / "snapshots" / "agentforce-rag.txt").read_text(encoding="utf-8") == "9/30 の本文"
    assert "abc" in (post / "manifest.json").read_text(encoding="utf-8")


def test_force_without_a_reason_also_stops(post):
    _existing_post(post)
    assert "--reason" in drift_check.post_baseline_guard(True, "")


def test_force_with_a_reason_retakes_and_records(post, diary, monkeypatch):
    _existing_post(post)
    monkeypatch.setattr(sys, "argv", ["drift_check.py", "--post-baseline", "--force",
                                      "--reason", "テーマ更新で全記事の HTML が変わった", "--sleep", "0"])
    monkeypatch.setattr(drift_check, "targets", lambda: [("agentforce-rag", "u")])
    monkeypatch.setattr(drift_check, "fetch", lambda url: "<article>新しい本文</article>")

    assert drift_check.main() == 0
    assert json.loads((post / "manifest.json").read_text(encoding="utf-8"))["agentforce-rag"]["sha256"] != "abc"
    line = diary.read_text(encoding="utf-8").splitlines()[-1]
    assert "drift_check.py" in line and "取得日 2026-09-30" in line
    assert "テーマ更新で全記事の HTML が変わった" in line


def test_the_first_post_baseline_is_allowed(post):
    assert drift_check.post_baseline_guard(False, "") is None
