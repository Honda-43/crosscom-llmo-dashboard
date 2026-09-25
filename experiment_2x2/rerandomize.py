# -*- coding: utf-8 -*-
"""rerandomize.py｜再ランダム化検定（条件付き並べ替え検定）（2026-09-25 新設）。

なぜ必要か
　9/28 の割付は「条件 a〜g を満たすくじを引くまで引き直す」方法で選ぶ。条件の
　合格率は約 1/9,200 で、取りうる割付のごく一部しか使っていない。普通の検定
　（フィッシャー正確検定）は「どの割付も等しく起こりえた」前提で p値を出すので、
　この引き方には合わない。**同じ条件 a〜g を満たす割付の中だけ**で、実際の差以上の
　差がどれくらい出るかを数える。条件を足したり緩めたりはしない。

使い方
  # 判定用の割付プール（5,000通り）を作る。9/28 の割付が決まったあとに1回だけ
  python experiment_2x2/rerandomize.py --build --cited-from 2026-09-15 --cited-to 2026-09-27
  # 中身の確認
  python experiment_2x2/rerandomize.py --show

プールは results/rerandomization_pool.csv に保存し、判定のたびに読み直す
（同じ p値が何度でも再現できるようにするため。作り直しは --build で明示したときだけ）。
"""
import argparse
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import allocate_47  # noqa: E402
from pool import load_allocation, slug  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(HERE, 'results', 'rerandomization_pool.csv')
POOL_SIZE = 5000
SEED_START = 20290101
# 9/28 の本番と同じ範囲（条件 c の「引用あり」をこの期間で決める）
CITED_FROM, CITED_TO = '2026-09-15', '2026-09-27'
GROUPS = allocate_47.GROUPS
LEAD_ON, LEAD_OFF = ('③リードのみ', '④両方'), ('①対照', '②FAQのみ')
FAQ_ON, FAQ_OFF = ('②FAQのみ', '④両方'), ('①対照', '③リードのみ')


# --------------------------------------------------------------------------
# 条件 a〜g（allocate_47.check と同じ判定を、数えるだけの形にしたもの）
# --------------------------------------------------------------------------
def features(arts, cited):
    """記事ごとの (b, c, d1, d2, e, f, g) の該当フラグ。"""
    return [(a['backlink'], a['slug'] in cited, a['month'] == '2026-09',
             a['month'] == '2026-07', a['late_backlink'], a['correction'],
             a['title_changed']) for a in arts]


def fast_ok(labels, feats, totals):
    """条件 b〜g を満たすか。a は本数の組み方（12/12/11/11）で必ず満たす。

    allocate_47.check と同じ判定。速さのために Counter を使わず、
    いちばん厳しい b から見て、外れた時点で止める。
    """
    counts = [[0] * 7 for _ in range(4)]
    for g, f in zip(labels, feats):
        row = counts[g]
        if f[0]: row[0] += 1
        if f[1]: row[1] += 1
        if f[2]: row[2] += 1
        if f[3]: row[3] += 1
        if f[4]: row[4] += 1
        if f[5]: row[5] += 1
        if f[6]: row[6] += 1
    for i in (0, 1, 2, 3):                      # b・c・d-1・d-2: 最大差1
        v = [counts[g][i] for g in range(4)]
        if max(v) - min(v) > 1:
            return False
    v = [counts[g][4] for g in range(4)]        # e: 各組2〜3本かつ最大差1
    if not all(2 <= x <= 3 for x in v) or max(v) - min(v) > 1:
        return False
    for i in (5, 6):                            # f・g: 各組に最大1本
        if any(counts[g][i] > 1 for g in range(4)):
            return False
    return True


def assignment_of(arts, assign):
    """{slug: 組} を、記事の並び順どおりの組番号の文字列にする。"""
    return ''.join(str(GROUPS.index(assign[a['slug']]) + 1) for a in arts)


def labels_of(text):
    return [int(c) - 1 for c in text.strip()]


# --------------------------------------------------------------------------
# プールを作る・読む
# --------------------------------------------------------------------------
def build(arts, cited, actual, size=POOL_SIZE, seed_start=SEED_START, progress=None):
    """条件 a〜g を満たす割付を ``size`` 通り作る。実際の割付と同じものは入れない。"""
    feats = features(arts, cited)
    totals = [sum(f[i] for f in feats) for i in range(7)]
    got, seed, tried = [], seed_start, 0
    while len(got) < size:
        labels = [GROUPS.index(g) for g in
                  (allocate_47.allocate(arts, seed)[a['slug']] for a in arts)]
        tried += 1
        if fast_ok(labels, feats, totals):
            text = ''.join(str(x + 1) for x in labels)
            if text != actual:
                got.append((seed, text))
                if progress and len(got) % progress == 0:
                    print(f'  {len(got)}/{size}（{tried:,}回試行）', flush=True)
        seed += 1
    return got, tried, seed


def save(rows, arts, meta, path=POOL_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('# 再ランダム化検定の割付プール。条件 a〜g を満たす割付だけが入っている。\n')
        f.write('# assignment は記事の並び順（config/prompts_experiment.csv）の組番号。\n')
        f.write(f'# 1=①対照 2=②FAQのみ 3=③リードのみ 4=④両方 / 記事 {len(arts)}本\n')
        for k, v in meta.items():
            f.write(f'# {k}: {v}\n')
        w = csv.writer(f)
        w.writerow(['perm_id', 'seed', 'assignment'])
        for i, (seed, text) in enumerate(rows, 1):
            w.writerow([i, seed, text])
    return path


def load(path=POOL_FILE):
    """保存したプール。[(seed, 組番号の文字列), ...]。無ければ空。"""
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith('#')))
    return [(int(r['seed']), r['assignment']) for r in rows]


# --------------------------------------------------------------------------
# 検定
# --------------------------------------------------------------------------
def effects(labels, outcomes):
    """(リードの主効果, FAQの主効果)。outcomes は記事の並び順の 0/1（引用あり）。

    観測の無い記事(None)は数えない。片側に観測が1本も無いときの率は 0 とする
    (summarize のフィッシャー側と同じ約束)。
    """
    hit = [0] * 4
    n = [0] * 4
    for g, v in zip(labels, outcomes):
        if v is None:
            continue
        n[g] += 1
        hit[g] += v

    def rate(groups):
        a = sum(hit[GROUPS.index(g)] for g in groups)
        b = sum(n[GROUPS.index(g)] for g in groups)
        return (a / b) if b else 0.0
    return (rate(LEAD_ON) - rate(LEAD_OFF), rate(FAQ_ON) - rate(FAQ_OFF))


def p_values(pool, actual_labels, outcomes):
    """片側p。実際の差以上の差が、同じ条件を満たす割付の何割で出るか。"""
    lead_actual, faq_actual = effects(actual_labels, outcomes)
    lead_hits = faq_hits = 0
    for _, text in pool:
        lead, faq = effects(labels_of(text), outcomes)
        lead_hits += lead >= lead_actual
        faq_hits += faq >= faq_actual
    n = len(pool)
    return {
        'n': n,
        'lead_diff': lead_actual, 'lead_p': (lead_hits / n) if n else float('nan'),
        'faq_diff': faq_actual, 'faq_p': (faq_hits / n) if n else float('nan'),
    }


def outcomes_for(arts, cited_any, exclude=()):
    """記事の並び順の 0/1。観測が無い記事と ``exclude`` は None（数えない）。"""
    return [None if (a['slug'] in exclude or a['slug'] not in cited_any)
            else int(cited_any[a['slug']]) for a in arts]


def main(argv=None):
    ap = argparse.ArgumentParser(description='再ランダム化検定の割付プール')
    ap.add_argument('--build', action='store_true', help='プールを作り直す')
    ap.add_argument('--show', action='store_true', help='保存済みのプールの概要を出す')
    ap.add_argument('--size', type=int, default=POOL_SIZE)
    ap.add_argument('--seed-start', type=int, default=SEED_START)
    ap.add_argument('--cited-from', default=CITED_FROM)
    ap.add_argument('--cited-to', default=CITED_TO)
    ap.add_argument('--cited-csv', default='')
    ap.add_argument('--out', default=POOL_FILE)
    a = ap.parse_args(argv)

    if a.show or not a.build:
        rows = load(a.out)
        if not rows:
            print(f'プールがまだ無い: {a.out}', file=sys.stderr)
            print('  9/28 の割付が決まったあとに --build で作る', file=sys.stderr)
            return 2
        print(f'{len(rows)} 通り / シード {rows[0][0]}〜{rows[-1][0]} / {a.out}')
        return 0

    arts, _ = allocate_47.load_articles()
    groups = load_allocation()
    if not groups:
        print('★ allocation_v1.csv が無い（9/28 の割付の前）。'
              '実際の割付が決まってからプールを作る', file=sys.stderr)
        return 2
    actual = ''.join(str(GROUPS.index(groups[a_['slug']]) + 1) for a_ in arts)
    cited, src = allocate_47.load_cited(argparse.Namespace(
        cited_csv=a.cited_csv, cited_from=a.cited_from, cited_to=a.cited_to))
    print(f'条件 c の引用あり: {len(cited)}本（{src}）')
    rows, tried, last = build(arts, cited, actual, a.size, a.seed_start, progress=500)
    path = save(rows, arts, {
        'size': len(rows), 'seed_start': a.seed_start, 'seed_last': last - 1,
        'tried': tried, 'cited': f'{a.cited_from}〜{a.cited_to}（{len(cited)}本）',
        'excluded_actual': actual,
    }, a.out)
    print(f'{len(rows)} 通り（{tried:,}回試行）→ {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
