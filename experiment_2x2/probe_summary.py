#!/usr/bin/env python3
"""probe_summary.py｜引用プローブの Perplexity の cited_article 率を組別に出す（2026-09-22）。

**参考データ。判定には使わない。** 判定は dashboard の llm_experiment だけで行う
（summarize.py とは別物。summarize.py は判定の手順を残すためのもの）。

- 対象はプール46本（pool.py）。E37 とプール外の行は数えない
- 組は割付の結果 allocation_v1.csv から引く（結果CSVの group 列は使わない）。
  割付前（9/25 のビフォーなど）に取った行も、割付が出たあとで組別に並べ直せる
- 率は2通り: 記事単位（その回に1回でも引用された記事 / 記事数）と、試行単位
  （cited=1 の行 / 行数）
- 2026-09-17 の回（旧い質問文・Claude のみ）は指定されても読まない

使い方:
  python probe_summary.py results/2026-09-25.csv [results/2026-10-06.csv ...]
  python probe_summary.py results/*.csv --out ../output/reports/experiment47_probe_20261006.md
"""
import argparse
import collections
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import (EXCLUDED, PROBE_BASELINE_EXCLUDED, load_allocation,  # noqa: E402
                  load_pool, slug)

MODEL = "perplexity"
UNALLOCATED = "（割付前）"
GROUP_ORDER = ["①対照", "②FAQのみ", "③リードのみ", "④両方", UNALLOCATED]


def load_rows(path, pool):
    """結果CSVのうち、プール内・Perplexity の行。"""
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows
            if r.get("model") == MODEL and slug(r["url"]) in pool and slug(r["url"]) not in EXCLUDED]


def summarize_file(path, pool, groups):
    """(日付, {組: (引用された記事, 記事数, cited行, 行数)})。"""
    rows = load_rows(path, pool)
    by_article = collections.defaultdict(list)
    for r in rows:
        by_article[slug(r["url"])].append(int(r["cited"]))
    stats = collections.defaultdict(lambda: [0, 0, 0, 0])
    for s, cited in by_article.items():
        g = groups.get(s, UNALLOCATED)
        stats[g][0] += int(any(cited))
        stats[g][1] += 1
        stats[g][2] += sum(cited)
        stats[g][3] += len(cited)
    date = rows[0]["run_date"] if rows else os.path.splitext(os.path.basename(path))[0]
    return date, stats


def render(paths):
    pool = {a["slug"] for a in load_pool()}
    groups = load_allocation()
    lines = ["# 引用プローブ（Perplexity）の組別 cited_article 率", "",
             "**参考データ。判定には使わない（判定は llm_experiment のみ）。**", "",
             f"- 対象: プール{len(pool)}本。組は allocation_v1.csv"
             + ("" if groups else "（まだ無い。9/28 の割付前なので全件「割付前」）"),
             "- 記事単位 = その回に1回でも引用された記事 / 観測した記事。試行単位 = cited=1 の行 / 行数",
             ""]
    skipped = []
    for path in paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in PROBE_BASELINE_EXCLUDED:
            skipped.append(path)
            continue
        date, stats = summarize_file(path, pool, groups)
        lines += [f"## {date}", ""]
        if not stats:
            lines += ["Perplexity の行が無い（鍵が無い日は観測していない）。", ""]
            continue
        lines += ["| 組 | 記事単位 | 率 | 試行単位 | 率 |", "|---|---:|---:|---:|---:|"]
        total = [0, 0, 0, 0]
        for g in [g for g in GROUP_ORDER if g in stats] + sorted(set(stats) - set(GROUP_ORDER)):
            a, n, c, t = stats[g]
            total = [x + y for x, y in zip(total, (a, n, c, t))]
            lines.append(f"| {g} | {a}/{n} | {a / n:.0%} | {c}/{t} | {c / t:.0%} |")
        a, n, c, t = total
        lines += [f"| 計 | {a}/{n} | {a / n:.0%} | {c}/{t} | {c / t:.0%} |", ""]
    if skipped:
        lines.append(f"- 読まなかった回（旧い質問文。pool.PROBE_BASELINE_EXCLUDED）: {', '.join(skipped)}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="results/YYYY-MM-DD.csv")
    ap.add_argument("--out", help="Markdown の書き出し先(省略時は画面のみ)")
    a = ap.parse_args(argv)
    text = render(a.paths)
    print(text)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        io.open(a.out, "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
