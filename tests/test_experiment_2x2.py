"""experiment_2x2 の安全策のテスト(2026-09-22).

固定したいのは4つ:
1. allocate_47.py は既定でドライラン。--write のときだけ書き、9/28 より前の --write は止まる
   (割付表は seo-agent の apply_gate が読む。本番前に書くと処置群が先に決まってしまう)
2. llmo_probe.py は鍵の無いモデルを先に外し、1つも無ければ結果ファイルを作らない
3. probe_summary.py は Perplexity・プール内の行だけを組別に数え、9/17 の回は読まない
4. probe.yml は自動実行しない(実験期間中は不使用。2026-09-22 決定)
"""
import csv
import datetime
import io
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))

import allocate_47  # noqa: E402
import llmo_probe  # noqa: E402
import pool  # noqa: E402
import probe_summary  # noqa: E402


# --- 1. 割付の書き出し ------------------------------------------------------------
@pytest.fixture
def cited_csv(tmp_path):
    path = tmp_path / "cited.csv"
    path.write_text("target_url,cited_article\nhttps://cross-com.jp/agentforce-rag/,1\n",
                    encoding="utf-8")
    return path


def _allocate(monkeypatch, tmp_path, cited_csv, *extra):
    out, out_csv = tmp_path / "alloc.md", tmp_path / "alloc.csv"
    monkeypatch.setattr(sys, "argv", ["allocate_47.py", "--cited-csv", str(cited_csv),
                                      "--out", str(out), "--out-csv", str(out_csv), *extra])
    return allocate_47.main(), out, out_csv


def test_the_allocation_is_a_dry_run_by_default(monkeypatch, tmp_path, cited_csv):
    code, out, out_csv = _allocate(monkeypatch, tmp_path, cited_csv)
    assert code == 0 and not out.exists() and not out_csv.exists()


def test_write_is_refused_before_the_allocation_day(monkeypatch, tmp_path, cited_csv):
    monkeypatch.setattr(allocate_47, "ALLOCATION_DAY", datetime.date.today() + datetime.timedelta(days=1))
    code, out, out_csv = _allocate(monkeypatch, tmp_path, cited_csv, "--write")
    assert code == 2 and not out.exists() and not out_csv.exists()


def test_write_on_the_allocation_day_writes_both_tables(monkeypatch, tmp_path, cited_csv):
    monkeypatch.setattr(allocate_47, "ALLOCATION_DAY", datetime.date.today())
    code, out, out_csv = _allocate(monkeypatch, tmp_path, cited_csv, "--write")
    assert code == 0 and out.exists() and out_csv.exists()
    rows = list(csv.DictReader(io.open(out_csv, encoding="utf-8")))
    assert len(rows) == 46
    assert sorted(collections_count(r["group"] for r in rows).values()) == [11, 11, 12, 12]
    # apply_gate の読み方: 3列目にURL、最後の列に組
    table = [ln for ln in out.read_text(encoding="utf-8").splitlines()
             if ln.startswith("| ") and "https://cross-com.jp/" in ln]
    assert len(table) == 46
    cells = [c.strip() for c in table[0].strip("|").split("|")]
    assert cells[2].startswith("https://cross-com.jp/") and cells[-1][0] in "①②③④"


def collections_count(items):
    import collections
    return collections.Counter(items)


def test_the_default_output_is_the_file_apply_gate_reads():
    """seo-agent の apply_gate はこの名前の md を読む。名前を変えると処置が通らなくなる。"""
    import argparse
    src = (ROOT / "experiment_2x2" / "allocate_47.py").read_text(encoding="utf-8")
    assert "experiment47_allocation_v1_20260928.md" in src


# --- 2. プローブの鍵 --------------------------------------------------------------
def test_models_without_a_key_are_dropped(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llmo_probe.runnable_models(["claude", "perplexity"]) == ["claude"]


def test_no_key_means_no_result_file(monkeypatch, tmp_path):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(llmo_probe, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["llmo_probe.py", "--models", "perplexity"])
    assert llmo_probe.main() == 0
    assert list(tmp_path.iterdir()) == []


def test_gemini_is_not_in_the_default_models():
    src = (ROOT / "experiment_2x2" / "llmo_probe.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--models", default="claude,perplexity")' in src


# --- 3. probe_summary -----------------------------------------------------------
HEADER = ["run_date", "id", "url", "group", "model", "run", "cited", "site_cited", "cited_urls"]


def _results(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow(r)


def test_the_summary_counts_perplexity_rows_in_the_pool_by_group(monkeypatch, tmp_path):
    rag, roi = "https://cross-com.jp/agentforce-rag/", "https://cross-com.jp/agentforce-roi/"
    alloc = tmp_path / "allocation_v1.csv"
    alloc.write_text(f"id,url,group,seed\nE06,{rag},②FAQのみ,1\nE05,{roi},①対照,1\n",
                     encoding="utf-8")
    monkeypatch.setattr(pool, "ALLOCATION_CSV", str(alloc))
    monkeypatch.setattr(probe_summary, "load_allocation", lambda: pool.load_allocation(str(alloc)))
    res = tmp_path / "2026-10-06.csv"
    _results(res, [
        ["2026-10-06", "E06", rag, "", "perplexity", 1, 1, 1, rag],
        ["2026-10-06", "E06", rag, "", "perplexity", 2, 0, 0, ""],
        ["2026-10-06", "E05", roi, "", "perplexity", 1, 0, 0, ""],
        ["2026-10-06", "E06", rag, "", "claude", 1, 1, 1, rag],                     # Claude は数えない
        ["2026-10-06", "E37", "https://cross-com.jp/agentforce-coworker/", "", "perplexity", 1, 1, 1, ""],
    ])
    text = probe_summary.render([str(res)])
    assert "参考データ。判定には使わない" in text
    assert "| ①対照 | 0/1 | 0% | 0/1 | 0% |" in text
    assert "| ②FAQのみ | 1/1 | 100% | 1/2 | 50% |" in text
    assert "| 計 | 1/2 | 50% | 1/3 | 33% |" in text


def test_rows_before_the_allocation_are_grouped_as_unallocated(monkeypatch, tmp_path):
    monkeypatch.setattr(probe_summary, "load_allocation", lambda: {})
    rag = "https://cross-com.jp/agentforce-rag/"
    res = tmp_path / "2026-09-25.csv"
    _results(res, [["2026-09-25", "E06", rag, "", "perplexity", 1, 0, 0, ""]])
    assert "| （割付前） | 0/1 | 0% | 0/1 | 0% |" in probe_summary.render([str(res)])


def test_the_old_9_17_baseline_is_never_read(tmp_path):
    res = tmp_path / "2026-09-17.csv"
    _results(res, [["2026-09-17", "1", "https://cross-com.jp/agentforce-rag/", "", "perplexity",
                    1, 1, 1, ""]])
    text = probe_summary.render([str(res)])
    assert "## 2026-09-17" not in text and "読まなかった回" in text


# --- 4. ワークフロー --------------------------------------------------------------
def test_the_probe_workflow_is_not_scheduled_during_the_experiment():
    """2026-09-22 決定: 実験期間中はプローブを使わない(Perplexity 不使用)。"""
    text = (ROOT / ".github" / "workflows" / "probe.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    triggers = doc.get(True) or doc.get("on")
    assert "schedule" not in triggers, "自動実行は外してあるはず"
    assert set(triggers) == {"workflow_dispatch"}
    # 手動で起動しても 2026-12-31 までは観測しない
    assert '"$TODAY" < "2027-01-01"' in text and 'echo "run=false"' in text


def test_the_readme_says_the_probe_is_unused():
    text = (ROOT / "experiment_2x2" / "README.md").read_text(encoding="utf-8")
    assert "プローブは実験期間中は不使用。判定は llm_experiment のみ。" in text


# --- 5. summarize.py(判定は llm_experiment のみ・2026-09-23) -----------------------
import summarize  # noqa: E402

EXP_HEAD = ["date", "experiment_id", "model", "target_url", "cited_article", "error",
            "experiment_flag"]


def _exp_csv(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXP_HEAD)
        w.writerows(rows)


def test_condition_f_covers_vibes_and_features():
    """条件 f は vibes の訂正見送り(2026-09-26)後も2本のまま。

    9/28 のシード探索は条件で決まるので、後から条件を動かすと引き直しの結果が変わる。
    実際に訂正が入るのは features の1本だけで、感度分析で抜くのはそちら。
    """
    assert pool.CORRECTION_SLUGS == ("agentforce-vibes", "agentforce-features")
    assert pool.APPLIED_CORRECTION_SLUGS == ("agentforce-features",)


def test_summarize_reads_llm_experiment_and_drops_watch_rows(monkeypatch, tmp_path, capsys):
    rag = "https://cross-com.jp/agentforce-rag/"
    feat = "https://cross-com.jp/agentforce-features/"      # 訂正対象(9/29〜30)
    cowork = "https://cross-com.jp/agentforce-coworker/"
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"agentforce-rag": "③リードのみ",
                                 "agentforce-features": "①対照",
                                 "agentforce-coworker": "④両方"})
    path = tmp_path / "llm_experiment.csv"
    _exp_csv(path, [
        ["2026-09-20", "E06", "gemini", rag, "0", "", "pool"],
        ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
        ["2026-10-10", "E12", "gemini", feat, "1", "", "pool"],
        ["2026-10-10", "E37", "gemini", cowork, "1", "", "watch"],       # watch は数えない
        ["2026-10-11", "E06", "gemini", rag, "", "503 UNAVAILABLE", "pool"],  # 欠測は数えない
    ])
    assert summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-08:2026-10-27",
                           "--csv", str(path), "--model", "gemini"]) == 0
    out = capsys.readouterr().out
    assert "watch 1行" in out
    assert "gemini 両方込み（2本）" in out
    assert "gemini features 抜き（訂正対象）（1本）" in out
    # E37(watch)は④両方に割り付けてあるが、数えないので④両方は0本のまま
    assert "④両方:" not in out, "watch の E37 が組に入っている"
    import re
    both = re.split(r"\s{2,}",
                    [ln for ln in out.splitlines() if ln.startswith("両方込み")][0])
    # 列: 変種, 本数, ①対照, ②FAQのみ, ③リードのみ, ④両方, ...
    assert both[5] == "—", both
    assert "③リードのみ: 1/1 = 100%   Δ平均 +1.00" in out


def test_summarize_refuses_to_judge_before_the_allocation(monkeypatch, tmp_path):
    monkeypatch.setattr(summarize, "load_allocation", lambda: {})
    path = tmp_path / "e.csv"
    _exp_csv(path, [])
    with pytest.raises(SystemExit):
        summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-08:2026-10-27",
                        "--csv", str(path)])


def test_summarize_still_refuses_the_old_probe_baseline(tmp_path):
    with pytest.raises(SystemExit):
        summarize.main(["--probe", str(tmp_path / "2026-10-06.csv"), str(tmp_path / "2026-09-17.csv")])


# --- 6. 9/15〜16 の追記9本(条件 b・e とビフォー基準値。2026-09-25) --------------------
def test_the_strata_splits_all_appends_from_the_late_nine():
    """全編集一覧(2026-09-25 取り込み)から: 条件 b は23本、条件 e は9本。"""
    appended = pool.appended_slugs()
    late = pool.late_appended_slugs()
    assert len(appended) == 23, "内部リンクが増えた記事(条件 b)"
    assert len(late) == 9, "観測開始(9/15 08:00)〜9/16 に変わった記事(条件 e)"
    assert late <= pool.pool_slugs()
    assert "revops-guide" in late and "agentforce-rag" not in late
    # 9/15 01:34 の2本は観測開始より前。リンクは増えたので b には入るが e には入らない
    for slug in ("agentforce-einstein-difference", "agentforce-service-agent"):
        assert slug in appended and slug not in late, slug


def test_a_newer_strata_file_is_not_adopted_automatically(tmp_path, monkeypatch):
    """採用中の層ファイルは pool.py で名前を固定する(2026-10-01)。

    新しい日付のファイルを作っても、pool.py の指定を書き換えない限り採用されない。
    以前は最新の日付を自動で選び、確定した条件 b・e・g の入力が気づかないまま替わった。
    """
    adopted = tmp_path / "strata_backlink_20260925.csv"
    adopted.write_text("slug,appended_at\n", encoding="utf-8")
    monkeypatch.setattr(pool, "STRATA_FILE", str(adopted))
    (tmp_path / "strata_backlink_20261002.csv").write_text("slug,appended_at\n", encoding="utf-8")
    assert pool.strata_path() == str(adopted)


def test_a_missing_adopted_file_stops_instead_of_falling_back(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "STRATA_FILE", str(tmp_path / "strata_backlink_20260925.csv"))
    (tmp_path / "strata_backlink_20261002.csv").write_text("slug,appended_at\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        pool.strata_path()


def test_the_adopted_files_are_the_9_25_ones():
    """今の採用中のファイル名を固定する。替えるときは pool.py と日誌とこのテストを一緒に直す。"""
    import os
    assert os.path.basename(pool.STRATA_FILE) == "strata_backlink_20260925.csv"
    assert os.path.basename(pool.TITLE_CHANGE_FILE) == "title_changes_20260925.csv"
    assert os.path.basename(pool.LATE_CHANGE_FILE) == "late_changes_20260925.csv"
    for path in (pool.STRATA_FILE, pool.TITLE_CHANGE_FILE, pool.LATE_CHANGE_FILE):
        assert os.path.exists(path), path


def test_the_allocation_checks_b_and_e(monkeypatch, tmp_path, cited_csv):
    monkeypatch.setattr(allocate_47, "ALLOCATION_DAY", datetime.date.today())
    code, out, _ = _allocate(monkeypatch, tmp_path, cited_csv, "--write")
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "b 逆リンク追記23本が組間で均等" in text
    assert "e 9/15〜16 の追記9本が各組2〜3本" in text
    assert "| 9/15〜16 の変更 |" in text, "割付表に列がある(追記＋タイトル変更)"
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "cross-com.jp" in ln]
    late = [ln for ln in rows if ln.split("|")[7].strip() == "あり"]
    assert len(late) == 9


def test_the_baseline_skips_observations_before_the_append(monkeypatch, tmp_path, capsys):
    """revops-guide は 9/15 に追記。9/16 までの観測は基準値に使わない。"""
    revops = "https://cross-com.jp/revops-guide/"
    rag = "https://cross-com.jp/agentforce-rag/"
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"revops-guide": "①対照", "agentforce-rag": "②FAQのみ"})
    path = tmp_path / "e.csv"
    _exp_csv(path, [
        ["2026-09-16", "E28", "gemini", revops, "1", "", "pool"],   # 追記前。使わない
        ["2026-09-18", "E28", "gemini", revops, "0", "", "pool"],
        ["2026-09-16", "E06", "gemini", rag, "1", "", "pool"],      # 追記なし。使う
        ["2026-10-10", "E28", "gemini", revops, "1", "", "pool"],
        ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
    ])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-08:2026-10-27",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    assert "9本は 2026-09-17 以降の観測だけを使う" in out
    # revops のビフォーは 9/18 の 0 だけ → Δ+1.00、rag は 9/16 の 1 が残る → Δ0.00
    assert "①対照: 1/1 = 100%   Δ平均 +1.00" in out
    assert "②FAQのみ: 1/1 = 100%   Δ平均 +0.00" in out


# --- 7. 感度分析(2026-09-25) -------------------------------------------------------
def test_the_four_variants_are_the_agreed_ones():
    labels = [label for label, _ in summarize.variants()]
    # 2026-09-29：複数段落回答の表があれば5通り目が末尾に付く(tests/test_rerandomize.py で確認)
    assert labels[0] == "両方込み" and labels[3] == "9本＋features 抜き"
    assert len(labels) == 6 and labels[4].startswith("複数段落回答抜き")
    assert labels[5].startswith("ピラーの既存リンク先抜き（27本")              # 2026-10-02 追加
    assert "9本抜き" in labels[1] and labels[2] == "features 抜き（訂正対象）"
    by_label = dict(summarize.variants())
    applied = set(pool.APPLIED_CORRECTION_SLUGS)
    assert by_label["両方込み"] == set()
    assert by_label[labels[1]] == pool.late_appended_slugs()
    assert by_label[labels[2]] == applied, "抜くのは訂正が入る features だけ"
    assert "agentforce-vibes" not in by_label[labels[2]], "vibes は訂正見送り"
    assert by_label["9本＋features 抜き"] == pool.late_appended_slugs() | applied


def test_the_judgement_prints_one_table_with_six_rows(monkeypatch, tmp_path, capsys):
    rag = "https://cross-com.jp/agentforce-rag/"          # 追記なし・訂正対象でない
    revops = "https://cross-com.jp/revops-guide/"         # 9/15〜16 追記の9本
    feat = "https://cross-com.jp/agentforce-features/"    # 訂正対象(features の1本のみ)
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"agentforce-rag": "①対照", "revops-guide": "②FAQのみ",
                                 "agentforce-features": "③リードのみ"})
    path = tmp_path / "e.csv"
    _exp_csv(path, [
        ["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
        ["2026-09-18", "E28", "gemini", revops, "0", "", "pool"],
        ["2026-09-18", "E12", "gemini", feat, "0", "", "pool"],
        ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
        ["2026-10-10", "E28", "gemini", revops, "1", "", "pool"],
        ["2026-10-10", "E12", "gemini", feat, "1", "", "pool"],
    ])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-08:2026-10-27",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    import re
    table = [re.split(r"\s{2,}", ln)
             for ln in out.splitlines()
             if ln.startswith(("両方込み", "9本抜き", "features 抜き", "9本＋features",
                               "複数段落回答抜き", "ピラーの既存リンク先抜き"))]
    assert len(table) == 6, out
    # 3本 → 9本を抜くと2本、features を抜くと2本、両方抜くと1本。
    # 3本とも複数段落回答ではないので、5通り目は3本のまま。3本ともピラーの既存リンク先なので6通り目は0本
    assert [r[1] for r in table] == ["3", "2", "2", "1", "3", "0"], table
    assert "感度分析（gemini）" in out, "見出しに余分な空白を入れない"
    assert out.count("=== gemini ") == 6, "6通りそれぞれの内訳も出す"


# --- 8. 条件 g: タイトル変更3本(2026-09-25) ----------------------------------------
def test_the_three_title_changes_are_in_the_pool():
    titles = pool.title_changed_slugs()
    assert titles == {"agentforce-for-sales-sdr-sales-coach", "agentic-ai-guide",
                      "agentic-crm-pipeline-stagnation-detection"}
    assert titles <= pool.pool_slugs()


def test_condition_g_keeps_the_title_changes_apart(monkeypatch, tmp_path, cited_csv):
    monkeypatch.setattr(allocate_47, "ALLOCATION_DAY", datetime.date.today())
    code, out, out_csv = _allocate(monkeypatch, tmp_path, cited_csv, "--write")
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "g タイトル変更3本が各組に最大1本" in text
    groups = {r["url"].rstrip("/").rsplit("/", 1)[-1]: r["group"]
              for r in csv.DictReader(io.open(out_csv, encoding="utf-8"))}
    assigned = [groups[s] for s in pool.title_changed_slugs()]
    assert len(set(assigned)) == 3, f"3本が別々の組に入っていない: {assigned}"
    assert "| タイトル変更 |" in text


def test_a_title_change_dated_9_15_joins_the_late_list(monkeypatch, tmp_path):
    """全編集一覧が無いときの手当て: TITLE_CHANGE_DATES から 9/15 以降を拾う。

    一覧があるときは時刻で切った late_changes_*.csv が優先される(そちらは
    tests/test_edits_ingest.py で固定)。
    """
    monkeypatch.setattr(pool, "LATE_CHANGE_FILE", None)
    monkeypatch.setattr(pool, "TITLE_CHANGE_FILE", None)
    before = pool.late_appended_slugs()
    assert "agentic-ai-guide" not in before, "日付が分かるまでは入れない"
    monkeypatch.setattr(pool, "TITLE_CHANGE_DATES",
                        {"agentic-ai-guide": "2026-09-16", "agentic-crm-pipeline-stagnation-detection": "2026-09-12"})
    after = pool.late_appended_slugs()
    assert "agentic-ai-guide" in after, "9/16 の変更は対象"
    assert "agentic-crm-pipeline-stagnation-detection" not in after, "9/12 の変更は対象外"
    assert before < after and len(after) == len(before) + 1
    assert pool.baseline_start("agentic-ai-guide") == pool.LATE_BASELINE_FROM


def test_load_probe_takes_groups_from_allocation_not_the_csv(tmp_path, monkeypatch):
    """2026-09-30: 結果CSVの group 列（9/17 は割付前 v0）ではなく allocation_v1 の組で数える。"""
    p = tmp_path / "2026-10-06.csv"
    p.write_text("url,group,cited\nhttps://cross-com.jp/agentforce-rag/,①対照,1\n", encoding="utf-8")
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "④両方"})
    monkeypatch.setattr(summarize, "pool_slugs", lambda: {"agentforce-rag"})
    assert summarize.load_probe(str(p)) == {"agentforce-rag": ("④両方", 1)}


# --- 判定期間と重なるサイト全体の介入(2026-10-01) -------------------------------------------
def _iv(raw, iid, scope="サイト全体"):
    import interventions
    return {"raw_date": raw, "date": interventions.parse_date(raw), "intervention_id": iid,
            "description": f"{iid} の内容", "scope": scope, "touches_pool46": "yes",
            "ongoing": raw.rstrip().endswith(interventions.ONGOING_MARKS)}


def test_site_wide_interventions_that_overlap_the_judgement_are_listed():
    import datetime as dt
    rows = [_iv("2026-09-10", "OLD"), _iv("2026-09-10〜16", "RANGE_IN"),
            _iv("2026-09-01〜09-14", "RANGE_OUT"), _iv("2026-09-01〜", "ONGOING"),
            _iv("2026-09-30", "B33"), _iv("2026-11-05", "LATER"),
            _iv("2026-09-30", "ARTICLE", scope="サイト(記事)"), _iv("", "UNDATED")]
    overlap, undated = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1), rows)
    # 2026-10-07 から scope で絞らない(サイト(記事)の ARTICLE も載る)。期間外(OLD・RANGE_OUT・LATER)は載らない
    assert [r["intervention_id"] for r in overlap] == ["RANGE_IN", "ONGOING", "B33", "ARTICLE"]
    assert [r["intervention_id"] for r in undated] == ["UNDATED"]


def test_the_judgement_report_starts_with_the_site_wide_interventions(monkeypatch, tmp_path, capsys):
    rag = "https://cross-com.jp/agentforce-rag/"
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "①対照"})
    path = tmp_path / "e.csv"
    _exp_csv(path, [["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
                    ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"]])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-11-01",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    head = out.split("#####")[0]
    assert "判定期間（2026-09-15〜2026-11-01）に日付が重なる interventions.csv の全行" in head
    assert "｜I-14｜B-33" in head and "｜I-04｜" in head


# --- 9. Claude は観測1回あたりの率で比べる(2026-10-03・本田さん決定) ----------------------
# Claude の観測は 2026-10-05 から週2回→週1回(月曜のみ)。ビフォー(週2回)とアフター(週1回)で
# 回数が違うので、「1回でも引用されたか」の二値ではなく、記事ごとの cited_article=1 の率で比べる。
# Gemini は「1回でも」のまま変えない
def test_claude_is_judged_by_the_rate_per_observation_and_gemini_by_any():
    rag = "https://cross-com.jp/agentforce-rag/"
    rows = [{"date": d, "model": m, "target_url": rag, "cited_article": c, "error": "",
             "experiment_flag": "pool"}
            for d, m, c in [("2026-09-21", "claude", "1"), ("2026-09-24", "claude", "0"),
                            ("2026-09-28", "claude", "0"), ("2026-10-01", "claude", "0"),
                            ("2026-09-21", "gemini", "1"), ("2026-09-24", "gemini", "0")]]
    groups = {"agentforce-rag": "①対照"}
    span = ("2026-09-15", "2026-09-28")
    pool_ = {"agentforce-rag"}
    claude = summarize.period(rows, span, "claude", groups, pool_)
    gemini = summarize.period(rows, span, "gemini", groups, pool_)
    assert claude["agentforce-rag"] == ("①対照", 1 / 3), "3回中1回 → 率 1/3(二値なら1)"
    assert gemini["agentforce-rag"] == ("①対照", 1), "Gemini は1回でも引用されたら1"
    assert summarize.RATE_MODELS == ("claude",)


def test_the_rate_does_not_reward_more_observations():
    """同じ引用されやすさでも、回数が多い期間ほど「1回でも」は1になりやすい。率ならそうならない。"""
    rag = "https://cross-com.jp/agentforce-rag/"
    groups, pool_ = {"agentforce-rag": "①対照"}, {"agentforce-rag"}
    before = [("2026-09-21", "1"), ("2026-09-24", "0"), ("2026-09-25", "0"), ("2026-09-28", "0")]
    after = [("2026-10-12", "0"), ("2026-10-19", "1"), ("2026-10-26", "0"), ("2026-11-02", "0")]
    rows = [{"date": d, "model": "claude", "target_url": rag, "cited_article": c, "error": "",
             "experiment_flag": "pool"} for d, c in before + after]
    b = summarize.period(rows, ("2026-09-15", "2026-09-28"), "claude", groups, pool_)
    a = summarize.period(rows, ("2026-10-06", "2026-11-02"), "claude", groups, pool_)
    groups_t = summarize.tally(a, b)
    assert groups_t["①対照"] == [(0.25, 0.0)], "率が同じなら変化(差の差の材料)は0"


def test_the_claude_judgement_shows_rates_and_no_fisher(monkeypatch, tmp_path, capsys):
    rag = "https://cross-com.jp/agentforce-rag/"             # ③リードのみ
    feat = "https://cross-com.jp/agentforce-features/"       # ①対照
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"agentforce-rag": "③リードのみ", "agentforce-features": "①対照"})
    path = tmp_path / "e.csv"
    _exp_csv(path, [
        # ビフォー:週2回(rag は4回中1回、features は4回中0回)
        ["2026-09-21", "E06", "claude", rag, "1", "", "pool"],
        ["2026-09-24", "E06", "claude", rag, "0", "", "pool"],
        ["2026-09-25", "E06", "claude", rag, "0", "", "pool"],
        ["2026-09-28", "E06", "claude", rag, "0", "", "pool"],
        ["2026-09-21", "E12", "claude", feat, "0", "", "pool"],
        ["2026-09-28", "E12", "claude", feat, "0", "", "pool"],
        # アフター:週1回(rag は2回中1回、features は2回中0回。欠測1件は分母に入れない)
        ["2026-10-12", "E06", "claude", rag, "1", "", "pool"],
        ["2026-10-19", "E06", "claude", rag, "0", "", "pool"],
        ["2026-10-26", "E06", "claude", rag, "", "overloaded", "pool"],
        ["2026-10-12", "E12", "claude", feat, "0", "", "pool"],
        ["2026-10-19", "E12", "claude", feat, "0", "", "pool"],
    ])
    assert summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-06:2026-10-27",
                           "--csv", str(path), "--model", "claude"]) == 0
    out = capsys.readouterr().out
    assert "記事ごとの引用率の平均" in out
    assert "③リードのみ: 平均 50%（1本）   Δ平均 +0.25" in out, "率 1/2 − ビフォーの率 1/4"
    assert "①対照: 平均 0%（1本）   Δ平均 +0.00" in out
    assert "片側p(フィッシャー)=—（率のため対象外）" in out
    import re
    both = re.split(r"\s{2,}", [ln for ln in out.splitlines() if ln.startswith("両方込み")][0])
    assert both[2] == "平均0%（1本）" and both[4] == "平均50%（1本）", both
    assert both[8] == "—" and both[11] == "—", "率ではフィッシャーの列は空"
    assert "※ Claude は記事ごとの率" in out


def test_gemini_judgement_is_unchanged(monkeypatch, tmp_path, capsys):
    rag = "https://cross-com.jp/agentforce-rag/"
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "③リードのみ"})
    path = tmp_path / "e.csv"
    _exp_csv(path, [
        ["2026-09-20", "E06", "gemini", rag, "0", "", "pool"],
        ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
        ["2026-10-12", "E06", "gemini", rag, "0", "", "pool"],
    ])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", "2026-10-08:2026-10-27",
                    "--csv", str(path), "--model", "gemini"])
    out = capsys.readouterr().out
    assert "③リードのみ: 1/1 = 100%   Δ平均 +1.00" in out, "Gemini は1回でも引用されたら1"
    assert "率のため対象外" not in out and "※ Claude は記事ごとの率" not in out


def test_the_randomization_test_takes_rates_as_they_are():
    import rerandomize
    arts = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]
    assert rerandomize.outcomes_for(arts, {"a": 0.25, "b": 1, "c": 0}) == [0.25, 1, 0]
    assert isinstance(rerandomize.outcomes_for(arts, {"a": 1})[0], int), "0/1 は整数のまま"
    # 率でも「実際の差以上」の割付を数える(同じ並びは必ず数える。足し算の誤差で落とさない)
    labels = [0, 1, 2, 3]
    outcomes = [0.1, 0.2, 0.3, 0.7]
    flipped = "3412"
    got = rerandomize.p_values([(1, "1234"), (2, flipped)], labels, outcomes)
    assert got["lead_diff"] == pytest.approx(0.35)
    assert got["lead_p"] == pytest.approx(0.5), "同じ並びの1通りだけが実際以上"


# --- 10. 引用プローブの上限漏れを塞ぐ(2026-10-03) -------------------------------------------
# 実験期間中(〜2026-12-31)は API を呼ばずに終わる(--force でも)。2027-01-01 以降は Claude の呼び出しが
# src/claude_budget.py の1日の上限・クレジット不足での停止を通る
def test_the_probe_is_blocked_until_the_experiment_ends():
    assert llmo_probe.experiment_end() == "2026-12-31"
    assert llmo_probe.blocked("2026-10-03") and llmo_probe.blocked("2026-12-31")
    assert not llmo_probe.blocked("2027-01-01")


def test_the_probe_calls_no_api_during_the_experiment_even_with_force(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(llmo_probe, "today_jst", lambda: "2026-10-03")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "x")
    monkeypatch.setattr(llmo_probe, "post_json", lambda *a, **k: pytest.fail("実験期間中は呼ばない"))
    monkeypatch.setattr(llmo_probe, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["llmo_probe.py", "--models", "claude,perplexity", "--force"])
    assert llmo_probe.main() == 0
    assert list(tmp_path.iterdir()) == [], "結果ファイルも作らない"
    assert "--force でも呼ばない" in capsys.readouterr().out
    for ask in (llmo_probe.ask_claude, llmo_probe.ask_perplexity):
        with pytest.raises(llmo_probe.ProbeBlocked):
            ask("質問")                       # resume_probe.py が直接呼んでも止まる


def test_resume_probe_also_stops_during_the_experiment(tmp_path):
    import subprocess
    if not llmo_probe.blocked():
        pytest.skip("実験期間が終わったあと")
    env = dict(os.environ, ANTHROPIC_API_KEY="x", PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "experiment_2x2" / "resume_probe.py"),
                          "--date", "2099-01-01"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "API を呼ばずに終了" in out.stdout
    assert not (tmp_path / "results").exists()


def _after_the_experiment(monkeypatch):
    monkeypatch.setattr(llmo_probe, "today_jst", lambda: "2027-01-05")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


def test_after_the_experiment_the_probe_goes_through_the_daily_cap(monkeypatch):
    import claude_budget
    _after_the_experiment(monkeypatch)
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "1")
    sent = []
    monkeypatch.setattr(llmo_probe, "post_json",
                        lambda *a, **k: sent.append(1) or {"content": "https://cross-com.jp/a/"})
    assert llmo_probe.ask_claude("質問") == {"https://cross-com.jp/a/"}
    with pytest.raises(claude_budget.ClaudeStopped, match="^daily_cap"):
        llmo_probe.ask_claude("質問")
    assert len(sent) == 1, "上限を超えた分は投げない"


def test_a_credit_400_from_the_probe_stops_the_day(monkeypatch):
    import urllib.error
    import claude_budget
    _after_the_experiment(monkeypatch)
    body = (b'{"type":"error","error":{"type":"invalid_request_error",'
            b'"message":"Your credit balance is too low to access the Anthropic API."}}')
    sent = []

    def post(*a, **k):
        sent.append(1)
        raise urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 400, "Bad Request", {},
                                     io.BytesIO(body))

    monkeypatch.setattr(llmo_probe, "post_json", post)
    with pytest.raises(RuntimeError, match="credit balance is too low"):
        llmo_probe.ask_claude("質問")
    with pytest.raises(claude_budget.ClaudeStopped, match="^credit_exhausted"):
        llmo_probe.ask_claude("質問")
    assert len(sent) == 1 and claude_budget.status()["stopped"] == "credit_exhausted"


def test_nothing_in_the_repo_calls_anthropic_without_the_daily_cap():
    """Anthropic の API を直接呼ぶ処理は claude_budget を通るものだけ(2026-10-03 にリポジトリ全体を検索)。

    - SDK の messages.create を呼んでいいのは claude_budget.create だけ(ほかは claude_budget.create(client, …))
    - HTTP で api.anthropic.com を呼ぶのは引用プローブだけで、claude_budget.guard を通る
    """
    import re
    files = [p for d in ("src", "experiment_2x2", "scripts", "app")
             for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts]
    sdk = [p.relative_to(ROOT).as_posix() for p in files
           if re.search(r"\.messages\.(create|stream)\(", p.read_text(encoding="utf-8"))]
    assert sdk == ["src/claude_budget.py"], sdk
    http = [p for p in files if "api.anthropic.com" in p.read_text(encoding="utf-8")]
    assert [p.relative_to(ROOT).as_posix() for p in http] == ["experiment_2x2/llmo_probe.py"]
    assert "claude_budget.guard(" in http[0].read_text(encoding="utf-8")


# --- 11. 交絡候補の一覧(2026-10-07・本田さん決定で全介入に拡大) -----------------------------------
# interventions.csv の全行のうち判定期間(ビフォーの初日〜アフターの最終日)に日付が重なるものを、scope ごとに載せる。
# touches_pool46=yes の行を含む scope が先。日付が定まらない行は末尾に「日付不確定」。判定の数値は一切変えない
def test_every_intervention_in_the_period_is_listed_whatever_its_scope():
    import datetime as dt
    rows = [_iv("2026-10-20", "HYG", scope="site_hygiene"), _iv("2026-09-26", "FORM", scope="固定ページ4件（68 /contact/）"),
            _iv("2026-09-30", "ARTICLE", scope="サイト(記事)"), _iv("2026-09-20", "EXT", scope="外部(エンティティ)"),
            _iv("2027-01-05", "LATE", scope="site_hygiene"), _iv("2026-09-11", "EARLY", scope="プール46本"),
            _iv("2026-09-15より前", "BEFORE", scope="サイト(メタ)")]
    for r in rows:
        r["touches_pool46"] = "no"
    rows[2]["touches_pool46"] = "yes"
    overlap, undated = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 12, 28), rows)
    assert sorted(r["intervention_id"] for r in overlap) == ["ARTICLE", "EXT", "FORM", "HYG"]
    assert [r["intervention_id"] for r in undated] == ["BEFORE"], "「〜より前」は日付不確定"
    groups = summarize.group_by_scope(overlap)
    assert [k for k, _ in groups] == ["サイト", "外部", "固定ページ", "site_hygiene"],         "プール46本に触れる行を含む scope が先、その後は日付順"
    assert not hasattr(summarize, "CONFOUNDER_SCOPES"), "scope で絞らない"


def test_the_real_log_lists_the_form_changes_i15_to_i17():
    import datetime as dt
    overlap, undated = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1))
    ids = {r["intervention_id"] for r in overlap}
    assert {"I-15", "I-16", "I-17"} <= ids, "scope が「固定ページ…」でも載る"
    assert not ids & {"I-11", "I-12"}, "9/14 までに終わった介入は判定期間の外"
    assert "I-05" in {r["intervention_id"] for r in undated}


def _judge_out(monkeypatch, tmp_path, capsys, rows_iv, after):
    import interventions
    rag = "https://cross-com.jp/agentforce-rag/"
    feat = "https://cross-com.jp/agentforce-features/"
    monkeypatch.setattr(summarize, "load_allocation",
                        lambda: {"agentforce-rag": "③リードのみ", "agentforce-features": "①対照"})
    monkeypatch.setattr(interventions, "load", lambda *a, **k: rows_iv)
    path = tmp_path / "e.csv"
    _exp_csv(path, [["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
                    ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
                    ["2026-09-18", "E12", "gemini", feat, "0", "", "pool"],
                    ["2026-10-11", "E12", "gemini", feat, "0", "", "pool"]])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", after, "--csv", str(path), "--model", "gemini"])
    return capsys.readouterr().out


def test_the_list_is_in_both_judgements_and_changes_no_number(monkeypatch, tmp_path, capsys):
    rows_iv = [_iv("2026-10-20", "I-90", scope="site_hygiene"), _iv("2026-09-26", "I-91", scope="固定ページ4件")]
    for after in ("2026-10-06:2026-11-01", "2026-10-06:2026-12-28"):     # 短期判定・長期判定
        with_list = _judge_out(monkeypatch, tmp_path, capsys, rows_iv, after)
        without = _judge_out(monkeypatch, tmp_path, capsys, [], after)
        head = with_list.split("#####")[0]
        assert "## 判定期間（ビフォー〜アフター）中のサイト施策一覧（判定の交絡候補）" in head
        assert "  - 2026-10-20｜I-90｜I-90 の内容｜scope=site_hygiene｜touches_pool46=yes" in head
        assert "｜I-91｜" in head
        # 一覧の部分を除くと1文字も変わらない(差の差・p値・感度分析は同じ)
        assert with_list.split("#####", 1)[1] == without.split("#####", 1)[1]


def test_scopes_with_a_count_are_grouped_together():
    """「固定ページ4件」「固定ページ1件」「固定ページ3件」は「固定ページ」にまとめる(2026-10-07)。"""
    assert summarize.scope_key("固定ページ4件（68 /contact/・1891 /download-paper/）") == "固定ページ"
    assert summarize.scope_key("固定ページ1件") == "固定ページ"
    assert summarize.scope_key("ピラーA（agentforce-guide）") == "ピラーA"
    assert summarize.scope_key("measurement") == "measurement"
    import datetime as dt
    overlap, _ = summarize.site_wide_interventions(dt.date(2026, 9, 15), dt.date(2026, 11, 1))
    groups = dict(summarize.group_by_scope(overlap))
    assert sorted(r["intervention_id"] for r in groups["固定ページ"]) == ["I-15", "I-16", "I-17"]

