#!/usr/bin/env python3
"""results/*.csv を集計し、組別の引用率と 2×2 の主効果検定（フィッシャー正確検定）を出す
使い方: python3 summarize.py results/2026-10-27.csv [results/2026-09-17.csv(ビフォー)]

プールは46本（pool.py）。9/22 に除外した E37 agentforce-coworker は、結果CSVに
行があっても常に除く。
鮮度更新の誤り訂正の対象（pool.CORRECTION_SLUGS。2026-09-22 から agentforce-vibes のみ）は、
アフター期間の本文に処置と訂正の両方が乗る。判定は「込み」と「抜き」の両方を必ず出す。

ビフォーとの突き合わせは URL で行う。9/28 の割付で組が変わるので、(id, 組) で
突き合わせるとビフォーが見つからず 0 扱いになる。
"""
import csv, os, sys, collections
from math import comb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import CORRECTION_SLUGS, EXCLUDED, pool_slugs, slug  # noqa: E402


def fisher_one_sided(a,b,c,d):
    # 表 [[a,b],[c,d]]  a=処置群引用あり b=処置群なし c=対照群あり d=対照群なし
    n=a+b+c+d; r1=a+b; c1=a+c
    def p(x): return comb(r1,x)*comb(n-r1,c1-x)/comb(n,c1)
    return sum(p(x) for x in range(a, min(r1,c1)+1))

def load(path):
    """{slug: (組, 1回でも引用されたら1)}"""
    cited=collections.defaultdict(list); group={}; pool=pool_slugs()
    for r in csv.DictReader(open(path,encoding="utf-8")):
        s=slug(r["url"])
        if s in EXCLUDED or s not in pool:   # E37・プール外（pricing 等）は統計に入れない
            continue
        cited[s].append(int(r["cited"])); group[s]=r["group"]
    return {s: (group[s], int(any(v))) for s,v in cited.items()}

def summarize(after, before, exclude=(), label=""):
    groups=collections.defaultdict(list)
    for s,(g,v) in after.items():
        if s in exclude:
            continue
        delta = v - before.get(s,(None,0))[1] if before else v
        groups[g].append((v,delta))
    n=sum(len(x) for x in groups.values())
    print(f"=== {label}（{n}本） ===")
    print("組別 引用率（アフター） / 平均変化（差の差用）")
    for g in sorted(groups):
        vs=[v for v,_ in groups[g]]; ds=[d for _,d in groups[g]]
        print(f"  {g}: {sum(vs)}/{len(vs)} = {sum(vs)/len(vs):.0%}   Δ平均 {sum(ds)/len(ds):+.2f}")
    def cell(g):
        vs=[v for v,_ in groups.get(g,[])]; return sum(vs), len(vs)-sum(vs)
    lead_on=[cell("③リードのみ"),cell("④両方")]; lead_off=[cell("①対照"),cell("②FAQのみ")]
    faq_on=[cell("②FAQのみ"),cell("④両方")];   faq_off=[cell("①対照"),cell("③リードのみ")]
    def main_effect(name,on,off):
        a=on[0][0]+on[1][0]; b=on[0][1]+on[1][1]; c=off[0][0]+off[1][0]; d=off[0][1]+off[1][1]
        pa=a/(a+b) if a+b else 0; pc=c/(c+d) if c+d else 0
        print(f"{name}: あり {a}/{a+b}={pa:.0%}  なし {c}/{c+d}={pc:.0%}  差 {pa-pc:+.0%}  片側p={fisher_one_sided(a,b,c,d):.3f}")
    print("主効果")
    main_effect("結論要約リード", lead_on, lead_off)
    main_effect("FAQブロック化", faq_on, faq_off)
    print()

if __name__ == "__main__":
    after=load(sys.argv[1]); before=load(sys.argv[2]) if len(sys.argv)>2 else None
    names = "・".join(CORRECTION_SLUGS)
    summarize(after, before, (), f"{names} 込み")
    summarize(after, before, set(CORRECTION_SLUGS), f"{names} 抜き")
    print("判定: 差が +25pt 以上 かつ p<0.10 で「効いた」。どちらか欠ければ「この本数では判断できない」。")
    print(f"{names} 込みと抜きで結論が食い違う場合は、鮮度更新の訂正の影響として扱う。")
