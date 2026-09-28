# -*- coding: utf-8 -*-
"""before_stability.py｜ビフォー期間の揺れの幅（2026-09-28 新設）。

なぜ見るか
　処置が無くても、引用率は日によって動く。ビフォー期間を前半・後半に分けて
　同じ指標がどれだけ動くかを出しておけば、アフターとの差を読むときに
　「処置が無くても出る揺れ」の目安になる。

数え方
　- llm_experiment のプール46本だけ。watch（E37）・プール外・error の行は数えない
　　（summarize.counted と同じ）
　- 9/15〜16 に変更の入った記事は pool.baseline_start 以降だけ使う
　- 観測単位：1行を1とした率／記事単位：半期に1回以上 =1 だった記事の割合（判定と同じ）
　- 組は allocation_v1.csv

usage:
  python experiment_2x2/before_stability.py                    # シートを読む
  python experiment_2x2/before_stability.py --csv llm_experiment.csv
"""
import argparse
import collections
import datetime
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import summarize  # noqa: E402
from pool import (EXCLUDED, ROOT, baseline_start, late_appended_slugs,  # noqa: E402
                  load_allocation, pool_slugs, slug)

HALVES = [('前半', '2026-09-17', '2026-09-22'), ('後半', '2026-09-23', '2026-09-27')]
MODELS = ('gemini', 'claude')
GROUPS = ['①対照', '②FAQのみ', '③リードのみ', '④両方']
OUT = os.path.join(ROOT, 'output', 'reports', 'experiment47_before_stability_20260928.md')
ARTICLE, DOMAIN = 5, 6            # 観測タプルの位置


def collect(rows, halves=HALVES, pool=None, groups=None):
    """(観測のリスト, 数えなかった行の内訳)。

    観測は (model, 半期, 組, slug, date, cited_article, cited_domain)。
    """
    pool = pool_slugs() if pool is None else pool
    groups = load_allocation() if groups is None else groups
    obs, dropped = [], collections.Counter()
    for r in rows:
        d = str(r.get('date', ''))[:10]
        half = next((h for h, a, b in halves if a <= d <= b), None)
        if half is None or r.get('model') not in MODELS:
            continue
        s = slug(r.get('target_url', ''))
        if str(r.get('experiment_flag', '')).strip() == summarize.WATCH_FLAG:
            dropped['watch'] += 1
            continue
        if s not in pool or s in EXCLUDED:
            dropped['プール外'] += 1
            continue
        if str(r.get('error', '')).strip():
            dropped[f'error（{r.get("model")} {d[5:]}）'] += 1
            continue
        lim = baseline_start(s)
        if lim and d < lim:
            dropped['基準日より前'] += 1
            continue
        obs.append((r['model'], half, groups.get(s, '（割付なし）'), s, d,
                    str(r.get('cited_article', '')).strip() == '1',
                    str(r.get('cited_domain', '')).strip() == '1'))
    return obs, dropped


def by_row(sub, idx):
    """(分子, 分母)。1行を1とする。"""
    return sum(1 for o in sub if o[idx]), len(sub)


def by_article(sub, idx):
    """(分子, 分母)。半期に1回でも =1 なら、その記事を1とする。"""
    hit = collections.defaultdict(bool)
    for o in sub:
        hit[o[3]] |= o[idx]
    return sum(hit.values()), len(hit)


def fmt(n, d):
    return f'{n / d * 100:.1f}%（{n}/{d}）' if d else '—'


METRICS = (('cited_article（観測単位）', ARTICLE, by_row),
           ('cited_domain（観測単位）', DOMAIN, by_row),
           ('cited_article（記事単位）', ARTICLE, by_article),
           ('cited_domain（記事単位）', DOMAIN, by_article))


def table(obs, title, per_group, halves=HALVES):
    out = [f'## {title}', '',
           '| モデル | 組 | 指標 | 前半 | 後半 | 差（後半−前半） |', '|---|---|---|---|---|---|']
    for m in MODELS:
        for g in (GROUPS if per_group else ['全体']):
            for label, idx, f in METRICS:
                cells, rates = [], []
                for h, _, _ in halves:
                    sub = [o for o in obs if o[0] == m and o[1] == h
                           and (g == '全体' or o[2] == g)]
                    n, d = f(sub, idx)
                    cells.append(fmt(n, d))
                    rates.append(n / d * 100 if d else None)
                diff = f'{rates[1] - rates[0]:+.1f}pt' if None not in rates else '—'
                out.append(f'| {m} | {g} | {label} | {cells[0]} | {cells[1]} | {diff} |')
    return out + ['']


def render(obs, dropped, source, halves=HALVES):
    (h1, a1, b1), (h2, a2, b2) = halves
    late = late_appended_slugs()
    lines = [
        '# ビフォー期間の揺れの幅（2026-09-28）', '',
        f'ビフォー期間 {a1}〜{b2} の llm_experiment を{h1}（{a1[5:]}〜{b1[5:]}）と'
        f'{h2}（{a2[5:]}〜{b2[5:]}）に分け、',
        '同じ指標が半分ずつでどれだけ動くかを見る。アフターとの差を読むときの「処置が無くても出る揺れ」の目安。', '',
        '## 数え方', '',
        f'- 出典：{source}',
        '- 対象：プール46本。experiment_flag=watch（E37）、プール外、error のある行は数えない',
        f'- 9/15〜16 に変更の入った{len(late)}本（条件 e）は 09-17 以降のみ使う'
        '（この期間はすべて 09-17 以降なので実質除外なし）',
        '- 組は allocation_v1.csv',
        '- **観測単位**：1行（1記事×1回の問い合わせ）を1とした率。分母は行数',
        '- **記事単位**：その半期に1回以上 cited_article（または cited_domain）=1 だった記事の割合。'
        '判定（summarize.py）と同じ数え方',
        '- 数えなかった行：' + ('／'.join(f'{k} {v}行' for k, v in sorted(dropped.items()))
                          if dropped else 'なし'),
        '- 注意：Gemini は日ごとに一部の記事だけを回すため、半期ごとに観測できた記事数が違う（下の表）。'
        'Claude は3〜4日おきに全件を回すので、半期ごとの回数がそろわない。'
        '記事単位の率は観測回数が多い半期で高めに出やすい',
        '- 組ごとの分母は小さく、1件で数pt〜10pt 動く', '',
        '## 観測日と行数', '', '| モデル | 半期 | 観測日 | 行数 | 記事数 |', '|---|---|---|---|---|']
    for m in MODELS:
        for h, _, _ in halves:
            sub = [o for o in obs if o[0] == m and o[1] == h]
            days = sorted({o[4] for o in sub})
            lines.append(f'| {m} | {h} | {"・".join(d[5:] for d in days)} | '
                         f'{len(sub)} | {len({o[3] for o in sub})} |')
    lines.append('')
    lines += table(obs, 'モデル別（全体）', per_group=False, halves=halves)
    lines += table(obs, '組別（①〜④）', per_group=True, halves=halves)
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description='ビフォー期間の揺れの幅')
    ap.add_argument('--csv', help='llm_experiment を書き出した CSV（省略時はシートを読む）')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args(argv)
    rows = summarize.read_llm_experiment(a.csv)
    source = (f'llm_experiment（{os.path.basename(a.csv)}）' if a.csv
              else f'llm_experiment タブ（{datetime.date.today().isoformat()} 取得）')
    obs, dropped = collect(rows)
    lines = render(obs, dropped, source)
    io.open(a.out, 'w', encoding='utf-8').write('\n'.join(lines))
    print('\n'.join(lines))
    print('wrote', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
