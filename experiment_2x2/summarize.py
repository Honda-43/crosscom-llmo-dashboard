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
- 欠測の行（error あり）は数えない。**Gemini** は記事ごとに「期間中に1回でも cited_article=1」を 1 とする
- **Claude は記事ごとの率**（cited_article=1 の回数 ÷ 観測できた回数）で比べる（2026-10-03・本田さん決定）。
  Claude の観測は 2026-10-05 から週2回→週1回（月曜のみ）になり、ビフォー（週2回）とアフター（週1回）で
  回数が違う。「1回でも」の二値は回数が多いほど1になりやすく、回数の差が処置の差に見えるため。
  変化（差の差）も率の差で出す。率は0/1ではないのでフィッシャー検定は使わない（再ランダム化検定は率の平均の差で行う）
- 組は allocation_v1.csv（9/28 の割付）から引く。9/28 の割付で組が変わるので、
  ビフォーとアフターは記事（URL）で突き合わせる

鮮度更新の誤り訂正が入る記事は、アフター期間の本文に処置と訂正の両方が乗る。
2026-09-26 に vibes の訂正は見送りになり、9/29〜30 に訂正するのは agentforce-features の
1文だけになった（pool.APPLIED_CORRECTION_SLUGS）。判定は「込み」と「features 抜き」の
両方を必ず出す。くじ引きの条件 f は2本のまま（pool.CORRECTION_SLUGS）。
"""
import argparse
import collections
import csv
import io
import os
import re
import sys
from math import comb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import interventions  # noqa: E402
import pillar  # noqa: E402
import rerandomize  # noqa: E402
from pool import GROUP_BLIND_UNTIL  # noqa: E402
from pool import LINK_LOSS_IDS, LINK_LOSS_SCOPE, LINK_LOSS_SLUGS  # noqa: E402
from pool import (MISINFO_FIX_FAQ_ANSWERS, MISINFO_FIX_IDS, MISINFO_FIX_PARAGRAPHS,  # noqa: E402
                  MISINFO_FIX_REST_CHANGES, MISINFO_FIX_SCOPE, MISINFO_FIX_SLUGS)
from pool import (FACT_CORRECTION_IMBALANCE, fact_correction_first_at,  # noqa: E402
                  fact_correction_slugs, load_fact_corrections)
from pool import (APPLIED_CORRECTION_SLUGS, EXCLUDED,  # noqa: E402
                  LATE_BASELINE_FROM, PROBE_BASELINE_EXCLUDED, baseline_start,
                  late_appended_slugs, load_allocation, multi_paragraph_slugs,
                  pool_slugs, slug)

WATCH_FLAG = "watch"
MODELS = ("gemini", "claude")
# 2026-10-06：Claude 観測を計画的に停止（費用ゼロ方針・本田さん決定）。アフター期間（10/6〜）の Claude は0本のため、
# Claude は判定・感度分析・補助分析の対象から外す（欠測を0＝引用なしとして数えない）。主指標（Gemini）は不変。
# 停止日は config/claude_budget.yaml の planned_stop_from（settings.claude_planned_stop_from）
GENERALIZATION_NOTE = ("結論は Gemini（検索接続あり）での結果。Claude ではアフター期間の観測がないため、"
                       "他のAIへの一般化は確認できていない")


def claude_stop_date():
    from settings import claude_planned_stop_from
    return claude_planned_stop_from()


def model_excluded(model, after_span):
    """判定から外すモデルか（Claude を止めた日がアフター期間の終わりまでにあれば外す）。"""
    stop = claude_stop_date()
    return model == "claude" and bool(stop) and after_span[1] >= stop


def excluded_line(model):
    return (f"Claude：アフター期間の観測なし（{claude_stop_date()} に計画的停止・費用ゼロ方針）。判定対象外")
# 記事ごとの値を「観測1回あたりの率」にするモデル（2026-10-03）。ほかは「1回でも引用されたか」の 0/1
RATE_MODELS = ("claude",)

# 判定時の補助分析(Google 順位の上位・下位で処置の効き方が違うか)に使う GSC の指標。
# **v2 に固定する**(2026-10-01)。# 付きURL(目次アンカー)は本体に寄せ、表示回数・順位は
# 本体の行のみ、クリックは合計(experiment_2x2/gsc_pages_v2.py)。9/14 版(seo-agent の
# experiment47_gsc_pages_20260914.csv)は表示回数を合算・順位を加重平均していたため使わない。
# GSC は判定そのもの(cited_article)には使わない。
GSC_PAGES_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output",
                             "articles", "experiment46_gsc_pages_20260914_v2.csv")


def read_gsc_pages(path=None):
    """{記事ID: {'position': float|None, 'impressions': int|None, 'clicks': int|None, 'note': str}}。

    表示回数・順位が「データなし」(本体の行が無い記事)は None。上位・下位の層別では外す。
    """
    out = {}
    with io.open(path or GSC_PAGES_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            num = lambda v, cast: cast(v) if str(v).strip() else None  # noqa: E731
            out[r["id"]] = {"position": num(r["平均掲載順位"], float),
                            "impressions": num(r["表示回数"], int),
                            "clicks": num(r["クリック数"], int), "note": r["備考"]}
    return out


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


def observed_at_jst(row):
    """観測の時刻（JST の datetime）。timestamp 列（UTC の ISO・末尾 Z）から。読めなければ None。"""
    import datetime as _dt
    raw = str(row.get("timestamp", "") or "").strip()
    if not raw:
        return None
    try:
        t = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is not None:
        t = t.astimezone(_dt.timezone(_dt.timedelta(hours=9))).replace(tzinfo=None)
    return t


def before_cut(row, until):
    """観測が ``until``（JST の datetime）より前か。時刻が読めない行は日付で見て、訂正の日の観測は入れない（保守的）。"""
    if until is None:
        return True
    t = observed_at_jst(row)
    if t is not None:
        return t < until
    return str(row.get("date", ""))[:10] < until.date().isoformat()


def period(rows, span, model, groups, pool, rate=None, until=None):
    """{slug: (組, 値)}。値は Gemini が「期間中に1回でも cited_article=1 なら1」、
    Claude（RATE_MODELS）が「cited_article=1 の回数 ÷ 観測できた回数」の率（0〜1 の小数）。
    ``rate`` を渡すとモデルに関係なくどちらかに決める。
    ``until``（JST の datetime）を渡すと、その時刻より前の観測だけを使う（感度分析 B「事実訂正前で打ち切り」）。

    9/15〜16 に逆リンク追記が入った9本は、追記より前(9/16 まで)の観測を使わない
    (pool.baseline_start)。追記そのものが引用されやすさを動かすので、追記前後を
    混ぜるとビフォーの基準値が実際とずれる。
    """
    start, end = span
    cited = collections.defaultdict(list)
    for r in rows:
        if r.get("model") != model or not (start <= str(r.get("date", ""))[:10] <= end):
            continue
        if not counted(r, pool) or not before_cut(r, until):
            continue
        s = slug(r["target_url"])
        limit = baseline_start(s)
        if limit and str(r.get("date", ""))[:10] < limit:
            continue
        cited[s].append(str(r.get("cited_article", "")).strip() == "1")
    rate = model in RATE_MODELS if rate is None else rate
    if rate:
        return {s: (groups.get(s, "（割付なし）"), sum(v) / len(v)) for s, v in cited.items()}
    return {s: (groups.get(s, "（割付なし）"), int(any(v))) for s, v in cited.items()}


# --------------------------------------------------------------------------
# 引用プローブ（参考。実験期間中は不使用）
# --------------------------------------------------------------------------
def load_probe(path):
    """{slug: (組, 1回でも引用されたら1)}"""
    # 2026-09-30：組は結果CSVの group 列ではなく割付表（allocation_v1）から読む（probe_summary と同じ）。
    # 　9/17 の結果CSVは割付前（v0）の組を持っており、46本中37本が v1 と違う。group 列を使うと
    # 　tally・effect・検定が v0 の組で数えられ、同じ出力の rerandomization_p（v1）と混ざる
    cited = collections.defaultdict(list); pool = pool_slugs(); groups = load_allocation()
    for r in csv.DictReader(open(path, encoding="utf-8")):
        s = slug(r["url"])
        if s in EXCLUDED or s not in pool:   # E37・プール外（pricing 等）は統計に入れない
            continue
        cited[s].append(int(r["cited"]))
    return {s: (groups.get(s, "（割付なし）"), int(any(v))) for s, v in cited.items()}


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


def is_rate(groups):
    """記事の値が率（0/1 でない小数）か。Claude の判定（RATE_MODELS）がこれ。"""
    return any(isinstance(v, float) for xs in groups.values() for v, _ in xs)


def share(hit, n, rate=False):
    """本数の表示。0/1 なら「引用/本数」、率なら「平均の率（本数）」。"""
    if not n:
        return "—"
    return f"平均{hit / n:.0%}（{n}本）" if rate else f"{hit}/{n}"


def pval(p):
    return "—（率のため対象外）" if p is None else f"{p:.3f}"


def effect(groups, on_groups, off_groups):
    """主効果。(あり引用, あり本数, なし引用, なし本数, 差, 片側p)。

    率（Claude）のときは「引用」が率の合計、差は記事ごとの率の平均の差。フィッシャー検定は
    0/1 の表にしか使えないので p は None。
    """
    a = sum(cells(groups, g)[0] for g in on_groups)
    b = sum(cells(groups, g)[1] for g in on_groups)
    c = sum(cells(groups, g)[0] for g in off_groups)
    d = sum(cells(groups, g)[1] for g in off_groups)
    pa = a / (a + b) if a + b else 0
    pc = c / (c + d) if c + d else 0
    p = None if is_rate(groups) else fisher_one_sided(a, b, c, d)
    return a, a + b, c, c + d, pa - pc, p


LEAD_ON, LEAD_OFF = ("③リードのみ", "④両方"), ("①対照", "②FAQのみ")
FAQ_ON, FAQ_OFF = ("②FAQのみ", "④両方"), ("①対照", "③リードのみ")


def summarize(after, before, exclude=(), label=""):
    groups = tally(after, before, exclude)
    rate = is_rate(groups)
    n = sum(len(x) for x in groups.values())
    print(f"=== {label}（{n}本） ===")
    if rate:
        print("組別 記事ごとの引用率の平均（アフター。観測1回あたりの率） / 率の平均変化（差の差用）")
    else:
        print("組別 引用率（アフター） / 平均変化（差の差用）")
    for g in sorted(groups):
        vs = [v for v, _ in groups[g]]; ds = [d for _, d in groups[g]]
        head = (f"平均 {sum(vs)/len(vs):.0%}（{len(vs)}本）" if rate
                else f"{sum(vs)}/{len(vs)} = {sum(vs)/len(vs):.0%}")
        print(f"  {g}: {head}   Δ平均 {sum(ds)/len(ds):+.2f}")
    def line(name, on, off):
        a, an, c, cn, diff, p = effect(groups, on, off)
        if rate:
            print(f"{name}: あり 平均{a/an if an else 0:.0%}（{an}本）  なし 平均{c/cn if cn else 0:.0%}（{cn}本）"
                  f"  差 {diff:+.0%}  片側p(フィッシャー)={pval(p)}")
            return
        print(f"{name}: あり {a}/{an}={a/an if an else 0:.0%}  なし {c}/{cn}={c/cn if cn else 0:.0%}"
              f"  差 {diff:+.0%}  片側p={p:.3f}")
    print("主効果")
    line("結論要約リード", LEAD_ON, LEAD_OFF)
    line("FAQブロック化", FAQ_ON, FAQ_OFF)
    rr = randomization(after, exclude)
    if tested(rr):
        print(f"再ランダム化検定（同じ条件を満たす割付の中で。**判定の本線**。使用した割付数：{rr['n']:,}）"
              f": リード 片側p={rr['lead_p']:.3f}／FAQ 片側p={rr['faq_p']:.3f}")
    else:
        print(pool_note(rr))
    print()


def tested(rr):
    """再ランダム化の p を出してよいか（プールが下限以上）。"""
    return bool(rr) and not rr.get("short")


def pool_note(rr):
    """再ランダム化の p を出さないときの1行。フィッシャーは参考として並べたまま。"""
    if not rr:
        return ("再ランダム化検定: プール未作成"
                "（experiment_2x2/rerandomize.py --build で作る）")
    return (f"再ランダム化検定: プール不足（{rr['n']:,}件／下限{rerandomize.POOL_MIN:,}）。"
            "検定は行わない（フィッシャー検定は参考）。"
            "experiment_2x2/rerandomize.py --resume で続きを作る")


def randomization(after, exclude=()):
    """再ランダム化検定。同じ条件 a〜g を満たす割付の中で、実際の差以上が出る割合。

    プール(results/rerandomization_pool.csv)が無ければ None。下限
    (rerandomize.POOL_MIN)未満なら {"n": 件数, "short": True} で p は出さない。条件の合格率が
    約 1/9,200 なので、取りうる割付すべてを前提にしたフィッシャー検定より、
    こちらを判定の本線にする。
    """
    pool_rows = rerandomize.load()
    if not pool_rows:
        return None
    if len(pool_rows) < rerandomize.POOL_MIN:
        # 2026-09-28：下限 2,000 件。少ないプールの p はモンテカルロ誤差が大きい
        return {"n": len(pool_rows), "short": True}
    import allocate_47
    arts, _ = allocate_47.load_articles()
    groups = load_allocation()
    if not groups:
        return None
    actual = [rerandomize.GROUPS.index(groups[a['slug']]) for a in arts]
    cited_any = {s: v for s, (_, v) in after.items()}
    outcomes = rerandomize.outcomes_for(arts, cited_any, exclude)
    return rerandomize.p_values(pool_rows, actual, outcomes)


def variants():
    """感度分析の4通り（表があれば5通り・6通り）。(見出し, 除く記事) を返す。

    9/15〜16 に逆リンク追記が入った9本と、鮮度更新の訂正が入る記事は、どちらも
    処置以外の理由で本文が変わっている。片方だけ抜いた結果も並べないと、
    結論がどちらの影響で動いたのか分からない。
    訂正対象は 2026-09-26 から agentforce-features の1本だけ（vibes は訂正見送り）。

    5通り目（2026-09-29）：FAQ の回答が複数段落の記事を**組に関係なく**抜く。
    B-24 の処置で、処置群の複数段落回答6本（②3本・④3本）は <br> でつないで変換した。
    処置群だけ抜くと組の条件が崩れるので、①③の同じ性質の記事も抜く。
    表（pool.multi_paragraph_slugs）が無いときは出さない（pool_multi_note が理由を出す）。
    """
    late = late_appended_slugs()
    corr = set(APPLIED_CORRECTION_SLUGS)
    out = [
        ("両方込み", set()),
        (f"9本抜き（9/15〜16 追記）", set(late)),
        ("features 抜き（訂正対象）", corr),
        ("9本＋features 抜き", set(late) | corr),
    ]
    multi = multi_paragraph_slugs()
    if multi is not None:
        out.append((f"複数段落回答抜き（{len(multi[0])}本・全組）", set(multi[0])))
    # 6通り目（2026-10-02）：ピラーA・ピラーBのどちらかから既存リンクを受けている46本を全組から抜く。
    # 凍結を解いたピラーに孤児へのリンクが足され、既存リンクの重みが薄まる（①②に多い）ため
    linked = pillar.linked_articles()
    if linked is not None:
        out.append((f"ピラーの既存リンク先抜き（{len(linked)}本・全組）", set(linked)))
    # 7通り目〜(2026-10-08)：MA・メールマーケ28本の note 移設で内部被リンクが減る2本（E23・E27。どちらも④）を抜く。
    # 9本抜き・複数段落回答抜きとの組み合わせも出す（重なる記事は1回だけ抜く。2本とも両方に含まれるので、
    # 組み合わせは元の通りと同じ記事になる）。早期解放の条件(3)・再ランダム化検定もこの通りを含む
    loss = set(LINK_LOSS_SLUGS)
    out.append((f"リンク減2本抜き（{'・'.join(LINK_LOSS_IDS)}）", loss))
    out.append(("9本抜き＋リンク減2本", set(late) | loss))
    if multi is not None:
        out.append(("複数段落回答抜き＋リンク減2本", set(multi[0]) | loss))
    # 最後の通り(2026-10-18)：実験期間中に誤情報を直す1本を抜く。記録が届くまでは出さない(sensitivity_table が理由を出す)。
    # 1本だけの集合なので、既存の行と同じ記事集合になるのは features 抜き(その記事が agentforce-features のとき)だけ。
    # そのときは merge_same_sets が1行にまとめる。早期解放の条件(3)・再ランダム化検定もこの通りを含む
    fix = set(MISINFO_FIX_SLUGS)
    if fix:
        out.append((misinfo_fix_label(), fix))
    # 事実訂正 A(2026-10-20 準備)：Agentforce の導入実績があるように読める文を直す記事(約20本)を全組から抜く。
    # fact_corrections.csv が空のうちは出さない(sensitivity_table が「記録待ち」の行を出す)。B は記事を抜かないので fact_cut で別に作る
    fact = fact_correction_slugs()
    if fact:
        out.append((fact_a_label(fact), set(fact)))
    return merge_same_sets(out)


# --------------------------------------------------------------------------
# 事実訂正（2026-10-20 準備）：A「事実訂正あり記事抜き」・B「事実訂正前で打ち切り」
# --------------------------------------------------------------------------
FACT_A = "事実訂正あり記事抜き"
FACT_B = "事実訂正前で打ち切り"
FACT_PENDING = "記録待ち"
GROUP_ORDER = ("①対照", "②FAQのみ", "③リードのみ", "④両方")


def fact_a_label(fact=None):
    fact = fact_correction_slugs() if fact is None else fact
    return f"{FACT_A}（{len(fact)}本・全組）"


def fact_b_label(at):
    return f"{FACT_B}（{at:%Y-%m-%d %H:%M} より前）"


def fact_group_counts(slugs=None, groups=None):
    """{組: 本数}（4組とも出す・0本も）。組は allocation_v1.csv から引く。"""
    slugs = fact_correction_slugs() if slugs is None else slugs
    groups = load_allocation() if groups is None else groups
    counts = {g: 0 for g in GROUP_ORDER}
    for s in slugs:
        g = groups.get(s)
        if g in counts:
            counts[g] += 1
    return counts


def fact_imbalanced(counts):
    """組の間の本数の差が pool.FACT_CORRECTION_IMBALANCE（3本）以上か。"""
    return bool(counts) and max(counts.values()) - min(counts.values()) >= FACT_CORRECTION_IMBALANCE


def print_fact_correction_head(groups=None):
    """判定レポートの冒頭：事実訂正の対象の記事の組ごとの本数と偏り。記録が無ければ「記録待ち」。"""
    groups = load_allocation() if groups is None else groups
    rows = load_fact_corrections()
    print("## 事実訂正（Agentforce の導入実績があるように読める文の訂正・凍結46本）")
    if not rows:
        print(f"{FACT_PENDING}：experiment_2x2/fact_corrections.csv が空。"
              f"感度分析の「{FACT_A}」「{FACT_B}」は記録が届いてから計算する\n")
        return None
    fact = fact_correction_slugs()
    counts = fact_group_counts(fact, groups)
    spread = max(counts.values()) - min(counts.values())
    mark = (f"**偏りあり**（組の間の差 {spread}本。{FACT_CORRECTION_IMBALANCE}本以上）" if fact_imbalanced(counts)
            else f"偏りなし（組の間の差 {spread}本）")
    print(f"対象 {len(fact)}本：" + "・".join(f"{g} {n}本" for g, n in counts.items()) + f" → {mark}")
    first = fact_correction_first_at()
    timed = len({r['slug'] for r in rows if r['at'] is not None})
    print(f"最も早い訂正の時刻：{first:%Y-%m-%d %H:%M:%S}（時刻の入った記事 {timed}本／{len(fact)}本）" if first
          else f"訂正の時刻：{FACT_PENDING}（{FACT_B} は時刻が入ってから計算する）")
    outside = sorted({r['slug'] for r in rows} - pool_slugs())
    if outside:
        print(f"※ プール46本に無い記事が表にある（数えない）：{'・'.join(outside)}")
    wrong = sorted(r['slug'] for r in rows if r['slug'] in groups and r['group'] and r['group'] != groups[r['slug']])
    if wrong:
        print(f"※ 表の「組」が allocation_v1.csv と違う記事（組は allocation_v1.csv を使う）：{'・'.join(sorted(set(wrong)))}")
    print()
    return counts


def fact_cut(rows, span, model, groups, pool, until=None):
    """感度分析 B の材料。{label, status, at, after, obs_full, obs_cut, days_full, days_cut}。

    status：pending（時刻が無い）・none（訂正がアフターの初日より前で、使える観測が無い）・
    same（訂正がアフターの最終日より後で、打ち切っても全期間と同じ）・cut（打ち切る）。
    ``until`` を省くと fact_corrections.csv の最も早い訂正の時刻を使う。"""
    import datetime as _dt
    until = fact_correction_first_at() if until is None else until
    start, end = span
    obs = [r for r in rows if r.get("model") == model and start <= str(r.get("date", ""))[:10] <= end
           and counted(r, pool)]
    kept = [r for r in obs if before_cut(r, until)]
    out = {"at": until, "obs_full": len(obs), "days_full": len({str(r.get("date", ""))[:10] for r in obs}),
           "obs_cut": len(kept), "days_cut": len({str(r.get("date", ""))[:10] for r in kept}), "after": None}
    if until is None:
        return dict(out, label=FACT_B, status="pending", obs_cut=None, days_cut=None)
    out["label"] = fact_b_label(until)
    if until <= _dt.datetime.fromisoformat(start):
        return dict(out, status="none")
    # 打ち切りがアフターの最終日の後、または打ち切りで落ちる観測が無いなら全期間と同じ
    if until >= _dt.datetime.fromisoformat(end) + _dt.timedelta(days=1) or out["obs_cut"] == out["obs_full"]:
        out["status"] = "same"
    else:
        out["status"] = "cut"
    out["after"] = period(rows, span, model, groups, pool, until=until)
    return out


def fact_lines(after, cut):
    """感度分析の表の下に出す行：A で抜いた後の本数（組ごと）と、B で使えるアフター期間の観測回数。"""
    lines = []
    fact = fact_correction_slugs()
    if not fact:
        lines.append(f"※ 「{FACT_A}」：{FACT_PENDING}（fact_corrections.csv が空）")
    else:
        groups = tally(after, None, fact)
        left = {g: len(groups.get(g, [])) for g in GROUP_ORDER}
        full = {g: len(tally(after, None).get(g, [])) for g in GROUP_ORDER}
        lines.append(f"※ 「{FACT_A}」で抜いた後の残り：{sum(left.values())}本／{sum(full.values())}本（"
                     + "・".join(f"{g} {left[g]}本" for g in GROUP_ORDER)
                     + "）。本数が減るぶん比べる力が落ちる")
    if cut is None or cut["status"] == "pending":
        lines.append(f"※ 「{FACT_B}」：{FACT_PENDING}（fact_corrections.csv に訂正の時刻が無い）")
    else:
        use = (f"使えるのは {cut['obs_cut']:,}回（{cut['days_cut']}日）" if cut["status"] != "none"
               else "使える観測なし（訂正がアフター期間の初日より前）")
        same = "。打ち切りはアフター期間の後なので、全期間と同じ（「両方込み」と同じ）" if cut["status"] == "same" else ""
        lines.append(f"※ 「{cut['label']}」：アフター期間の観測 {cut['obs_full']:,}回（{cut['days_full']}日）のうち"
                     f"{use}{same}。観測が減るぶん比べる力が落ちる")
    return lines


def misinfo_fix_label():
    ids = "・".join(MISINFO_FIX_IDS) or "・".join(sorted(MISINFO_FIX_SLUGS))
    return f"誤情報修正1本抜き（{ids}）"


def misinfo_fix_overlap():
    """誤情報を直す記事が、既存の感度分析のどの「抜く記事」に含まれるか。[(見出し, 含まれるか)]。記録が無ければ None。"""
    fix = set(MISINFO_FIX_SLUGS)
    if not fix:
        return None
    multi = multi_paragraph_slugs()
    linked = pillar.linked_articles()
    sets = [("9本（9/15〜16 追記）", set(late_appended_slugs())),
            ("features（訂正対象）", set(APPLIED_CORRECTION_SLUGS)),
            ("複数段落回答", set(multi[0]) if multi is not None else None),
            ("ピラーの既存リンク先", set(linked) if linked is not None else None),
            ("リンク減2本", set(LINK_LOSS_SLUGS))]
    return [(label, s is not None and fix <= s) for label, s in sets]


def misinfo_fix_note():
    """感度分析の表の下に出す1行。"""
    over = misinfo_fix_overlap()
    if over is None:
        return ("※ 「誤情報修正1本抜き」は出していない：seo-agent からの記録（slug・組・適用日時）待ち"
                "（pool.MISINFO_FIX_SLUGS が空）")
    inside = [label for label, hit in over if hit]
    return (f"※ 誤情報修正の1本（{'・'.join(MISINFO_FIX_IDS) or '・'.join(MISINFO_FIX_SLUGS)}）は"
            + (f"{'・'.join(inside)}にも含まれる" if inside else "既存の感度分析のどの行にも含まれない"))


def merge_same_sets(variant_list):
    """抜く記事の集合がまったく同じ行を1行にまとめる(2026-10-08)。先に出た行の名前を残し、
    「〔〇〇と同じ記事集合〕」と注記する。判定の中身(どの記事を抜くか)は変わらない。"""
    merged, index = [], {}
    for label, exclude in variant_list:
        key = frozenset(exclude)
        if key in index:
            i = index[key]
            first, ex = merged[i]
            merged[i] = (first + f"〔{label}と同じ記事集合〕", ex)
            continue
        index[key] = len(merged)
        merged.append((label, set(exclude)))
    return merged


def link_loss_date(rows=None):
    """移設で E23・E27 の被リンクが減った日（interventions.csv の scope=site_structure の行の日付）。記録が無ければ None。

    2記事のリンクが消えた日時が別々なら、遅いほうを区切りにする（2026-10-08 本田さん指示）。"""
    rows = interventions.load() if rows is None else rows
    hits = [r for r in rows if scope_key(r.get("scope")) == LINK_LOSS_SCOPE and r.get("date") is not None
            and any(s in str(r.get("description", "")) for s in LINK_LOSS_SLUGS)]
    return max(r["date"] for r in hits) if hits else None


_LINK_LOSS_AT = re.compile(r"区切り日時は\D*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)")


def link_loss_at(rows=None):
    """区切り日時（JST の文字列）。行の note の「区切り日時は…YYYY-MM-DD HH:MM:SS」から取る（2026-10-11）。
    時刻が書かれていなければ日付だけ。記録が無ければ None。

    「リンク減2本抜き」は E23・E27 を期間全体で抜くので、区切り日時で数字は変わらない（注記と表示のため）。"""
    rows = interventions.load() if rows is None else rows
    day = link_loss_date(rows)
    if day is None:
        return None
    times = [m.group(1) for r in rows if scope_key(r.get("scope")) == LINK_LOSS_SCOPE and r.get("date") == day
             for m in [_LINK_LOSS_AT.search(str(r.get("note", "")))] if m and m.group(1).startswith(str(day))]
    return max(times) if times else str(day)


def print_link_loss_note(after, rows=None):
    """アフター期間中に E23・E27 の被リンク減があれば注記（短期判定は 11/1 までに起きた場合だけ・長期判定は期間内なら）。"""
    import datetime as _dt
    rows = interventions.load() if rows is None else rows
    day = link_loss_date(rows)
    start, end = (_dt.date.fromisoformat(x) for x in _span(after))
    if day is None or not (start <= day <= end):
        return False
    print(f"**アフター期間中（{day}）に E23・E27 の被リンク減あり。いずれも④。リード・FAQの効果とも小さめに出る方向**"
          f"（区切り日時 {link_loss_at(rows)}）：MA・メールマーケ記事の note 移設で buyer-enablement（E23・④）の被リンク4本・"
          "hyper-personalization（E27・④）の1本が消えた。感度分析の「リンク減2本抜き」を参照\n")
    return True


def misinfo_fix_date(rows=None):
    """誤情報修正の実施日（interventions.csv の scope=プール46本 で記事の slug を含む行の date）。記録が無ければ None。"""
    rows = interventions.load() if rows is None else rows
    hits = [r for r in rows if scope_key(r.get("scope")) == MISINFO_FIX_SCOPE and r.get("date") is not None
            and any(s in str(r.get("description", "")) for s in MISINFO_FIX_SLUGS)]
    return max(r["date"] for r in hits) if hits else None


def print_misinfo_fix_note(after, rows=None):
    """アフター期間中に誤情報修正があれば偏りの向きを注記（2026-10-18・本田さん指示）。短期・長期の両方に出る。"""
    import datetime as _dt
    if not MISINFO_FIX_SLUGS:
        return False
    rows = interventions.load() if rows is None else rows
    day = misinfo_fix_date(rows)
    start, end = (_dt.date.fromisoformat(x) for x in _span(after))
    if day is None or not (start <= day <= end):
        return False
    group = load_allocation().get(MISINFO_FIX_SLUGS[0], "")
    mark = group[:1]
    print(f"**アフター期間中（{day}）に {'・'.join(MISINFO_FIX_IDS)}（{mark}）の本文と FAQ の数字の修正、"
          "および架空の例と『当社では』の分離を実施。"
          f"{mark}の引用が下がる場合、リードの効果は大きめ（甘い方向）、FAQの効果は小さめに出る。"
          "リードの早期解放は『誤情報修正1本抜き』でも効果の向きが同じときだけ通る**"
          f"（{MISINFO_FIX_SLUGS[0]}・{group}。15:46:07 に本文{MISINFO_FIX_PARAGRAPHS}段落、16:05:51 に FAQ の答え"
          f"{MISINFO_FIX_FAQ_ANSWERS}か所、16:44:20 に残りの{MISINFO_FIX_REST_CHANGES}か所（本文28・FAQ の答え2）。"
          "数字を幅のある表現にし、架空の事例である旨の断りを足し、架空の例の直後に「当社では」が続く2か所を分離。"
          "FAQ は数字だけ（問いの数・順番・位置は不変）。見出し・リード・リンクは不変。感度分析の「誤情報修正1本抜き」を参照）\n")
    return True


def multi_paragraph_note():
    """5通り目を出せない・抜き漏れがありうるときの1行。問題が無ければ None。"""
    multi = multi_paragraph_slugs()
    if multi is None:
        return ("※ 5通り目（複数段落回答抜き）は出していない："
                "faq_multiparagraph_*.csv が無い（seo-agent 側が作る）")
    if multi[1]:
        return (f"※ 複数段落回答の表に載っていない記事が {len(multi[1])}本ある"
                f"（{'・'.join(sorted(multi[1]))}）。抜き漏れがありうる")
    return None


def _table_row(label, after, before, exclude=()):
    groups = tally(after, before, exclude)
    rate = is_rate(groups)
    n = sum(len(x) for x in groups.values())
    rates = []
    for g in GROUP_ORDER:
        hit, miss = cells(groups, g)
        rates.append(share(hit, len(groups.get(g, [])), rate))
    _, _, _, _, lead_diff, lead_p = effect(groups, LEAD_ON, LEAD_OFF)
    _, _, _, _, faq_diff, faq_p = effect(groups, FAQ_ON, FAQ_OFF)
    rr = randomization(after, exclude)
    ok = tested(rr)
    return [label, str(n)] + rates + [
        f"{lead_diff:+.0%}",
        f"{rr['lead_p']:.3f}" if ok else "—", "—" if lead_p is None else f"{lead_p:.3f}",
        f"{faq_diff:+.0%}",
        f"{rr['faq_p']:.3f}" if ok else "—", "—" if faq_p is None else f"{faq_p:.3f}"], rr


def _pending_row(label, text=FACT_PENDING):
    return [label, text] + [""] * 10


def sensitivity_table(after, before, title="", cut=None):
    """感度分析（両方込み／9本抜き／features 抜き／…／事実訂正 A・B）を1つの表にする。

    ``cut`` は fact_cut の結果（感度分析 B）。None か時刻が無ければ B は「記録待ち」の行。"""
    rows = []
    rr = None
    labels = variants()
    for i, (label, exclude) in enumerate(labels):
        if i == 0 and cut is not None and cut["status"] == "same":
            # B が全期間と同じ観測になる（打ち切りがアフター期間の後）ときは「両方込み」の行にまとめる
            label += f"〔{cut['label']}と同じ観測〕"
        row, rr = _table_row(label, after, before, exclude)
        rows.append(row)
    if not fact_correction_slugs():
        rows.append(_pending_row(FACT_A))
    if cut is None or cut["status"] == "pending":
        rows.append(_pending_row(FACT_B))
    elif cut["status"] == "none":
        rows.append(_pending_row(cut["label"], "観測なし"))
    elif cut["status"] == "cut":
        rows.append(_table_row(cut["label"], cut["after"], before)[0])
    head = ["感度分析" + (f"（{title.strip()}）" if title.strip() else ""), "本数",
            "①対照", "②FAQのみ", "③リードのみ", "④両方",
            "リード差", "p(再ランダム化)", "p(フィッシャー)",
            "FAQ差", "p(再ランダム化)", "p(フィッシャー)"]
    width = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    def row(cells_):
        return "  ".join(c.ljust(w) for c, w in zip(cells_, width)).rstrip()
    print(row(head))
    print("  ".join("-" * w for w in width))
    for r in rows:
        print(row(r))
    print(f"使用した割付数：{rr['n']:,}" if tested(rr) else pool_note(rr))
    if is_rate(tally(after, before)):
        print("※ Claude は記事ごとの率（cited_article=1 の回数 ÷ 観測できた回数）の平均で比べる。"
              "組のマスは「平均の率（本数）」。率のためフィッシャー検定は出さない（—）。"
              "再ランダム化検定は率の平均の差で行う")
    note = multi_paragraph_note()
    if note:
        print(note)
    print(misinfo_fix_note())
    for line in fact_lines(after, cut):
        print(line)
    print()


def faq_by_multi_paragraph(after, before, title=""):
    """FAQ の主効果を、複数段落回答あり／なしの層に分けて比べる（2026-09-29）。

    複数段落回答の7本は、9/28 の割付で偶然すべて ②④（FAQ あり）に入った（条件 a〜g に
    入れていなかった性質）。この性質を共変量として、層の中だけで ②④ 対 ①③ を比べる。
    片側の組に1本も無い層は比べられないので「比較不能」と出す。
    「なし」の層は、感度分析の5通り目（複数段落回答抜き）の FAQ 差と同じ記事で数える。
    """
    multi = multi_paragraph_slugs()
    head = "FAQ の主効果（複数段落回答で層別）" + (f"（{title.strip()}）" if title.strip() else "")
    print(head)
    if multi is None:
        print("  faq_multiparagraph_*.csv が無いため出していない\n")
        return None
    multi_set = set(multi[0])
    out = {}
    for name, keep in (("複数段落あり", lambda s: s in multi_set),
                       ("複数段落なし", lambda s: s not in multi_set)):
        drop = {s for s in after if not keep(s)}
        groups = tally(after, before, drop)
        a, an, c, cn, diff, p = effect(groups, FAQ_ON, FAQ_OFF)
        n = an + cn
        if not an or not cn:
            print(f"  {name}（{n}本）：比較不能（②④ {an}本／①③ {cn}本。片側に記事が無い）")
            out[name] = None
            continue
        on_d = [d for g in FAQ_ON for _, d in groups.get(g, [])]
        off_d = [d for g in FAQ_OFF for _, d in groups.get(g, [])]
        did = sum(on_d) / len(on_d) - sum(off_d) / len(off_d)
        rate = is_rate(groups)
        print(f"  {name}（{n}本）：②④ {share(a, an, rate)}={a / an:.0%}  ①③ {share(c, cn, rate)}={c / cn:.0%}"
              f"  差 {diff:+.0%}  片側p(フィッシャー)={pval(p)}"
              + (f"  差の差（Δ平均の差）{did:+.2f}" if before else ""))
        out[name] = {"n": n, "on": (a, an), "off": (c, cn), "diff": diff, "p": p,
                     "did": did if before else None}
    print("  ※「複数段落なし」は感度分析の「複数段落回答抜き」と同じ記事。再ランダム化の p はそちらの行を見る\n")
    return out


def both_ways(after, before, title="", cut=None):
    """感度分析の表と、各通りの組別の内訳を出す。``cut`` は感度分析 B（fact_cut の結果）。"""
    sensitivity_table(after, before, title, cut)
    faq_by_multi_paragraph(after, before, title)
    for label, exclude in variants():
        summarize(after, before, exclude, f"{title}{label}")
    if cut is not None and cut["status"] == "cut":
        summarize(cut["after"], before, (), f"{title}{cut['label']}")


def cut_signs(cut):
    """早期解放の条件(3)に足す B の行。(見出し, アフター) のリスト。打ち切りがあるときだけ。"""
    return [(cut["label"], cut["after"])] if cut is not None and cut["status"] in ("cut", "none") else []


# --------------------------------------------------------------------------
# 早期解放の判定（2026-10-01 事前登録・2026-10-07 実装。短期判定のデータを見る前に固定）
# --------------------------------------------------------------------------
# 短期判定（2026-11-02 の週。アフター 10/06〜11/01）でのみ出す。Gemini のみ（Claude は観測停止で対象外）。
# 施策ごとに、次の3つをすべて満たしたら「解放可」：
#   (1) Gemini の cited_article（記事単位・主指標と同じ定義）の差の差が +20ポイント以上
#   (2) 再ランダム化検定（判定の本線と同じ）の片側 p値が 0.005 未満。プールが2,000件未満なら判定しない
#   (3) 感度分析の全パターン（variants() の全通り）で差の差の向きが同じ（すべて正）
# 境目：(1) ちょうど +20ポイントは合格（以上）、(2) ちょうど 0.005 は不合格（未満）
SHORT_JUDGEMENT_AFTER = ("2026-10-06", "2026-11-01")
EARLY_RELEASE_DID_PT = 20.0
EARLY_RELEASE_P = 0.005
EARLY_RELEASE_TREATMENTS = (("リード（③＋④ 対 ①＋②）", LEAD_ON, LEAD_OFF, "lead_p"),
                            ("FAQ（②＋④ 対 ①＋③）", FAQ_ON, FAQ_OFF, "faq_p"))
EARLY_RELEASE_YES = ("この施策のみ、残りの記事（その施策を受けていない組）に入れてよい。"
                     "その他の編集（リライト・画像・リンク）は 12/31 まで禁止のまま")
EARLY_RELEASE_NO = "12/28 の週の長期判定まで継続（遅れて効く可能性があるため、効いていないことによる打ち切りはしない）"
EARLY_RELEASE_POOL_SHORT = "プール不足のため判定不能"


def did_of(after, before, on_groups, off_groups, exclude=()):
    """差の差(ポイント)。あり側・なし側どちらかに記事が無ければ None。"""
    groups = tally(after, before, exclude)
    on_d = [d for g in on_groups for _, d in groups.get(g, [])]
    off_d = [d for g in off_groups for _, d in groups.get(g, [])]
    if not on_d or not off_d:
        return None
    return round((sum(on_d) / len(on_d) - sum(off_d) / len(off_d)) * 100, 6)


def early_release(after, before, rr=None, variant_list=None, cut=None):
    """施策ごとの早期解放の判定。[{name, did, did_ok, p, n, p_ok, signs, signs_ok, verdict, text}]。

    ``rr`` は再ランダム化検定の結果（省略時は randomization(after)）。``variant_list`` は感度分析の通り（省略時は variants()）。
    ``cut`` は感度分析 B（fact_cut の結果）。打ち切りがあれば条件(3)に B の行も入る（観測が無ければ「計算できない」で不合格）。
    """
    rr = randomization(after) if rr is None else rr
    variant_list = variants() if variant_list is None else variant_list
    out = []
    for name, on, off, key in EARLY_RELEASE_TREATMENTS:
        did = did_of(after, before, on, off)
        did_ok = did is not None and did >= EARLY_RELEASE_DID_PT
        pool_ok = tested(rr)
        p = rr.get(key) if pool_ok else None
        p_ok = pool_ok and p is not None and p < EARLY_RELEASE_P
        signs = [(label, did_of(after, before, on, off, exclude)) for label, exclude in variant_list]
        signs += [(label, did_of(part, before, on, off) if part else None) for label, part in cut_signs(cut)]
        signs_ok = bool(signs) and all(v is not None and v > 0 for _, v in signs)
        if not pool_ok:
            verdict, text = EARLY_RELEASE_POOL_SHORT, EARLY_RELEASE_NO
        elif did_ok and p_ok and signs_ok:
            verdict, text = "解放可", EARLY_RELEASE_YES
        else:
            verdict, text = "解放不可", EARLY_RELEASE_NO
        out.append({"name": name, "did": did, "did_ok": did_ok, "p": p,
                    "n": (rr or {}).get("n", 0), "p_ok": p_ok, "signs": signs, "signs_ok": signs_ok,
                    "verdict": verdict, "text": text})
    return out


def is_short_judgement(after_span):
    return tuple(after_span) == SHORT_JUDGEMENT_AFTER


def fact_pending_note(cut=None):
    """条件(3)に入れられなかった事実訂正の行（記録待ち）の注記。無ければ None。"""
    pending = ([FACT_A] if not fact_correction_slugs() else []) + \
        ([FACT_B] if cut is None or cut["status"] == "pending" else [])
    if not pending:
        return None
    return (f"※ 条件(3)の「{'」「'.join(pending)}」は{FACT_PENDING}のため含めていない（fact_corrections.csv が空・時刻なし）。"
            "訂正を反映したのに記録が無いまま判定しないこと")


def print_early_release(after, before, rr=None, variant_list=None, cut=None):
    ok = lambda b: "合格" if b else "不合格"  # noqa: E731
    print("## 早期解放の判定（短期判定のみ・Gemini・2026-10-01 事前登録）")
    note = fact_pending_note(cut)
    if note:
        print(note)
    for r in early_release(after, before, rr, variant_list, cut):
        print(f"### {r['name']}")
        did = "計算できない" if r["did"] is None else f"{r['did']:+.1f}ポイント"
        print(f"- (1) 差の差 {did}（基準 +{EARLY_RELEASE_DID_PT:.0f}ポイント以上）→ {ok(r['did_ok'])}")
        if r["verdict"] == EARLY_RELEASE_POOL_SHORT:
            print(f"- (2) 再ランダム化検定：{EARLY_RELEASE_POOL_SHORT}（プール {r['n']:,}件／下限{rerandomize.POOL_MIN:,}件）")
        else:
            print(f"- (2) 再ランダム化検定 片側p={r['p']:.4f}（基準 {EARLY_RELEASE_P} 未満・割付 {r['n']:,}件）→ {ok(r['p_ok'])}")
        shown = "・".join(f"{label} {'—' if v is None else f'{v:+.1f}'}" for label, v in r["signs"])
        print(f"- (3) 感度分析の全{len(r['signs'])}通りで向きが同じ（すべて正）：{shown} → {ok(r['signs_ok'])}")
        print(f"- **判定：{r['verdict']}**　{r['text']}")
    print("※ Claude は観測停止のため対象外。この欄は短期判定でのみ出す（長期判定・週次レポートには出さない）\n")


# --------------------------------------------------------------------------
# GSC 補助分析：Google 順位の上位・下位で処置の効き方が違うか（2026-10-01 事前固定）
# --------------------------------------------------------------------------
# 分け方は gsc_rank_split.py が gsc_rank_split_v1.csv に固定した（アフターを見る前）。
# 探索的分析：推定値（差の差）と95%の幅だけを出す。p値・「効いた」の判定・再ランダム化検定は使わない。
GSC_RANK_SPLIT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gsc_rank_split_v1.csv")
# 2026-10-01 に実際の本数(上位17本・下位29本)に合わせて差し替えた(旧:「1マス5〜6本のため…」)
GSC_SUBGROUP_HEADER = ("探索的分析。1マスは上位で4本前後、下位で7本前後のため判定には使わない。State 項目8の参考。\n"
                       "1マスの本数が少ないため、95%の幅（ブートストラップ）は不安定で、実際より狭く出ることがある")
BOOTSTRAP_DRAWS = 10000
BOOTSTRAP_SEED = 20261001


def read_rank_split(path=None):
    """{slug: '上位'|'下位'}。"""
    with io.open(path or GSC_RANK_SPLIT_CSV, encoding="utf-8") as f:
        return {r["slug"]: r["rank_split"] for r in csv.DictReader(f)}


def did_interval(on_d, off_d, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """差の差（処置ありの Δ平均 − なしの Δ平均）と、その95%の幅（ブートストラップ・百分位）。

    本数が少ない（各側4〜7本）ので正規近似は使わず、記事を側ごとに復元抽出する。
    乱数の種は固定して、同じデータなら同じ幅が出るようにする。片側が0本なら None。
    """
    import random
    if not on_d or not off_d:
        return None
    est = sum(on_d) / len(on_d) - sum(off_d) / len(off_d)
    rng = random.Random(seed)
    sims = sorted(
        sum(rng.choice(on_d) for _ in on_d) / len(on_d)
        - sum(rng.choice(off_d) for _ in off_d) / len(off_d)
        for _ in range(draws))
    return est, sims[int(0.025 * draws)], sims[int(0.975 * draws) - 1]


def _direction(upper, lower):
    if upper is None or lower is None:
        return "比べられない（片方の層で推定できない）"
    if upper[0] * lower[0] < 0:
        return "**逆**（上位と下位で符号が違う）"
    if upper[0] == 0 or lower[0] == 0:
        return "どちらかが0（向きを比べられない）"
    return "同じ"


def gsc_rank_subgroups(after, before, title="", split=None, today=None):
    """上位・下位それぞれの中で、リードと FAQ の主効果の差の差（推定値と95%の幅）。

    11/2（短期判定）より前は実行しない（組ごとの比較につながる数字を出さないルール）。
    """
    import datetime
    today = today or datetime.date.today()
    head = "GSC 補助分析（Google 順位の上位・下位で層別）" + (f"（{title.strip()}）" if title.strip() else "")
    print(head)
    if today < datetime.date.fromisoformat(GROUP_BLIND_UNTIL):
        print(f"  {GROUP_BLIND_UNTIL} の短期判定まで実行しない（組ごとの比較を途中で見ないため）\n")
        return None
    for line in GSC_SUBGROUP_HEADER.splitlines():
        print(f"  {line}")
    if not before:
        print("  ビフォーが無いため差の差を出せない\n")
        return None
    split = split if split is not None else read_rank_split()
    out = {}
    for layer in ("上位", "下位"):
        groups = tally(after, before, {s for s in after if split.get(s) != layer})
        n = sum(len(v) for v in groups.values())
        res = {}
        for name, on, off in (("リード", LEAD_ON, LEAD_OFF), ("FAQ", FAQ_ON, FAQ_OFF)):
            on_d = [d for g in on for _, d in groups.get(g, [])]
            off_d = [d for g in off for _, d in groups.get(g, [])]
            res[name] = did_interval(on_d, off_d)
            cell = f"あり {len(on_d)}本・なし {len(off_d)}本"
            if res[name] is None:
                print(f"  {layer}（{n}本）{name}：推定できない（{cell}）")
            else:
                est, lo, hi = res[name]
                print(f"  {layer}（{n}本）{name}：差の差 {est:+.2f}（95%の幅 {lo:+.2f}〜{hi:+.2f}・{cell}）")
        out[layer] = res
    for name in ("リード", "FAQ"):
        print(f"  {name}の効果の向き（上位と下位）：{_direction(out['上位'][name], out['下位'][name])}")
    print("  ※ 推定値と幅のみ。p値と「効いた・効かない」の判定は出さない。再ランダム化検定は使わない\n")
    return out


# --------------------------------------------------------------------------
# 判定期間中のサイト施策一覧＝交絡候補(2026-10-01 新設・2026-10-07 に全介入へ拡大)
# --------------------------------------------------------------------------
# interventions.csv の**全行**のうち、判定期間(ビフォーの初日〜その判定のアフターの最終日)に日付が重なるものを載せる
# (scope で絞らない。2026-10-07 本田さん決定)。表示は scope の括弧より前でまとめ、touches_pool46=yes の行を含む
# scope を先にする(その中は日付順)。日付が定まらない行(「〜より前」など)は末尾に「日付不確定」として載せる。
# 表示だけで、判定の数値(差の差・p値・感度分析)には使わない。interventions.csv の scope は書き換えない
CONFOUNDER_HEADING = "判定期間（ビフォー〜アフター）中のサイト施策一覧（判定の交絡候補）"


def scope_key(scope):
    """scope の括弧より前から、末尾の「数字＋件」を除いたもの。
    「ピラーA（agentforce-guide）」→「ピラーA」、「固定ページ4件（68 /contact/…）」→「固定ページ」(2026-10-07)。"""
    import re
    base = re.split(r"[（(]", str(scope or ""))[0].strip()
    return re.sub(r"\s*[0-9０-９]+件$", "", base).strip() or "（scope なし）"


def intervention_end(row):
    """介入の終わりの日。継続("〜"で終わる)は None(終わりなし)。"2026-09-20〜22" は 22 日。"""
    raw = str(row.get("raw_date") or "")
    start = row.get("date")
    if start is None or row.get("ongoing"):
        return None
    tail = raw.split("〜", 1)[1] if "〜" in raw else ""
    try:
        if tail.count("-") == 1:                         # 〜MM-DD
            m, d = tail.split("-")
            return start.replace(month=int(m), day=int(d))
        if tail.isdigit():                               # 〜DD
            return start.replace(day=int(tail))
    except ValueError:
        pass
    return start


def site_wide_interventions(start, end, rows=None):
    """(期間と重なる介入, 日付が定まらない介入)。start・end は date。interventions.csv の全行が対象。

    介入は処置以外の理由で引用されやすさを動かしうる。判定のたびに冒頭に並べ、処置の効果と取り違えないようにする。
    """
    rows = interventions.load() if rows is None else rows
    overlap = []
    for r in rows:
        if r.get("date") is None:
            continue
        stop = intervention_end(r)
        if r["date"] <= end and (stop is None or stop >= start):
            overlap.append(r)
    return overlap, [r for r in rows if r.get("date") is None]


def group_by_scope(rows):
    """[(scope の括弧より前, 行)]。touches_pool46=yes の行を含む scope を先、同じ扱いの中は最初の日付順。行は日付順。"""
    groups = {}
    for r in rows:
        groups.setdefault(scope_key(r.get("scope")), []).append(r)
    for key in groups:
        groups[key].sort(key=lambda r: (r["date"], str(r.get("intervention_id"))))
    touches = lambda rs: any(str(r.get("touches_pool46", "")).strip() == "yes" for r in rs)  # noqa: E731
    return sorted(groups.items(), key=lambda kv: (not touches(kv[1]), kv[1][0]["date"], kv[0]))


def _line(r, date_text=None):
    return (f"  - {date_text or r.get('raw_date', '')}｜{r['intervention_id']}｜{r['description']}"
            f"｜scope={r.get('scope', '')}｜touches_pool46={r.get('touches_pool46', '')}")


def print_site_wide_interventions(before, after, rows=None):
    import datetime as _dt
    start = _dt.date.fromisoformat(_span(before)[0])
    end = _dt.date.fromisoformat(_span(after)[1])
    overlap, undated = site_wide_interventions(start, end, rows)
    print(f"## {CONFOUNDER_HEADING}")
    print(f"判定期間（{start}〜{end}）に日付が重なる interventions.csv の全行（scope ごと・プール46本に触れる行を含む scope が先）")
    if not overlap and not undated:
        print("なし\n")
        return overlap
    for key, group in group_by_scope(overlap):
        mark = "（プール46本に触れる行あり）" if any(str(r.get("touches_pool46", "")).strip() == "yes" for r in group) else ""
        print(f"- {key}{mark}")
        for r in group:
            print(_line(r))
    if undated:
        print("- 日付不確定（期間と重なるか判定できない）")
        for r in undated:
            print(_line(r))
    print("※ 全記事に一様にかかる介入は、組の差ではなく全組共通のベースラインの変化として読む\n")
    return overlap


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
        if model_excluded("claude", _span(a.after)):
            print(f"**{GENERALIZATION_NOTE}**\n")
        print_site_wide_interventions(a.before, a.after)
        print_link_loss_note(a.after)
        print_misinfo_fix_note(a.after)
        print_fact_correction_head(groups)
        pillar_lines, pillar_parts = pillar.report_lines(_span(a.after))
        print("\n".join(pillar_lines))
        rows = read_llm_experiment(a.csv)
        pool = pool_slugs()
        late = late_appended_slugs()
        if late:
            print(f"9/15〜16 に追記の入った{len(late)}本は {LATE_BASELINE_FROM} 以降の観測だけを使う")
        watch = sum(1 for r in rows if str(r.get("experiment_flag", "")).strip() == WATCH_FLAG)
        print(f"llm_experiment {len(rows)}行（watch {watch}行とプール外・欠測は数えない）\n")
        for model in ([a.model] if a.model else MODELS):
            if model_excluded(model, _span(a.after)):
                # 欠測を0（引用なし）として数えない。ビフォー（9/15〜9/28）の Claude データは消さずに記録として残す
                print(f"##### {model}\n{excluded_line(model)}\n")
                continue
            after = period(rows, _span(a.after), model, groups, pool)
            before = period(rows, _span(a.before), model, groups, pool)
            missing = sorted(set(after) - set(before))
            print(f"##### {model}（アフター {a.after} / ビフォー {a.before}）")
            if missing:
                print(f"ビフォーに観測の無い記事 {len(missing)}本（ビフォーは0として扱う）: {', '.join(missing)}")
            cut = fact_cut(rows, _span(a.after), model, groups, pool)
            both_ways(after, before, f"{model} ", cut)
            # ピラー編集が 10/6 以降に完了した場合は、アフターをその前後に分けた結果も並べる
            for label, span in pillar_parts:
                part = period(rows, span, model, groups, pool)
                print(f"##### {model}（アフター {span[0]}〜{span[1]}・{label} / ビフォー {a.before}）")
                both_ways(part, before, f"{model} {label} ", fact_cut(rows, span, model, groups, pool))
            gsc_rank_subgroups(after, before, f"{model} ")
            if model == "gemini" and is_short_judgement(_span(a.after)):
                print_early_release(after, before, cut=cut)
    print("判定: 差が +25pt 以上 かつ p<0.10 で「効いた」。どちらか欠ければ「この本数では判断できない」。")
    print("p は**再ランダム化検定**を本線にする（条件 a〜g の合格率が約 1/9,200 のため、"
          "同じ条件を満たす割付の中で数える）。フィッシャー正確検定は参考。")
    print("感度分析で結論が食い違う場合は、処置ではなく"
          "「9/15〜16 の追記」「鮮度更新の訂正」「FAQ の複数段落回答（<br> でつないだ変換）」「誤情報の修正（1本）」"
          "「事実訂正（導入実績の記述）」"
          "のどれかの影響として扱う。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
