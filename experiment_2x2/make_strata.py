# -*- coding: utf-8 -*-
"""make_strata.py｜逆リンク追記を受けた17本を、便GL の記録から層の表に起こす。

割付の層（b の条件）に使う。記録そのものは crosscom-seo-agent 側にあるが、
割付は**この手元のファイルだけで再現できる**必要があるため、csv に落として持つ。
"""
import csv, io, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import EXCLUDED, pool_slugs  # noqa: E402

SRC = os.environ.get(
    "BUNGL_RECORD",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                 'crosscom-seo-agent', 'output', 'reports',
                 'bunGL_experiment48_append_record_20260917.md'))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'strata_backlink17.csv')

text = io.open(SRC, encoding='utf-8').read()
rows = []
for line in text.splitlines():
    if not line.startswith('| ') or 'https://cross-com.jp/' not in line:
        continue
    c = [x.strip() for x in line.strip('|').split('|')]
    if len(c) < 8 or not c[0].isdigit():
        continue
    url = c[1]
    rows.append({
        'slug': url.rstrip('/').split('/')[-1],
        'url': url,
        'post_id': c[3],
        'appended_at': c[4],
        'backlinks': c[5],
        'parents': c[6].replace('<br>', ' ; '),
    })
assert rows, '記録の表を読めていない'
# プール（46本）に無い記事は層に入れない（9/22 に E37 を除外。17本には元々含まれない）
pool = pool_slugs()
dropped = [r['slug'] for r in rows if r['slug'] in EXCLUDED or r['slug'] not in pool]
rows = [r for r in rows if r['slug'] not in dropped]
if dropped:
    print('プール外のため除いた:', ', '.join(dropped))
with io.open(OUT, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['slug', 'url', 'post_id', 'appended_at', 'backlinks', 'parents'])
    w.writeheader(); w.writerows(rows)
print(f'{len(rows)} 本 → {OUT}')
print('合計リンク本数:', sum(int(r['backlinks']) for r in rows))
