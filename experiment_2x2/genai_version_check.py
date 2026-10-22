#!/usr/bin/env python3
"""genai_version_check.py｜Gemini のライブラリ(google-genai)の版が変わった日の前後で、引用の取り出しに段差が無いか(2026-10-22).

google-genai は 9/15〜10/22 に10回上がった(GitHub Actions の実験ジョブの Install dependencies のログで確認・README)。
同じ日は4組とも同じ版なので差の差では打ち消されるが、「返事から引用URLを取り出す部分」が変われば全体の水準がずれる。

**組ごとの数字は出さない。46本をまとめた全体だけ。cited_article・mentioned 系の列は読まない**(実験の結果にあたるため、
全体でも 11/2 まで見ない)。raw(data/raw/experiment/<日付>/*_gemini.json)のうち次の列だけを読む:
  cited_urls(Gemini の grounding_chunks から取り出した引用元URL。転送URLのまま)・cited_domains(転送先を解決した後の引用元)・
  error・experiment_flag・target_url(プール46本かどうか)・timestamp(どの版で取ったか)

日ごとの指標(答えの取れたプール46本の行):
  ① 引用元(cited_domains)が1つ以上ある行の割合 ② 1行あたりの引用元(cited_domains)の数の平均
  ③ grounding の情報が空の行の割合(cited_urls が空。grounding の生データは raw に残していないので、取り出した結果で見る)

段差の見方:版が変わった日の前3日・後3日(観測のある日。3日でほぼ46本を1巡する)の行をまとめて差を取り、
版が変わっていない日の境目で同じ差を取ったときの分布(ふだんの揺れ)と比べる。ふだんの揺れの最大より大きければ「段差あり」。
差は記事の違いをならして取る(各行の値から、その記事の全期間の平均を引く)。引用元が出ない行は一部の記事に偏っていて
(46本のうち12本)、それらが固まった日は全体の率が動くため(10/21 はならす前の差だけが揺れを超えた。2026-10-22 確認)。

使い方: python experiment_2x2/genai_version_check.py [--out output/reports/genai_version_check_20261022.csv]
表(日ごと・版の変わり目ごと)はファイルに書き、画面には段差の有無と日付だけを出す。
"""
import argparse
import csv
import datetime as dt
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import pool_slugs, slug  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RAW_DIR = os.path.join(ROOT, "data", "raw", "experiment")
JST = dt.timezone(dt.timedelta(hours=9))
WINDOW_DAYS = 3

# google-genai の版が変わった日(その日の実験ジョブから新しい版。実験ジョブの Install dependencies のログで確認)
VERSION_FROM = [
    ("2026-09-15", "2.23.0"), ("2026-09-17", "2.24.0"), ("2026-09-23", "2.25.0"), ("2026-10-01", "2.26.0"),
    ("2026-10-02", "2.27.0"), ("2026-10-03", "2.28.0"), ("2026-10-08", "2.29.0"), ("2026-10-13", "2.30.0"),
    ("2026-10-14", "2.30.1"), ("2026-10-15", "2.31.0"), ("2026-10-21", "2.32.0"),
]
METRICS = ("has_citation", "domains_per_row", "empty_grounding")
METRIC_LABELS = {"has_citation": "引用元（cited_domains）が1つ以上ある行の割合",
                 "domains_per_row": "1行あたりの引用元（cited_domains）の数の平均",
                 "empty_grounding": "grounding の情報（引用の元データ）が空の行の割合"}
# 読んでよい列(これ以外は読まない)
READ_KEYS = ("cited_urls", "cited_domains", "error", "experiment_flag", "target_url", "timestamp", "date")


def version_on(day):
    """その日(JST)の実験ジョブで入っていた版。"""
    out = None
    for start, ver in VERSION_FROM:
        if day >= start:
            out = ver
    return out


def run_day(rec):
    """観測した時刻の日付(JST)。読めなければ観測日の列。取り直しが後日の場合はその日の版になる。"""
    raw = str(rec.get("timestamp") or "")
    try:
        t = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(JST).date().isoformat()
    except ValueError:
        return str(rec.get("date", ""))[:10]


def load_rows(raw_dir=RAW_DIR, pool=None):
    """答えの取れたプール46本の Gemini の行(読む列だけ)。"""
    pool = pool_slugs() if pool is None else pool
    rows = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*", "*_gemini.json"))):
        with io.open(path, encoding="utf-8") as f:
            full = json.load(f)
        rec = {k: full.get(k) for k in READ_KEYS}
        del full
        if rec["error"] or str(rec.get("experiment_flag") or "") == "watch" or slug(rec.get("target_url") or "") not in pool:
            continue
        day = run_day(rec)
        rows.append({"day": day, "version": version_on(day), "article": slug(rec.get("target_url") or ""),
                     "has_citation": int(bool(rec.get("cited_domains"))),
                     "domains_per_row": len(rec.get("cited_domains") or []),
                     "empty_grounding": int(not rec.get("cited_urls"))})
    return rows


def adjust_for_articles(rows):
    """記事の違いをならす:各指標から、その記事の全期間の平均を引いた値(adj_*)を足す。
    日によって観測する記事が違い(46本を約3日で1巡)、引用元が出にくい記事が固まった日は全体の率が動くため。"""
    by = {}
    for r in rows:
        by.setdefault(r["article"], []).append(r)
    for part in by.values():
        for m in METRICS:
            avg = _mean(part, m)
            for r in part:
                r[f"adj_{m}"] = r[m] - avg
    return rows


def _mean(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else None


def daily(rows):
    days = sorted({r["day"] for r in rows})
    out = []
    for d in days:
        part = [r for r in rows if r["day"] == d]
        out.append({"day": d, "version": part[0]["version"], "rows": len(part),
                    **{m: round(_mean(part, m), 4) for m in METRICS}})
    return out


def boundary_diffs(rows, days, i, window=WINDOW_DAYS):
    """days[i] の前 window 日・days[i] から window 日の行の差(後 − 前)。"""
    before = set(days[max(0, i - window):i])
    after = set(days[i:i + window])
    b = [r for r in rows if r["day"] in before]
    a = [r for r in rows if r["day"] in after]
    keys = list(METRICS) + [f"adj_{m}" for m in METRICS]
    return {k: _mean(a, k) - _mean(b, k) for k in keys}, len(b), len(a)


def steps(rows, window=WINDOW_DAYS):
    """版が変わった日ごとの差と、ふだんの揺れ(版が変わっていない日の境目の差の絶対値の最大)。
    段差の判定は記事の違いをならした差(adj_*)で行う。ならす前の差(raw)は表に残す(顔ぶれで動くので判定には使わない)。"""
    adjust_for_articles(rows)
    days = sorted({r["day"] for r in rows})
    change_days = {d for d, _ in VERSION_FROM[1:]}
    keys = list(METRICS) + [f"adj_{m}" for m in METRICS]
    normal = {k: [] for k in keys}
    for i in range(window, len(days) - window + 1):
        if days[i] in change_days:
            continue
        diff, _, _ = boundary_diffs(rows, days, i, window)
        for k in keys:
            normal[k].append(abs(diff[k]))
    limit = {k: max(normal[k]) for k in keys}
    out = []
    for d, ver in VERSION_FROM[1:]:
        if d not in days:
            continue
        i = days.index(d)
        diff, nb, na = boundary_diffs(rows, days, i, window)
        flags = [m for m in METRICS if abs(diff[f"adj_{m}"]) > limit[f"adj_{m}"]]
        raw_flags = [m for m in METRICS if abs(diff[m]) > limit[m]]
        out.append({"day": d, "version": f"{version_on(days[i - 1]) if i else ''}→{ver}", "rows_before": nb,
                    "rows_after": na, **{f"diff_{k}": round(diff[k], 4) for k in keys},
                    **{f"normal_max_{k}": round(limit[k], 4) for k in keys},
                    "step_raw": "・".join(raw_flags), "step": "・".join(flags)})
    return out


def version_table(rows):
    out = []
    for start, ver in VERSION_FROM:
        part = [r for r in rows if r["version"] == ver]
        days = sorted({r["day"] for r in part})
        out.append({"version": ver, "from": start, "days": len(days), "rows": len(part),
                    "first_day": days[0] if days else "", "last_day": days[-1] if days else ""})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "reports", "genai_version_check_20261022.csv"))
    a = ap.parse_args(argv)
    rows = load_rows()
    table, st, vt = daily(rows), steps(rows), version_table(rows)
    with io.open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write("# google-genai の版の変化と引用の取り出し（2026-10-22・genai_version_check.py）。46本をまとめた全体のみ。"
                "cited_article・mentioned 系は読んでいない\n")
        for title, part in (("版ごとの観測", vt), ("日ごと", table), ("版が変わった日の前後（前3日・後3日）", st)):
            f.write(f"# {title}\n")
            w = csv.DictWriter(f, list(part[0]))
            w.writeheader()
            w.writerows(part)
    print("版ごとの観測：" + "・".join(f"{v['version']} {v['days']}日{v['rows']}本" for v in vt))
    raw = [s["day"] for s in st if s["step_raw"]]
    if raw:
        print("ならす前の差で揺れを超えた日：" + "・".join(raw) + "（記事の顔ぶれの違い。記事の違いをならすと下のとおり）")
    flagged = [s for s in st if s["step"]]
    if flagged:
        print("段差あり：" + "・".join(f"{s['day']}（{s['version']}：{'・'.join(METRIC_LABELS[m] for m in s['step'].split('・'))}）"
                                     for s in flagged))
    else:
        print("段差なし（版が変わった10日とも、前後の差はふだんの日の境目の揺れの範囲）")
    print(f"表：{os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
