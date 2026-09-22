#!/usr/bin/env python3
"""summarize.py｜2×2 の判定: 組別の引用率と主効果検定（フィッシャー正確検定）。

**判定は llm_experiment のみ**（2026-09-22 決定）。既定はシートの llm_experiment を読む。

使い方:
  # 判定（llm_experiment。シートから読む）
  python3 summarize.py --before 2026-09-15:2026-09-28 --after 2026-10-08:2026-10-27
  # シートを CSV に書き出したものを使う
  python3 summarize.py --before ... --after ... --csv llm_experiment.csv
  # 引用プローブの結果（参考。実験期間中は不使用）
  python3 summarize.py --probe results/<アフター>.csv [results/<ビフォー>.csv]

数える記事
- プール46本（pool.py）だけ。llm_experiment の experiment_flag=watch の行（E37 など、観測は
  続けるが統計に入れない記事）と、プール外の記事の行は自動で除く
- 欠測の行（error あり）は数えない。記事ごとに「期間中に1回でも cited_article=1」を 1 とする
- 組は allocation_v1.csv（9/28 の割付）から引く。9/28 の割付で組が変わるので、
  ビフォーとアフターは記事（URL）で突き合わせる

鮮度更新の誤り訂正の対象（pool.CORRECTION_SLUGS。2026-09-23 から agentforce-vibes・
agentforce-features の2本）は、アフター期間の本文に処置と訂正の両方が乗る。
判定は「2本込み」と「2本抜き」の両方を必ず出す。
"""
import argparse
import collections
import csv
import io
import os
import sys
from math import comb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import (CORRECTION_SLUGS, EXCLUDED, PROBE_BASELINE_EXCLUDED,  # noqa: E402
                  load_allocation, pool_slugs, slug)

WATCH_FLAG = "watch"
MODELS = ("gemini", "claude")


def fisher_one_sided(a, b, c, d):
    # 表 [[a,b],[c,d]]  a=処置群引用あり b=処置群なし c=対照群あり d=対照群なし
    n = a + b + c + d; r1 = a + b; c1 = a + c
    def p(x): return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    return sum(p(x) for x in range(a, min(r1, c1) + 1))


# --------------------------------------------------------------------------
# llm_experiment（判定）
# --------------------------------------------------------------------------
def read_llm_experiment(csv_path=None):
    """llm_experiment の行。csv_path があればそれを、無ければシートを読む。"""
    if csv_path:
        with io.open(csv_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sid = io.open(os.path.join(root, "credentials", "spreadsheet_id.txt"), encoding="utf-8").read().strip()
    creds = Credentials.from_service_account_file(
        os.path.join(root, "credentials", "service_account.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    values = build("sheets", "v4", credentials=creds).spreadsheets().values().get(
        spreadsheetId=sid, range="'llm_experiment'!A1:ZZ50000").execute().get("values", [])
    head = values[0]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in values[1:]]


def counted(row, pool):
    """判定に数える行か。watch・プール外・欠測は数えない。"""
    s = slug(row.get("target_url", ""))
    return (str(row.get("experiment_flag", "")).strip() != WATCH_FLAG
            and s in pool and s not in EXCLUDED
            and not str(row.get("error", "")).strip())


def period(rows, span, model, groups, pool):
    """{slug: (組, 期間中に1回でも cited_article=1 なら1)}"""
    start, end = span
    cited = collections.defaultdict(list)
    for r in rows:
        if r.get("model") != model or not (start <= str(r.get("date", ""))[:10] <= end):
            continue
        if not counted(r, pool):
            continue
        cited[slug(r["target_url"])].append(str(r.get("cited_article", "")).strip() == "1")
    return {s: (groups.get(s, "（割付なし）"), int(any(v))) for s, v in cited.items()}


# --------------------------------------------------------------------------
# 引用プローブ（参考。実験期間中は不使用）
# --------------------------------------------------------------------------
def load_probe(path):
    """{slug: (組, 1回でも引用されたら1)}"""
    cited = collections.defaultdict(list); group = {}; pool = pool_slugs()
    for r in csv.DictReader(open(path, encoding="utf-8")):
        s = slug(r["url"])
        if s in EXCLUDED or s not in pool:   # E37・プール外（pricing 等）は統計に入れない
            continue
        cited[s].append(int(r["cited"])); group[s] = r["group"]
    return {s: (group[s], int(any(v))) for s, v in cited.items()}


# --------------------------------------------------------------------------
# 集計と検定（共通）
# --------------------------------------------------------------------------
def summarize(after, before, exclude=(), label=""):
    groups = collections.defaultdict(list)
    for s, (g, v) in after.items():
        if s in exclude:
            continue
        delta = v - before.get(s, (None, 0))[1] if before else v
        groups[g].append((v, delta))
    n = sum(len(x) for x in groups.values())
    print(f"=== {label}（{n}本） ===")
    print("組別 引用率（アフター） / 平均変化（差の差用）")
    for g in sorted(groups):
        vs = [v for v, _ in groups[g]]; ds = [d for _, d in groups[g]]
        print(f"  {g}: {sum(vs)}/{len(vs)} = {sum(vs)/len(vs):.0%}   Δ平均 {sum(ds)/len(ds):+.2f}")
    def cell(g):
        vs = [v for v, _ in groups.get(g, [])]; return sum(vs), len(vs) - sum(vs)
    lead_on = [cell("③リードのみ"), cell("④両方")]; lead_off = [cell("①対照"), cell("②FAQのみ")]
    faq_on = [cell("②FAQのみ"), cell("④両方")];   faq_off = [cell("①対照"), cell("③リードのみ")]
    def main_effect(name, on, off):
        a = on[0][0] + on[1][0]; b = on[0][1] + on[1][1]; c = off[0][0] + off[1][0]; d = off[0][1] + off[1][1]
        pa = a / (a + b) if a + b else 0; pc = c / (c + d) if c + d else 0
        print(f"{name}: あり {a}/{a+b}={pa:.0%}  なし {c}/{c+d}={pc:.0%}  差 {pa-pc:+.0%}  片側p={fisher_one_sided(a,b,c,d):.3f}")
    print("主効果")
    main_effect("結論要約リード", lead_on, lead_off)
    main_effect("FAQブロック化", faq_on, faq_off)
    print()


def both_ways(after, before, title=""):
    """訂正対象（CORRECTION_SLUGS）込み／抜きの両方を出す。"""
    k = len(CORRECTION_SLUGS)
    names = "・".join(CORRECTION_SLUGS)
    summarize(after, before, (), f"{title}{k}本込み（{names} を含む）")
    summarize(after, before, set(CORRECTION_SLUGS), f"{title}{k}本抜き（{names} を除く）")


def _span(text):
    start, _, end = text.partition(":")
    return start, end or start


def main(argv=None):
    ap = argparse.ArgumentParser(description="2×2 の判定（llm_experiment）")
    ap.add_argument("--before", help="ビフォー期間 YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--after", help="アフター期間 YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--csv", help="llm_experiment を書き出した CSV（省略時はシートを読む）")
    ap.add_argument("--model", choices=MODELS, help="1モデルだけ出す（省略時は両方）")
    ap.add_argument("--probe", nargs="+", metavar="CSV",
                    help="引用プローブの結果で集計する（参考。アフター [ビフォー]）")
    a = ap.parse_args(argv)

    if a.probe:
        if len(a.probe) > 1:
            stem = os.path.splitext(os.path.basename(a.probe[1]))[0]
            if stem in PROBE_BASELINE_EXCLUDED:
                sys.exit(f"{a.probe[1]} はビフォーに使わない(質問文が旧い。pool.PROBE_BASELINE_EXCLUDED)")
        after = load_probe(a.probe[0])
        before = load_probe(a.probe[1]) if len(a.probe) > 1 else None
        print("※ 引用プローブは参考。判定は llm_experiment のみ\n")
        both_ways(after, before)
    else:
        if not (a.before and a.after):
            ap.error("--before と --after を指定する（または --probe）")
        groups = load_allocation()
        if not groups:
            sys.exit("allocation_v1.csv が無い（9/28 の割付の前）。組が決まってから判定する")
        rows = read_llm_experiment(a.csv)
        pool = pool_slugs()
        watch = sum(1 for r in rows if str(r.get("experiment_flag", "")).strip() == WATCH_FLAG)
        print(f"llm_experiment {len(rows)}行（watch {watch}行とプール外・欠測は数えない）\n")
        for model in ([a.model] if a.model else MODELS):
            after = period(rows, _span(a.after), model, groups, pool)
            before = period(rows, _span(a.before), model, groups, pool)
            missing = sorted(set(after) - set(before))
            print(f"##### {model}（アフター {a.after} / ビフォー {a.before}）")
            if missing:
                print(f"ビフォーに観測の無い記事 {len(missing)}本（ビフォーは0として扱う）: {', '.join(missing)}")
            both_ways(after, before, f"{model} ")
    print("判定: 差が +25pt 以上 かつ p<0.10 で「効いた」。どちらか欠ければ「この本数では判断できない」。")
    print(f"{len(CORRECTION_SLUGS)}本込みと{len(CORRECTION_SLUGS)}本抜きで結論が食い違う場合は、"
          "鮮度更新の訂正の影響として扱う。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
