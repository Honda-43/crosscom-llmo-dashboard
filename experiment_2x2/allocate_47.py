# -*- coding: utf-8 -*-
"""allocate_47.py｜46本を4組へ「制約付きくじ引き」で割り付ける（2026-09-28 実施）。

2026-09-22：プールは46本（E37 agentforce-coworker を除外。pool.py）。
ファイル名は47本時代のまま（experiment47_* の記録と揃えるため）。

なぜくじ引きに制約を付けるか
　単純な無作為だと、偏ったときに「処置の効果」と「もともとの差」を切り分けられない。
　特に 2026-09-11〜09-16 に逆リンク追記を受けた17本は、追記の有無そのものが
　引用されやすさに効く可能性がある。組に固まると処置の効果と見分けがつかない。
　だから「偏っていないくじを引くまで引き直す」。引き直した事実と採用シードを残す。

条件（全部満たす最初のシードを採用する）
　a. 各組 11〜12本（46本なので 12/12/11/11）
　b. 9/11〜9/16 に逆リンク追記を受けた記事（層の表の全件）が組間で均等（最大差1）
　c. 引用あり（--cited-from 〜 --cited-to の観測で cited_article=1 が1回以上）が組間で最大差1
　d. 2026-09 公開・2026-07 公開それぞれの本数が組間で最大差1（d-1・d-2 の2つ）
　e. **9/15〜9/16 に追記を受けた9本が各組 2〜3本（最大差1）**（2026-09-25 追加）
　　この9本はビフォー観測の途中で本文が変わっている。組に固まると、処置の効果と
　　追記の効果が分けられない。基準値もこの9本だけ 9/17 以降の観測を使う
　　（pool.LATE_BASELINE_FROM。summarize.py が自動で切る）
　f. 鮮度更新の誤り訂正の対象（pool.CORRECTION_SLUGS）は各組に最大1本
　　2026-09-22 に3本で追加し、同日 agentforce-vibes のみに、2026-09-23 に
　　agentforce-vibes・agentforce-features の2本に更新した（coworker はプールから除外し
　　watch で観測継続。features は本文1文の訂正を 9/29〜30 に入れることを了承）。
　　判定時は「2本込み／2本抜き」の両方を出す（summarize.py）。

**既定はドライラン（画面に出すだけ）**（2026-09-22）。--write を付けたときだけ
allocation_v1.csv と output/reports/experiment47_allocation_v1_20260928.md を書く。
--write を使うのは 9/28 の本番実行の1回だけ。割付表は seo-agent の apply_gate が
9/29〜30 の処置の通し判定に読むので、試しに書くと本番前に処置群が確定してしまう。

usage:
  # 9/28 の本番（この1回だけ --write）
  python experiment_2x2/allocate_47.py --seed-start 20260928 \
      --cited-from 2026-09-15 --cited-to 2026-09-27 --write
  # 確認（書かない。既定）
  python experiment_2x2/allocate_47.py --cited-to 2026-09-22
  # 観測を取りに行かず、手元のCSVで試すとき（列: target_url,cited_article）
  python experiment_2x2/allocate_47.py --cited-csv <path>
"""
import argparse
import csv
import datetime
import io
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import (ALLOCATION_CSV, CORRECTION_SLUGS, EXCLUDED,  # noqa: E402
                  appended_slugs, late_appended_slugs, load_pool, read_csv, slug,
                  strata_path)

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
GROUPS = ['①対照', '②FAQのみ', '③リードのみ', '④両方']
SIZES = [12, 12, 11, 11]          # 46 = 12+12+11+11
POOL_SIZE = sum(SIZES)
# 本番の割付を書いてよい最初の日(--write はこの日より前は止まる)
ALLOCATION_DAY = datetime.date(2026, 9, 28)
FENCE = '`' * 3


def load_articles():
    """プール46本（pool.load_pool）に、公開日と層の印を足して返す。

    公開日（条件 d）だけは targets.csv の published 列から引く。targets.csv は
    観測には使わない（編集禁止リスト）。
    """
    pub = {slug(r['url']): r.get('published', '')
           for r in read_csv(os.path.join(ROOT, 'experiment_2x2', 'targets.csv'))}
    back = appended_slugs()
    late = late_appended_slugs()
    arts = []
    for r in load_pool():
        s = r['slug']
        arts.append({'id': r['id'], 'url': r['url'], 'slug': s,
                     'layer': r.get('layer', ''), 'published': pub.get(s, ''),
                     'month': pub.get(s, '')[:7], 'backlink': s in back,
                     'late_backlink': s in late,
                     'correction': s in CORRECTION_SLUGS})
    return arts, back


def load_cited(a):
    """観測から「1回でも記事が引用された」slug の集合と、その出所を返す。"""
    if a.cited_csv:
        with io.open(a.cited_csv, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        got = {slug(r['target_url']) for r in rows
               if str(r.get('cited_article', '')).strip() == '1'} - set(EXCLUDED)
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
    # 除外した記事（E37）の観測行は条件 c に数えない
    return got - set(EXCLUDED), f'llm_experiment タブ（{a.cited_from}〜{a.cited_to} の {n} 行）'


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
    res.append((f'b 逆リンク追記{sum(v)}本が組間で均等（実差 {max(v) - min(v)}）',
                max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['slug'] in cited))
    res.append((f'c 引用ありが最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['month'] == '2026-09'))
    res.append((f'd-1 2026-09公開が最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['month'] == '2026-07'))
    res.append((f'd-2 2026-07公開が最大差1（実差 {max(v) - min(v)}）', max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['late_backlink']))
    res.append((f'e 9/15〜16 の追記{sum(v)}本が各組2〜3本（実差 {max(v) - min(v)}）',
                all(2 <= x <= 3 for x in v) and max(v) - min(v) <= 1, v))
    v = vals(by(lambda a: a['correction']))
    res.append((f'f 鮮度更新の訂正対象（{"・".join(CORRECTION_SLUGS)}）が各組に最大1本',
                all(x <= 1 for x in v), v))
    return all(r[1] for r in res), res


def report(arts, assign, cited, cited_src, seed, seed_start, tried, res, a):
    lines = [f'# {len(arts)}本の割付 v1（{datetime.date.today().isoformat()}）', '',
             '「制約付きくじ引き」で作った。単純な無作為だと、偏ったときに処置の効果と',
             'もともとの差を切り分けられない。条件を満たすくじが出るまで引き直している。',
             '引き直した回数と採用シードを残すのは、後から同じ割付を再現するため。', '',
             f'- 採用シード：**{seed}**（開始 {seed_start} から {tried} 個目）',
             f'- 引用の判定：{cited_src}',
             f'- 逆リンク追記の層：{os.path.basename(strata_path())}'
             f'（9/11〜9/16 の追記 {sum(1 for x in arts if x["backlink"])}本。'
             f'うち 9/15〜16 が {sum(1 for x in arts if x["late_backlink"])}本）',
             '- 鮮度更新の訂正対象：' + '・'.join(CORRECTION_SLUGS)
             + '（訂正が未確定でも条件 f と判定の込み／抜きに含める）',
             '- プールから除外：' + '、'.join(f'{k}（{v}）' for k, v in EXCLUDED.items()),
             f'- 対象：config/prompts_experiment.csv の {len(arts)} 本', '',
             '## チェック結果', '',
             '| 条件 | 判定 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 |',
             '|---|---|---|---|---|---|']
    for name, ok, v in res:
        lines.append(f'| {name} | {"OK" if ok else "★NG"} | '
                     + ' | '.join(str(x) for x in v) + ' |')
    lines += ['', '## 割付表', '',
              '| # | id | url | 層 | 公開日 | 逆リンク追記 | 9/15〜16 の追記 | 引用あり | 訂正対象 | 組 |',
              '|---|---|---|---|---|---|---|---|---|---|']
    ordered = sorted(arts, key=lambda y: (GROUPS.index(assign[y['slug']]), y['id']))
    for i, x in enumerate(ordered, 1):
        lines.append(f'| {i} | {x["id"]} | {x["url"]} | {x["layer"]} | {x["published"]} | '
                     f'{"あり" if x["backlink"] else "—"} | '
                     f'{"あり" if x["late_backlink"] else "—"} | '
                     f'{"あり" if x["slug"] in cited else "—"} | '
                     f'{"対象" if x["correction"] else "—"} | {assign[x["slug"]]} |')
    names = '・'.join(CORRECTION_SLUGS)
    k = len(CORRECTION_SLUGS)
    lines += ['', f'## 判定時の集計（{k}本込み／{k}本抜き）', '',
              '判定は llm_experiment のみで行う（引用プローブは実験期間中は不使用）。',
              '訂正対象はアフター期間の本文に「処置」と「訂正」の両方が乗る。',
              '判定は次の2通りを必ず並べて出し、結論が食い違えば訂正の影響として扱う。', '',
              f'- **{k}本込み**：{len(arts)}本すべて',
              f'- **{k}本抜き**：{names} を除いた{len(arts) - k}本',
              '  （訂正を見送った場合も、事前に決めたとおり抜いた集計も出す）',
              '- llm_experiment の experiment_flag=watch の行（E37）は数えない', '',
              FENCE,
              'python experiment_2x2/summarize.py --before <ビフォー開始>:<ビフォー終了> '
              '--after <アフター開始>:<アフター終了>',
              FENCE,
              '（summarize.py がモデルごとに両方を出す。対象は pool.CORRECTION_SLUGS）', '',
              '## 再現方法', '', FENCE,
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
    ap.add_argument('--out-csv', default=ALLOCATION_CSV,
                    help='観測・判定が読む割付の表（id,url,group,seed）')
    ap.add_argument('--write', action='store_true',
                    help='割付表（md・csv）を書く。9/28 の本番実行のときだけ付ける')
    a = ap.parse_args()

    # 本番(9/28)より前に --write で書くと、apply_gate が読む処置群が本番前に決まってしまう。
    # 引用ありの判定(条件 c)も 9/27 までの観測がそろう前の値になる。
    if a.write and datetime.date.today() < ALLOCATION_DAY:
        print(f'★--write は {ALLOCATION_DAY.isoformat()} 以降だけ使える'
              f'（今日は {datetime.date.today().isoformat()}）。ドライランで確認すること',
              file=sys.stderr)
        return 2

    arts, _ = load_articles()
    assert len(arts) == POOL_SIZE, f'{POOL_SIZE}本のはずが {len(arts)} 本'
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
    if not a.write:
        print()
        print('\n'.join(lines[:22]))
        print('...（ドライラン。--write を付けていないので書き出していない）')
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    io.open(a.out, 'w', encoding='utf-8').write('\n'.join(lines))
    print('wrote', a.out)
    # 観測（llmo_probe の group 列）と判定が読む機械用の表
    with io.open(a.out_csv, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id', 'url', 'group', 'seed'])
        for x in sorted(arts, key=lambda y: y['id']):
            w.writerow([x['id'], x['url'], assign[x['slug']], seed])
    print('wrote', a.out_csv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
