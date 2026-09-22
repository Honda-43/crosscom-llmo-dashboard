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
