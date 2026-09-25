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
from pool import (CORRECTION_SLUGS, EXCLUDED, LATE_BASELINE_FROM,  # noqa: E402
                  PROBE_BASELINE_EXCLUDED, baseline_start, late_appended_slugs,
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
    """{slug: (組, 期間中に1回でも cited_article=1 なら1)}

    9/15〜16 に逆リンク追記が入った9本は、追記より前(9/16 まで)の観測を使わない
    (pool.baseline_start)。追記そのものが引用されやすさを動かすので、追記前後を
    混ぜるとビフォーの基準値が実際とずれる。
    """
    start, end = span
    cited = collections.defaultdict(list)
    for r in rows:
        if r.get("model") != model or not (start <= str(r.get("date", ""))[:10] <= end):
            continue
        if not counted(r, pool):
            continue
        s = slug(r["target_url"])
        limit = baseline_start(s)
        if limit and str(r.get("date", ""))[:10] < limit:
            continue
        cited[s].append(str(r.get("cited_article", "")).strip() == "1")
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
def tally(after, before, exclude=()):
    """{組: [(アフターの値, 変化), ...]} を作る。``exclude`` の記事は数えない。"""
    groups = collections.defaultdict(list)
    for s, (g, v) in after.items():
        if s in exclude:
            continue
        delta = v - before.get(s, (None, 0))[1] if before else v
        groups[g].append((v, delta))
    return groups


def cells(groups, g):
    vs = [v for v, _ in groups.get(g, [])]
    return sum(vs), len(vs) - sum(vs)


def effect(groups, on_groups, off_groups):
    """主効果。(あり引用, あり本数, なし引用, なし本数, 差, 片側p)。"""
    a = sum(cells(groups, g)[0] for g in on_groups)
    b = sum(cells(groups, g)[1] for g in on_groups)
    c = sum(cells(groups, g)[0] for g in off_groups)
    d = sum(cells(groups, g)[1] for g in off_groups)
    pa = a / (a + b) if a + b else 0
    pc = c / (c + d) if c + d else 0
    return a, a + b, c, c + d, pa - pc, fisher_one_sided(a, b, c, d)


LEAD_ON, LEAD_OFF = ("③リードのみ", "④両方"), ("①対照", "②FAQのみ")
FAQ_ON, FAQ_OFF = ("②FAQのみ", "④両方"), ("①対照", "③リードのみ")


def summarize(after, before, exclude=(), label=""):
    groups = tally(after, before, exclude)
    n = sum(len(x) for x in groups.values())
    print(f"=== {label}（{n}本） ===")
    print("組別 引用率（アフター） / 平均変化（差の差用）")
    for g in sorted(groups):
        vs = [v for v, _ in groups[g]]; ds = [d for _, d in groups[g]]
        print(f"  {g}: {sum(vs)}/{len(vs)} = {sum(vs)/len(vs):.0%}   Δ平均 {sum(ds)/len(ds):+.2f}")
    def line(name, on, off):
        a, an, c, cn, diff, p = effect(groups, on, off)
        print(f"{name}: あり {a}/{an}={a/an if an else 0:.0%}  なし {c}/{cn}={c/cn if cn else 0:.0%}"
              f"  差 {diff:+.0%}  片側p={p:.3f}")
    print("主効果")
    line("結論要約リード", LEAD_ON, LEAD_OFF)
    line("FAQブロック化", FAQ_ON, FAQ_OFF)
    print()


def variants():
    """感度分析の4通り。(見出し, 除く記事) を返す。

    9/15〜16 に逆リンク追記が入った9本と、鮮度更新の訂正2本は、どちらも
    処置以外の理由で本文が変わっている。片方だけ抜いた結果も並べないと、
    結論がどちらの影響で動いたのか分からない。
    """
    late = late_appended_slugs()
    corr = set(CORRECTION_SLUGS)
    return [
        ("両方込み", set()),
        (f"9本抜き（9/15〜16 追記）", set(late)),
        (f"{len(corr)}本抜き（訂正対象）", corr),
        ("両方抜き", set(late) | corr),
    ]


def sensitivity_table(after, before, title=""):
    """4通り（両方込み／9本抜き／2本抜き／両方抜き）を1つの表にする。"""
    rows = []
    for label, exclude in variants():
        groups = tally(after, before, exclude)
        n = sum(len(x) for x in groups.values())
        rates = []
        for g in ("①対照", "②FAQのみ", "③リードのみ", "④両方"):
            hit, miss = cells(groups, g)
            rates.append(f"{hit}/{hit + miss}" if hit + miss else "—")
        _, _, _, _, lead_diff, lead_p = effect(groups, LEAD_ON, LEAD_OFF)
        _, _, _, _, faq_diff, faq_p = effect(groups, FAQ_ON, FAQ_OFF)
        rows.append([label, str(n)] + rates
                    + [f"{lead_diff:+.0%}", f"{lead_p:.3f}",
                       f"{faq_diff:+.0%}", f"{faq_p:.3f}"])
    head = ["感度分析" + (f"（{title.strip()}）" if title.strip() else ""), "本数",
            "①対照", "②FAQのみ", "③リードのみ", "④両方",
            "リード差", "p", "FAQ差", "p"]
    width = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    def row(cells_):
        return "  ".join(c.ljust(w) for c, w in zip(cells_, width)).rstrip()
    print(row(head))
    print("  ".join("-" * w for w in width))
    for r in rows:
        print(row(r))
    print()


def both_ways(after, before, title=""):
    """感度分析の表と、4通りそれぞれの組別の内訳を出す。"""
    sensitivity_table(after, before, title)
    for label, exclude in variants():
        summarize(after, before, exclude, f"{title}{label}")


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
        late = late_appended_slugs()
        if late:
            print(f"9/15〜16 に追記の入った{len(late)}本は {LATE_BASELINE_FROM} 以降の観測だけを使う")
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
    print("感度分析の4通りで結論が食い違う場合は、処置ではなく"
          "「9/15〜16 の追記」か「鮮度更新の訂正」の影響として扱う。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
