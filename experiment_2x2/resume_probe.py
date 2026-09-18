# -*- coding: utf-8 -*-
"""resume_probe.py｜中断した観測の続きだけを取り、既存の行に足す（2026-09-18 新設）。

llmo_probe.py は results/YYYY-MM-DD.csv を 'w' で開くため、
そのまま再実行すると**取れている行を消してしまう**。
ここは (id, model, run) の欠けだけを取り、同じファイルへ追記する。
run_date は元の観測日のまま（ビフォー観測は1点として扱うため）。
"""
import argparse, csv, io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llmo_probe import MODELS, norm, SITE_DOMAIN

ap = argparse.ArgumentParser()
ap.add_argument("--date", required=True, help="続きを足す results/<date>.csv")
ap.add_argument("--targets", default="targets.csv")
ap.add_argument("--runs", type=int, default=3)
ap.add_argument("--models", default="claude")
ap.add_argument("--sleep", type=float, default=1.0)
ap.add_argument("--retries", type=int, default=3, help="タイムアウト時の再試行回数")
a = ap.parse_args()

out = f"results/{a.date}.csv"
rows = list(csv.DictReader(io.open(a.targets, encoding="utf-8")))
have = set()
if os.path.exists(out):
    for r in csv.DictReader(io.open(out, encoding="utf-8")):
        have.add((r["id"], r["model"], r["run"]))
print(f"既存 {len(have)} 行 / 目標 {len(rows) * a.runs * len(a.models.split(','))} 行")

models = [m.strip() for m in a.models.split(",")]
added = 0
with io.open(out, "a", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    for r in rows:
        q = (r.get("query") or "").strip()
        if not q:
            print(f"[skip] {r['id']} query 未設定", file=sys.stderr); continue
        target = norm(r["url"])
        for m in models:
            fn = MODELS.get(m)
            if not fn: continue
            for k in range(1, a.runs + 1):
                if (r["id"], m, str(k)) in have: continue
                urls = None
                for attempt in range(1, a.retries + 1):
                    try:
                        urls = fn(q); break
                    except Exception as e:                       # noqa: BLE001
                        print(f"[err] {r['id']} {m} run{k} 試行{attempt}: {e}", file=sys.stderr)
                        time.sleep(5 * attempt)
                if urls is None:
                    print(f"[give up] {r['id']} {m} run{k}", file=sys.stderr); continue
                n = {norm(u) for u in urls}
                cited = int(target in n)
                site = int(any(SITE_DOMAIN in u for u in n))
                w.writerow([a.date, r["id"], r["url"], r.get("group", ""), m, k, cited, site,
                            " ".join(sorted(u for u in urls if SITE_DOMAIN in u))])
                f.flush(); added += 1
                print(f"  + {r['id']} run{k} cited={cited} site={site}", flush=True)
                time.sleep(a.sleep)
print(f"追記 {added} 行 → {out}")
