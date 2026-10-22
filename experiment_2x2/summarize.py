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
import datetime
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
from pool import (FACT_CORRECTION_IMBALANCE, fact_correction_at_by_slug, fact_correction_first_at,  # noqa: E402
                  fact_correction_slugs, load_fact_corrections)
from pool import (APPLIED_CORRECTION_SLUGS, EXCLUDED,  # noqa: E402
                  LATE_BASELINE_FROM, PROBE_BASELINE_EXCLUDED, baseline_start,
                  late_appended_slugs, load_allocation, multi_paragraph_slugs,
                  load_pool, pool_slugs, slug)

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


def fact_slugs_in_order():
    """事実訂正の記事の slug（表の順・重複なし・プール46本の中だけ）。"""
    fact, out = fact_correction_slugs(), []
    for r in load_fact_corrections():
        if r["slug"] in fact and r["slug"] not in out:
            out.append(r["slug"])
    return out


def fact_eids(fact=None):
    """事実訂正の記事の E番号（表の順・重複なし）。E番号の無い記事は slug で出す。"""
    fact = fact_correction_slugs() if fact is None else set(fact)
    rows = load_fact_corrections()
    out = []
    for r in rows:
        key = r["eid"] or r["slug"]
        if r["slug"] in fact and key not in out:
            out.append(key)
    out += sorted(fact - {r["slug"] for r in rows})
    return out


def fact_a_label(fact=None):
    """感度分析 A の見出し。例：事実訂正2本抜き（E22・E05）（2026-10-22 本田さん指定の形）。"""
    fact = fact_correction_slugs() if fact is None else fact
    return f"事実訂正{len(fact)}本抜き（{'・'.join(fact_eids(fact))}）"


# その組の引用が下がったときの、リード・FAQ の効果の出方（効果＝処置あり − 処置なし）
FACT_SAFE, FACT_SOFT = "小さめ（安全側）", "大きめ（甘い方向）"


def fact_direction(group):
    """(リード, FAQ) の効果の出方。その組の引用が下がった場合。"""
    lead = FACT_SAFE if group in LEAD_ON else FACT_SOFT
    faq = FACT_SAFE if group in FAQ_ON else FACT_SOFT
    return lead, faq


def fact_places(fact=None):
    """決めた修正前後の文の組の数（drift の expected_edits.json と fact_correction_sentences.csv）。無ければ 0。"""
    import drift_check
    fact = fact_correction_slugs() if fact is None else set(fact)
    edits = drift_check.fact_sentence_edits(with_pending=True)
    return sum(len(drift_check._pair_list(e)) for e in edits if e.get("slug") in fact)


def fact_direction_note(groups=None, span=None):
    """偏りの向きの注記（2026-10-22・本田さん指示。短期・長期の両方に出す）。対象が無い・訂正がアフターの後なら None。"""
    import datetime as _dt
    groups = load_allocation() if groups is None else groups
    fact = fact_correction_slugs()
    if not fact:
        return None
    first = fact_correction_first_at()
    if first is not None and span is not None and first >= _dt.datetime.fromisoformat(span[1]) + _dt.timedelta(days=1):
        return None
    gs = [g for g in GROUP_ORDER if any(groups.get(s) == g for s in fact)]
    marks = "・".join(g[:1] for g in gs)
    if len(gs) == 1 and len(fact) > 1:
        who = f"ともに{marks}" if len(fact) == 2 else f"すべて{marks}"
    else:
        who = marks
    places = fact_places(fact)
    what = f"本文{places}か所" if places else "本文の文（箇所の数は記録待ち）"
    dirs = {fact_direction(g) for g in gs}
    if len(dirs) == 1:
        lead, faq = dirs.pop()
        tail = f"{marks}の引用が下がった場合、リードの効果は{lead}、FAQの効果は{faq}に出る"
    else:
        tail = "組によって向きが違う：" + "／".join(
            f"{g[:1]}の引用が下がるとリードは{fact_direction(g)[0]}・FAQは{fact_direction(g)[1]}" for g in gs)
    when = "" if first else "（反映の時刻は記録待ち）"
    return f"**{'・'.join(fact_eids(fact))}（{who}）の{what}を事実訂正{when}。{tail}**"


def fact_b_label(at):
    return f"{FACT_B}（{at:%Y-%m-%d %H:%M:%S} より前）"


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


def print_fact_correction_head(groups=None, span=None):
    """判定レポートの冒頭：事実訂正の対象の記事の組ごとの本数と偏り、偏りの向き。記録が無ければ「記録待ち」。"""
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
    note = fact_direction_note(groups, span)
    if note:
        print(note)
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


FACT_REFERENCE_HEADING = "参考：事実訂正の記事の反映の前後（Gemini・判定には使わない）"


def fact_reference(rows, span, pool, at_by_slug=None):
    """[{slug, at, before:{obs, cited, mentioned}, after:{…}}]。アフター期間の中を、反映の時刻の前と以後に分けて数える。

    時刻の無い観測は日付で見て、反映の日の分はどちらにも入れない（前後を決められない）。時刻の無い記事は at=None。"""
    at_by_slug = fact_correction_at_by_slug() if at_by_slug is None else at_by_slug
    start, end = span
    out = []
    for s in fact_slugs_in_order():
        at = at_by_slug.get(s)
        side = {k: {"obs": 0, "cited": 0, "mentioned": 0} for k in ("before", "after")}
        for r in rows if at is not None else []:
            if (r.get("model") != "gemini" or slug(r.get("target_url", "")) != s
                    or not (start <= str(r.get("date", ""))[:10] <= end) or not counted(r, pool)):
                continue
            t = observed_at_jst(r)
            if t is None:
                day, cut_day = str(r.get("date", ""))[:10], at.date().isoformat()
                key = None if day == cut_day else ("before" if day < cut_day else "after")
            else:
                key = "before" if t < at else "after"
            if key is None:
                continue
            side[key]["obs"] += 1
            side[key]["cited"] += str(r.get("cited_article", "")).strip() == "1"
            side[key]["mentioned"] += str(r.get("mentioned_v2", "")).strip() == "1"
        out.append({"slug": s, "at": at, **side})
    return out


def print_fact_reference(rows, span, groups=None, pool=None, today=None):
    """参考の表（2026-10-22 本田さん指示）。11/2 の短期判定より前は出さない（組ごとの結果を途中で見ないルール）。"""
    import datetime as _dt
    groups = load_allocation() if groups is None else groups
    pool = pool_slugs() if pool is None else pool
    today = today or _dt.date.today()
    fact = fact_correction_slugs()
    if not fact:
        return None
    print(f"### {FACT_REFERENCE_HEADING}")
    marks = "・".join(g[:1] for g in GROUP_ORDER if any(groups.get(s) == g for s in fact))
    if today < _dt.date.fromisoformat(GROUP_BLIND_UNTIL):
        print(f"{GROUP_BLIND_UNTIL} の短期判定まで出さない（組ごとの結果を途中で見ないため。{marks}の記事の結果にあたる）\n")
        return None
    table = fact_reference(rows, span, pool)
    eid = {r["slug"]: r["eid"] for r in load_fact_corrections()}
    print(f"**{len(table)}本・数回ずつの観測のため、上下から何かを言える量ではない。**"
          "判定には使わない（反映の時刻より前／以後。時刻の無い観測は、反映の日の分をどちらにも入れない）")
    print("| E番号 | slug | 組 | 反映の時刻 | 前：観測 | 前：cited_article | 前：mentioned_v2 "
          "| 後：観測 | 後：cited_article | 後：mentioned_v2 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for t in table:
        head = f"| {eid.get(t['slug'], '')} | {t['slug']} | {groups.get(t['slug'], '')} "
        if t["at"] is None:
            print(head + f"| {FACT_PENDING} |  |  |  |  |  |  |")
            continue
        b, a = t["before"], t["after"]
        print(head + f"| {t['at']:%Y-%m-%d %H:%M} | {b['obs']}回 | {b['cited']}回 | {b['mentioned']}回 "
              f"| {a['obs']}回 | {a['cited']}回 | {a['mentioned']}回 |")
    print()
    return table


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
        lines.append(f"※ 「{fact_a_label(fact)}」で抜いた後の残り：{sum(left.values())}本／{sum(full.values())}本（"
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


# --------------------------------------------------------------------------
# 新記事の横取りのおそれ(2026-10-22・戦略管制塔の依頼)
# cross-com.jp に新記事が出るたびに interventions.csv に scope=new_article で1行記録する。
# note に seo-agent の確認の形で「実験用プロンプトとの重なり：強0」「弱：E16（…）」と書く(強・弱の E番号)。
# 46本の実験用プロンプトに答えうる新記事は、AI が46本の代わりに引用しうる(横取り)。
# 強・弱の E番号は常に出し、組ごとの本数は 11/2 の短期判定から出す。表示だけで、判定の数値には使わない。
# 重なりの記載が無い行は、旧い書き方「実験用プロンプトに答えうる：E16」(＝強)／「なし」／「要確認」を読む
# --------------------------------------------------------------------------
NEW_ARTICLE_SCOPE = "new_article"
ANSWERABLE_LABEL = "実験用プロンプトに答えうる"
OVERLAP_LABEL = "実験用プロンプトとの重なり"
POACHING_HEADING = "新記事の横取りのおそれ（46本の実験用プロンプトに答えうる新記事）"
_ANSWERABLE = re.compile(ANSWERABLE_LABEL + r"[：:]\s*([^。\n]*)")
_EID = re.compile(r"E\d{2}")


def _ids_in_order(text):
    return list(dict.fromkeys(_EID.findall(text)))


def new_article_overlap(row):
    """("known", 強の E番号, 弱の E番号) ／ ("unknown", [], [])。強・弱は note に出てくる順。

    「実験用プロンプトとの重なり：」があれば、そこから「・公開」までを読む：「弱」より前が強、「弱」から後が弱。
    無ければ旧い書き方「実験用プロンプトに答えうる：…」(E番号は強・「なし」は重なりなし・それ以外は要確認)。
    """
    note = str(row.get("note") or "")
    at = note.rfind(OVERLAP_LABEL)
    if at >= 0:
        part = note[at + len(OVERLAP_LABEL):]
        stop = part.find("・公開")
        part = part if stop < 0 else part[:stop]
        weak_at = part.find("弱")
        strong_text, weak_text = (part, "") if weak_at < 0 else (part[:weak_at], part[weak_at:])
        strong = _ids_in_order(strong_text)
        return "known", strong, [i for i in _ids_in_order(weak_text) if i not in strong]
    m = _ANSWERABLE.search(note)
    if not m:
        return "unknown", [], []
    ids = _ids_in_order(m.group(1))
    if ids:
        return "known", ids, []
    if m.group(1).strip().startswith("なし"):
        return "known", [], []
    return "unknown", [], []


def overlap_text(strong, weak):
    """「強0・弱（E16・E22）」の形。"""
    fmt = lambda name, ids: f"{name}（{'・'.join(ids)}）" if ids else f"{name}0"  # noqa: E731
    return fmt("強", strong) + "・" + fmt("弱", weak)


def new_article_rows(rows):
    return [r for r in rows if scope_key(r.get("scope")) == NEW_ARTICLE_SCOPE]


def _new_article_slug(row):
    desc = str(row.get("description") or "")
    return desc.split("：", 1)[1].strip() if "：" in desc else desc


def print_new_article_poaching(overlap, blind, groups=None):
    """判定期間に日付が重なる新記事と、46本の実験用プロンプトとの重なり(強・弱)。組ごとは 11/2 から。"""
    news = new_article_rows(overlap)
    print(f"### {POACHING_HEADING}")
    if not news:
        print("判定期間に公開された新記事（scope=new_article）の記録なし\n")
        return
    judged = [(r, *new_article_overlap(r)) for r in news]
    strong = list(dict.fromkeys(i for _, k, st, _ in judged for i in st))
    weak = [i for i in dict.fromkeys(i for _, k, _, wk in judged for i in wk) if i not in strong]
    unknown = [r for r, k, _, _ in judged if k == "unknown"]
    print(f"判定期間に公開された新記事 {len(news)}本。46本の実験用プロンプトとの重なり：{overlap_text(strong, weak)}"
          + (f"・重なりが要確認 {len(unknown)}本（{'・'.join(r['intervention_id'] for r in unknown)}）" if unknown else ""))
    for r, k, st, wk in judged:
        print(f"- {r['intervention_id']} {_new_article_slug(r)}：" + (overlap_text(st, wk) if k == "known" else "要確認"))
    if (strong or weak) and blind:
        print(f"組ごとの本数は {GROUP_BLIND_UNTIL} の短期判定まで出さない")
    elif strong or weak:
        groups = load_allocation() if groups is None else groups
        by_id = {a["id"]: a["slug"] for a in load_pool()}
        for name, ids in (("強", strong), ("弱", weak)):
            if ids:
                by = collections.Counter(groups.get(by_id.get(i), "（割付なし）") for i in ids)
                print(f"{name}の E番号の組：" + "・".join(f"{g} {by.get(g, 0)}本" for g in GROUP_ORDER))
    print("※ 表示だけで、判定の数値には使わない\n")


# --------------------------------------------------------------------------
# 観測の欠測の注記（2026-10-22・戦略管制塔との決まりに合わせて追加）
# 日ごとの観測計画（settings.experiment_plan）と、実際に答えの取れた行を突き合わせ、抜けた日の日付と理由を自動で出す。
# 理由は実験日誌（data/experiment_journal.csv）→ llm_experiment の error 列 の順に見る。どちらにも無ければ「記録なし」
# （ジョブが動かなかった日は、行も日誌も残らないため）。組は出さない（11/2 より前でも出してよい内容だけ）
# --------------------------------------------------------------------------
GAP_HEADING = "観測の欠測（Gemini・日ごとの計画に対して観測できなかった分）"
JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "experiment_journal.csv")
GAP_REASON_LABELS = {"quota": "枠切れ（429）", "unavailable": "一時的な混雑・時間切れ（503）",
                     "permanent": "認証・権限・課金のエラー", "error": "例外", "skipped": "投げなかった"}
GAP_NO_RECORD = "記録なし（その日の行も実験日誌の記録も無い。ジョブが動かなかった可能性）"
# 今の本数の決まり(月水金日16本・日次の実消費を待って引く。2026-09-21 13:25 に入った)で動いた最初の日。
# これより前の日は、今の計画で数え直すと当時の本数と合わない(9/20・9/21 は14本の決まりで動いた)ので、
# 行か実験日誌に記録のある観測だけを計画として扱う(記録の無い分は「記録なし」にしない)
GAP_PLAN_FROM = "2026-09-22"
GAP_CYCLE_START = "2026-09-19"   # 日ごとの計画(settings.EXPERIMENT_CYCLE_START)が始まった日。これより前は数えない


def read_journal(path=None):
    """実験日誌の行（無ければ空）。"""
    path = path or JOURNAL_FILE
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def gap_reason(code, detail=""):
    """欠測の理由コード（collect_llm.REASON_*）と詳細を、注記の短い文にする。"""
    code = str(code or "").strip()
    if code != "skipped":
        return GAP_REASON_LABELS.get(code, code or "理由不明")
    text = str(detail or "").strip()
    if text.startswith("time_budget"):
        return "投げなかった（時間の予算切れ）"
    head, sep, rest = text.partition(":")
    why = rest.strip() if head.strip() == "skipped" else (f"{head.strip()}：{rest.strip()}" if sep else text)
    why = why.split("。")[0][:60]
    return f"投げなかった（{why}）" if why else GAP_REASON_LABELS["skipped"]


def _default_plan(date):
    import settings
    return [p["id"] for p in settings.experiment_plan(date).get("gemini") or []]


def observation_gaps(rows, spans, journal=(), plan=None, today=None):
    """期間の各日（今日より前）について、計画のうち答えの取れなかった本数と理由。
    返り値は [(日付, 計画の本数, 観測できた本数, {理由: 本数})]（欠測のある日だけ・日付順）。"""
    import collect_llm
    plan = plan or _default_plan
    today = today or _now_jst().date()
    ok = collections.defaultdict(set)
    row_errors = {}
    for r in rows:
        if not str(r.get("model", "")).lower().startswith("gemini"):
            continue
        key = (str(r.get("date", ""))[:10], str(r.get("experiment_id", "")).strip())
        err = str(r.get("error", "") or "").strip()
        if err:
            row_errors[key] = err
        else:
            ok[key[0]].add(key[1])
    logged = {}
    for j in journal:
        if str(j.get("model", "")).lower().startswith("gemini"):
            logged[(str(j.get("date", ""))[:10], str(j.get("experiment_id", "")).strip())] = (
                j.get("reason", ""), j.get("detail", ""))
    dates = set()
    for start, end in spans:
        d, last = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
        while d <= last and d < today:
            if d.isoformat() >= GAP_CYCLE_START:
                dates.add(d.isoformat())
            d += datetime.timedelta(days=1)
    out = []
    for d in sorted(dates):
        if d < GAP_PLAN_FROM:
            planned = sorted({e for (day, e) in list(row_errors) + list(logged) if day == d} | ok[d])
        else:
            planned = list(plan(d))
        missing = [e for e in planned if e not in ok[d]]
        if not missing:
            continue
        reasons = collections.Counter()
        for e in missing:
            if (d, e) in logged:
                reasons[gap_reason(*logged[(d, e)])] += 1
            elif (d, e) in row_errors:
                err = row_errors[(d, e)]
                # 投げなかった行(skipped: …・job_timeout: …)は collect_llm.miss_reason では「例外」になるので先に見る
                code = "skipped" if err.startswith(("skipped", "job_timeout")) else collect_llm.miss_reason(err)
                reasons[gap_reason(code, err)] += 1
            else:
                reasons[GAP_NO_RECORD] += 1
        out.append((d, len(planned), len(planned) - len(missing), dict(reasons)))
    return out


def print_observation_gaps(rows, spans, journal=None, plan=None, today=None):
    """判定レポートの注記：観測の抜けた日の日付と理由。"""
    gaps = observation_gaps(rows, spans, read_journal() if journal is None else journal, plan, today)
    print(f"### {GAP_HEADING}")
    if not gaps:
        print("期間中（今日より前の日）に、計画に対する欠測は無い")
    else:
        lost = sum(n - got for _, n, got, _ in gaps)
        print(f"欠測のある日 {len(gaps)}日・欠測 {lost}本。欠測は判定に数えない（引用なし＝0 としては扱わない）")
        for d, n, got, reasons in gaps:
            parts = "・".join(f"{k} {v}本" for k, v in reasons.items())
            print(f"- {d}：計画 {n}本・観測 {got}本・欠測 {n - got}本（{parts}）")
    print(f"※ 計画は日ごとの観測計画（settings.experiment_plan）、理由は実験日誌と llm_experiment の error 列から自動で出す。"
          f"今日の分と、日ごとの計画が始まる前（{GAP_CYCLE_START} より前）の日は含めない。"
          f"{GAP_PLAN_FROM} より前の日は本数の決まりが今と違うので、行か実験日誌に記録のある観測だけを数える\n")


def _span(text):
    start, _, end = text.partition(":")
    return start, end or start


# --------------------------------------------------------------------------
# 11/2 より前は、本物のデータの組ごとの数字を計算も表示もしない（2026-10-22・本田さん指示）
# 「11/2 まで組ごとの結果を見ない」は、見た人が後の判断に引きずられないためのルール。人の注意に頼らず仕組みで止める。
# - 日付は実行した時刻（JST・システムの時計）で決める。引数・環境変数では前倒しできない
# - 作り物のデータ（テスト）かどうかは、引数ではなく読み込むファイルの場所で決める：
#   pytest の一時フォルダ（パスに pytest-of- を含む）か、リポジトリの tests/ の下のファイルだけが作り物。
#   シート（--csv なし）と、それ以外の場所のファイルはすべて本物として扱う。
#   一時フォルダの場所は環境変数（TEMP など）で変えられるので、場所の判定には使わない
# --------------------------------------------------------------------------
_JST = datetime.timezone(datetime.timedelta(hours=9))
GROUP_BLIND_UNTIL_JST = datetime.datetime.fromisoformat(GROUP_BLIND_UNTIL).replace(tzinfo=_JST)
_TESTS_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
BLIND_MESSAGE = (f"組ごとの数字（組別の率・差・p値・感度分析の表・早期解放の判定・参考の表）は "
                 f"{GROUP_BLIND_UNTIL} 00:00 JST の短期判定まで計算も表示もしない"
                 "（組ごとの結果を途中で見ないため。本物のデータで実行したとき）")


def _now_jst():
    """実行した時刻（JST）。引数・環境変数では変えられない。"""
    return datetime.datetime.now(_JST)


def is_synthetic(path):
    """作り物のデータのファイルか（場所で決める）。シート（path が空）は本物。"""
    if not path:
        return False
    real = os.path.realpath(str(path))
    parts = real.replace("\\", "/").split("/")
    if any(p.startswith("pytest-of-") for p in parts):
        return True
    return os.path.commonpath([os.path.normcase(real), os.path.normcase(_TESTS_DIR)]) == os.path.normcase(_TESTS_DIR)


def group_blind(paths, now=None):
    """組ごとの数字を出さないか。本物のデータ（作り物でないファイルが1つでもある）で、11/2 00:00 JST より前なら True。"""
    now = _now_jst() if now is None else now
    if all(is_synthetic(p) for p in paths):
        return False
    return now < GROUP_BLIND_UNTIL_JST


def print_blind_overall(after, before, groups, pool, model):
    """11/2 より前に出してよいもの：46本全体の数字と、観測の無い記事の組別本数（結果ではない）。"""
    n = len(after)
    hit = sum(1 for _, v in after.values() if v)
    print(f"46本全体（組をまとめた数）：アフターに観測のある記事 {n}本／{len(pool)}本"
          + (f"・期間中に1回でも引用された記事 {hit}本" if model not in RATE_MODELS else ""))
    none_after = sorted(s for s in pool if s not in after)
    if none_after:
        by = collections.Counter(groups.get(s, "（割付なし）") for s in none_after)
        print(f"アフターに観測の無い記事（欠測）{len(none_after)}本：" + "・".join(f"{g} {by.get(g, 0)}本" for g in GROUP_ORDER))
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="2×2 の判定（llm_experiment）")
    ap.add_argument("--before", help="ビフォー期間 YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--after", help="アフター期間 YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--csv", help="llm_experiment を書き出した CSV（省略時はシートを読む）")
    ap.add_argument("--model", choices=MODELS, help="1モデルだけ出す（省略時は両方）")
    ap.add_argument("--journal", help="実験日誌の CSV（省略時は data/experiment_journal.csv）。欠測の注記の理由に使う")
    ap.add_argument("--probe", nargs="+", metavar="CSV",
                    help="引用プローブの結果で集計する（参考。アフター [ビフォー]）")
    a = ap.parse_args(argv)
    blind = group_blind(a.probe if a.probe else [a.csv])

    if a.probe and blind:
        print(f"※ 引用プローブ：{BLIND_MESSAGE}\n")
    elif a.probe:
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
        overlap = print_site_wide_interventions(a.before, a.after)
        print_new_article_poaching(overlap, blind, groups)
        print_link_loss_note(a.after)
        print_misinfo_fix_note(a.after)
        print_fact_correction_head(groups, _span(a.after))
        pillar_lines, pillar_parts = pillar.report_lines(_span(a.after))
        print("\n".join(pillar_lines))
        rows = read_llm_experiment(a.csv)
        pool = pool_slugs()
        late = late_appended_slugs()
        if late:
            print(f"9/15〜16 に追記の入った{len(late)}本は {LATE_BASELINE_FROM} 以降の観測だけを使う")
        watch = sum(1 for r in rows if str(r.get("experiment_flag", "")).strip() == WATCH_FLAG)
        print(f"llm_experiment {len(rows)}行（watch {watch}行とプール外・欠測は数えない）\n")
        if not a.model or a.model == "gemini":
            print_observation_gaps(rows, [_span(a.before), _span(a.after)], read_journal(a.journal))
        if blind:
            print(f"**{BLIND_MESSAGE}**\n")
        if (not a.model or a.model == "gemini") and not blind:
            print_fact_reference(rows, _span(a.after), groups, pool)
        elif not a.model or a.model == "gemini":
            print(f"### {FACT_REFERENCE_HEADING}\n{GROUP_BLIND_UNTIL} の短期判定まで出さない（組ごとの結果を途中で見ないため）\n")
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
            if blind:
                print_blind_overall(after, before, groups, pool, model)
                print(f"感度分析・早期解放・ピラーの前後・GSC 補助分析：{GROUP_BLIND_UNTIL} の短期判定まで出さない\n")
                continue
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
