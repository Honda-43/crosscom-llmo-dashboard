#!/usr/bin/env python3
"""results/*.csv を集計し、組別の引用率と 2×2 の主効果検定（フィッシャー正確検定）を出す
使い方: python3 summarize.py results/2026-10-27.csv [results/2026-09-17.csv(ビフォー)]
"""
import csv, sys, collections
from math import comb

def fisher_one_sided(a,b,c,d):
    # 表 [[a,b],[c,d]]  a=処置群引用あり b=処置群なし c=対照群あり d=対照群なし
    n=a+b+c+d; r1=a+b; c1=a+c
    def p(x): return comb(r1,x)*comb(n-r1,c1-x)/comb(n,c1)
    return sum(p(x) for x in range(a, min(r1,c1)+1))

def load(path):
    cited=collections.defaultdict(list)
    for r in csv.DictReader(open(path,encoding="utf-8")):
        cited[(r["id"],r["group"])].append(int(r["cited"]))
    # 記事ごとに「1回でも引用された」= 1
    return {k: int(any(v)) for k,v in cited.items()}

after=load(sys.argv[1]); before=load(sys.argv[2]) if len(sys.argv)>2 else None
groups=collections.defaultdict(list)
for (i,g),v in after.items():
    delta = v - before.get((i,g),0) if before else v
    groups[g].append((v,delta))
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
print("\n主効果（24本 vs 24本）")
main_effect("結論要約リード", lead_on, lead_off)
main_effect("FAQブロック化", faq_on, faq_off)
print("\n判定: 差が +25pt 以上 かつ p<0.10 で「効いた」。どちらか欠ければ「この本数では判断できない」。")
