#!/usr/bin/env python3
"""
LLMO 引用観測プローブ（自前計測）
- 入力: config/prompts_experiment.csv（プール46本。列: id,layer,url,prompt）
         組は experiment_2x2/allocation_v1.csv（9/28 の割付。無ければ空欄）
  2026-09-22 から targets.csv（編集禁止リスト50本）は観測に使わない。
  質問文は prompts_experiment.csv の prompt 列（dashboard の実験と同じ文）。
- 各記事の質問を AI（Claude / Perplexity / Gemini）に投げ、
  回答の引用URLに当該記事URLが含まれるかを記録する
- 出力: results/YYYY-MM-DD.csv （列: run_date,id,url,group,model,run,cited,cited_urls）

必要な環境変数（使うモデルだけ設定すればよい）
  ANTHROPIC_API_KEY      Claude（web_search ツール使用）
  PERPLEXITY_API_KEY     Perplexity sonar
  GEMINI_API_KEY         Gemini（Google検索グラウンディング）※任意
実行:  python3 llmo_probe.py --runs 3
"""
import argparse, csv, datetime, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import load_allocation, load_pool  # noqa: E402

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
PPLX_MODEL   = os.environ.get("PPLX_MODEL", "sonar")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
SITE_DOMAIN  = "cross-com.jp"

def norm(u: str) -> str:
    u = u.strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")

def post_json(url, headers, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

URL_RE = re.compile(r"https?://[^\s\"'<>\\)\]]+")

def ask_claude(q):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    body = {"model": CLAUDE_MODEL, "max_tokens": 1500,
            "messages": [{"role": "user", "content": q}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]}
    data = post_json("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
    return set(URL_RE.findall(json.dumps(data, ensure_ascii=False)))

def ask_perplexity(q):
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key: return None
    body = {"model": PPLX_MODEL, "messages": [{"role": "user", "content": q}]}
    data = post_json("https://api.perplexity.ai/chat/completions",
                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body)
    urls = set(data.get("citations", []) or [])
    for r in (data.get("search_results") or []):
        if r.get("url"): urls.add(r["url"])
    return urls

def ask_gemini(q):
    key = os.environ.get("GEMINI_API_KEY")
    if not key: return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": q}]}], "tools": [{"google_search": {}}]}
    data = post_json(url, {"Content-Type": "application/json"}, body)
    urls = set()
    for cand in data.get("candidates", []):
        gm = cand.get("groundingMetadata", {}) or {}
        for ch in gm.get("groundingChunks", []) or []:
            w = ch.get("web", {}) or {}
            # Gemini はリダイレクトURLを返すことがある。title にドメインが入る場合があるので両方見る
            if w.get("uri"): urls.add(w["uri"])
            if w.get("title"): urls.add("https://" + w["title"])
    return urls

MODELS = {"claude": ask_claude, "perplexity": ask_perplexity, "gemini": ask_gemini}

def load_targets():
    """観測の対象。プール46本に、割付の組を足す（割付前は空欄）。"""
    groups = load_allocation()
    return [{"id": a["id"], "url": a["url"], "group": groups.get(a["slug"], ""),
             "query": a["prompt"]} for a in load_pool()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="同一クエリの反復回数（揺れを均す）")
    # 既定に gemini を入れない(2026-09-22)。dashboard の日次・月次・実験と同じ
    # GEMINI_API_KEY(無料枠 20回/日)を読むので、46本×3回=138回で1日の枠が尽きる。
    # これまでの観測(results/2026-09-17.csv)は claude のみで、枠は消費していない。
    ap.add_argument("--models", default="claude,perplexity")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    os.makedirs("results", exist_ok=True)
    out = f"results/{today}.csv"
    rows = load_targets()
    models = [m.strip() for m in a.models.split(",")]
    if "gemini" in models:
        print("[warn] gemini は dashboard と同じ GEMINI_API_KEY の無料枠(20回/日)を使います。"
              f"{len(rows)}本×{a.runs}回で枠が尽き、同じ日の日次・実験の観測が 429 になります",
              file=sys.stderr)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["run_date","id","url","group","model","run","cited","site_cited","cited_urls"])
        for r in rows:
            q = (r.get("query") or "").strip()
            if not q:
                print(f"[skip] {r['id']} query 未設定", file=sys.stderr); continue
            target = norm(r["url"])
            for m in models:
                fn = MODELS.get(m)
                if not fn: continue
                for k in range(1, a.runs+1):
                    try:
                        urls = fn(q)
                    except Exception as e:
                        print(f"[err] {r['id']} {m} run{k}: {e}", file=sys.stderr); urls = None
                    if urls is None: continue
                    n = {norm(u) for u in urls}
                    cited = int(target in n)
                    site = int(any(SITE_DOMAIN in u for u in n))
                    w.writerow([today, r["id"], r["url"], r.get("group",""), m, k, cited, site, " ".join(sorted(u for u in urls if SITE_DOMAIN in u))])
                    f.flush(); time.sleep(a.sleep)
    print("wrote", out)

if __name__ == "__main__":
    main()
