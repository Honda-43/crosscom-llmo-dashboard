# -*- coding: utf-8 -*-
"""allocate_47.py｜47本を4組へ「制約付きくじ引き」で割り付ける（2026-09-28 実施）。

なぜくじ引きに制約を付けるか
　単純な無作為だと、偏ったときに「処置の効果」と「もともとの差」を切り分けられない。
　特に 2026-09-11〜09-16 に逆リンク追記を受けた17本は、追記の有無そのものが
　引用されやすさに効く可能性がある。組に固まると処置の効果と見分けがつかない。
　だから「偏っていないくじを引くまで引き直す」。引き直した事実と採用シードを残す。

条件（全部満たす最初のシードを採用する）
　a. 各組 11〜12本
　b. 逆リンク追記あり17本が各組 4〜5本
　c. 引用あり（--cited-from 〜 --cited-to の観測で cited_article=1 が1回以上）が組間で最大差1
　d. 2026-09 公開・2026-07 公開それぞれの本数が組間で最大差1

usage:
  python experiment_2x2/allocate_47.py --seed-start 20260928 \
      --cited-from 2026-09-15 --cited-to 2026-09-27
  # 観測を取りに行かず、手元のCSVで試すとき（列: target_url,cited_article）
  python experiment_2x2/allocate_47.py --cited-csv <path> --dry
"""
import argparse
import csv
import datetime
import io
import os
import random
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
GROUPS = ['①対照', '②FAQのみ', '③リードのみ', '④両方']
SIZES = [12, 12, 12, 11]          # 47 = 12+12+12+11
FENCE = '`' * 3


def slug(u):
    return u.strip().rstrip('/').split('/')[-1].lower()


def load_articles():
    """47本（config/prompts_experiment.csv）に、公開日と層の印を足して返す。"""
    pub = {}
    with io.open(os.path.join(ROOT, 'experiment_2x2', 'targets.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pub[slug(r['url'])] = r.get('published', '')
    back = set()
    p = os.path.join(ROOT, 'experiment_2x2', 'strata_backlink17.csv')
    if os.path.exists(p):
        with io.open(p, encoding='utf-8') as f:
            back = {r['slug'].lower() for r in csv.DictReader(f)}
    arts = []
    with io.open(os.path.join(ROOT, 'config', 'prompts_experiment.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            s = slug(r['url'])
            arts.append({'id': r['id'], 'url': r['url'], 'slug': s,
                         'layer': r.get('layer', ''), 'published': pub.get(s, ''),
                         'month': pub.get(s, '')[:7], 'backlink': s in back})
    return arts, back


def load_cited(a):
    """観測から「1回でも記事が引用された」slug の集合と、その出所を返す。"""
    if a.cited_csv:
        with io.open(a.cited_csv, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        got = {slug(r['target_url']) for r in rows
               if str(r.get('cited_article', '')).strip() == '1'}
        return got, f'{a.cited_csv}（{len(rows)} 行）'
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    sid = io.open(os.path.join(ROOT, 'credentials', 'spreadsheet_id.txt'),
                  encoding='utf-8').read().strip()
    creds = Credentials.from_service_account_file(
        os.path.join(ROOT, 'credentials', 'service_account.json'),
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    svc = build('sheets', 'v4', credentials=creds)
    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range="'llm_experiment'!A1:I20000").execute().get('values', [])
    idx = {h: i for i, h in enumerate(rows[0])}
    got, n = set(), 0
    for r in rows[1:]:
        if len(r) <= idx['cited_article']:
            continue
        if not (a.cited_from <= r[idx['date']] <= a.cited_to):
            continue
        n += 1
        if str(r[idx['cited_article']]).strip() == '1':
            got.add(slug(r[idx['target_url']]))
    return got, f'llm_experiment タブ（{a.cited_from}〜{a.cited_to} の {n} 行）'


def allocate(arts, seed):
    """シードから割付を作る。同じシードなら必ず同じ割付になる。"""
    rng = random.Random(seed)
    sizes = list(SIZES)
    rng.shuffle(sizes)                       # どの組が11本になるかも引く
    labels = []
    for g, n in zip(GROUPS, sizes):
        labels += [g] * n
    rng.shuffle(labels)
    return {a['slug']: g for a, g in zip(arts, labels)}


def check(arts, assign, cited):
    """(全部満たすか, [(条件名, 判定, 組ごとの値), ...]) を返す。"""
    def by(pred):
        return Counter(assign[a['slug']] for a in arts if pred(a))

    def vals(c):
        return [c.get(g, 0) for g in GROUPS]

    res = []
    v = vals(by(lambda a: True))
    res.append(('a 各組11〜12本', all(11 <= x <= 12 for x in v), v))
    v = vals(by(lambda a: a['backlink']))
    res.append(('b 逆リンク追記17本が各組4〜5本', all(4 <= x <= 5 for x in v), v))
    v = vals(by(lambda a: a['slug'] in cited))
    res.append((f'c 引用ありが最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['month'] == '2026-09'))
    res.append((f'd-1 2026-09公開が最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['month'] == '2026-07'))
    res.append((f'd-2 2026-07公開が最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    return all(r[1] for r in res), res


def report(arts, assign, cited, cited_src, seed, seed_start, tried, res, a):
    lines = [f'# 47本の割付 v1（{datetime.date.today().isoformat()}）', '',
             '「制約付きくじ引き」で作った。単純な無作為だと、偏ったときに処置の効果と',
             'もともとの差を切り分けられない。条件を満たすくじが出るまで引き直している。',
             '引き直した回数と採用シードを残すのは、後から同じ割付を再現するため。', '',
             f'- 採用シード：**{seed}**（開始 {seed_start} から {tried} 個目）',
             f'- 引用の判定：{cited_src}',
             '- 逆リンク追記あり17本：便GL の記録'
             '（crosscom-seo-agent / bunGL_experiment48_append_record_20260917.md）',
             f'- 対象：config/prompts_experiment.csv の {len(arts)} 本', '',
             '## チェック結果', '',
             '| 条件 | 判定 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 |',
             '|---|---|---|---|---|---|']
    for name, ok, v in res:
        lines.append(f'| {name} | {"OK" if ok else "★NG"} | '
                     + ' | '.join(str(x) for x in v) + ' |')
    lines += ['', '## 割付表', '',
              '| # | id | url | 層 | 公開日 | 逆リンク追記 | 引用あり | 組 |',
              '|---|---|---|---|---|---|---|---|']
    ordered = sorted(arts, key=lambda y: (GROUPS.index(assign[y['slug']]), y['id']))
    for i, x in enumerate(ordered, 1):
        lines.append(f'| {i} | {x["id"]} | {x["url"]} | {x["layer"]} | {x["published"]} | '
                     f'{"あり" if x["backlink"] else "—"} | '
                     f'{"あり" if x["slug"] in cited else "—"} | {assign[x["slug"]]} |')
    lines += ['', '## 再現方法', '', FENCE,
              f'python experiment_2x2/allocate_47.py --seed-start {seed} '
              f'--cited-from {a.cited_from} --cited-to {a.cited_to}',
              FENCE, '',
              '※ c の判定は観測データに依存する。同じ割付を出すには、同じ期間の',
              'llm_experiment を参照すること（後から行が増えると結果が変わりうる）。']
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed-start', type=int, default=20260928)
    ap.add_argument('--max-seeds', type=int, default=200000)
    ap.add_argument('--cited-from', default='2026-09-15')
    ap.add_argument('--cited-to', default='2026-09-27')
    ap.add_argument('--cited-csv', default='')
    ap.add_argument('--out', default=os.path.join(
        ROOT, 'output', 'reports', 'experiment47_allocation_v1_20260928.md'))
    ap.add_argument('--dry', action='store_true', help='ファイルを書かず結果だけ出す')
    a = ap.parse_args()

    arts, _ = load_articles()
    assert len(arts) == 47, f'47本のはずが {len(arts)} 本'
    cited, cited_src = load_cited(a)
    n_back = sum(x['backlink'] for x in arts)
    n_cit = sum(1 for x in arts if x['slug'] in cited)
    print(f'対象 {len(arts)} 本／逆リンク追記あり {n_back} 本／引用あり {n_cit} 本')

    seed, res = None, None
    for s in range(a.seed_start, a.seed_start + a.max_seeds):
        assign = allocate(arts, s)
        ok, res = check(arts, assign, cited)
        if ok:
            seed = s
            break
    if seed is None:
        print(f'★{a.max_seeds} シード試して条件を満たす割付が見つかりませんでした', file=sys.stderr)
        for name, ok, v in res:
            print(f'  {"OK " if ok else "★NG"} {name}：{dict(zip(GROUPS, v))}', file=sys.stderr)
        return 1

    tried = seed - a.seed_start + 1
    assign = allocate(arts, seed)
    ok, res = check(arts, assign, cited)
    print(f'採用シード {seed}（{a.seed_start} から {tried} 個目）')
    for name, k, v in res:
        print(f'  {"OK " if k else "★NG"} {name}：{dict(zip(GROUPS, v))}')

    lines = report(arts, assign, cited, cited_src, seed, a.seed_start, tried, res, a)
    if a.dry:
        print()
        print('\n'.join(lines[:22]))
        print('...（--dry のため書き出していない）')
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    io.open(a.out, 'w', encoding='utf-8').write('\n'.join(lines))
    print('wrote', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
