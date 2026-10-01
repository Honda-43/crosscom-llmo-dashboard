# -*- coding: utf-8 -*-
"""gsc_rank_split.py｜GSC 補助分析の上位・下位の分け方（事前登録・2026-10-01）。

アフターのデータを見る前に、46本を Google 順位の上位・下位に分けて固定する。
判定（cited_article）には使わない。summarize.py の補助分析（探索的）だけが読む。

分け方（2026-10-01 に事前固定）：
- 対象：統計46本（E37 を除く）。入力は output/articles/experiment46_gsc_pages_20260914_v2.csv
- 表示回数が20未満の記事は「下位」（順位が不確かで、Google でほとんど見られていないため）。
  表示回数が「データなし」の記事も「下位」
- 表示回数20以上の記事で平均掲載順位の中央値を出し、中央値以下（数字が小さい＝上位）を「上位」、
  中央値より大きいものを「下位」。中央値と同じ値の記事は「上位」

出力：experiment_2x2/gsc_rank_split_v1.csv（列：id, slug, impressions, position, rank_split）。
**既にあれば止まる。** --force のときだけ作り直す（事前登録を後から動かさないため）。

usage:
  python experiment_2x2/gsc_rank_split.py
"""
import argparse
import csv
import io
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
GSC_V2_CSV = os.path.join(ROOT, 'output', 'articles', 'experiment46_gsc_pages_20260914_v2.csv')
OUT_CSV = os.path.join(HERE, 'gsc_rank_split_v1.csv')
COLUMNS = ['id', 'slug', 'impressions', 'position', 'rank_split']
MIN_IMPRESSIONS = 20
UPPER, LOWER = '上位', '下位'


def _num(value, cast):
    return cast(value) if str(value).strip() else None


def split(rows):
    """(分類の行, 中央値)。rows は v2 の行。"""
    items = [{'id': r['id'], 'slug': r['url'].rstrip('/').rsplit('/', 1)[-1],
              'impressions': _num(r['表示回数'], int), 'position': _num(r['平均掲載順位'], float)}
             for r in rows]
    seen = [x for x in items if (x['impressions'] or 0) >= MIN_IMPRESSIONS and x['position'] is not None]
    median = statistics.median(x['position'] for x in seen) if seen else None
    for x in items:
        ok = (x['impressions'] or 0) >= MIN_IMPRESSIONS and x['position'] is not None
        x['rank_split'] = UPPER if ok and x['position'] <= median else LOWER
    return items, median


def write(items, path, force=False):
    if os.path.exists(path) and not force:
        print(f'★{os.path.relpath(path, ROOT)} が既にある（事前登録した分け方）。作り直すときは --force',
              file=sys.stderr)
        return False
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for x in items:
            w.writerow({'id': x['id'], 'slug': x['slug'],
                        'impressions': '' if x['impressions'] is None else x['impressions'],
                        'position': '' if x['position'] is None else f"{x['position']:.2f}",
                        'rank_split': x['rank_split']})
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description='GSC 補助分析の上位・下位（事前登録）')
    ap.add_argument('--source', default=GSC_V2_CSV)
    ap.add_argument('--out', default=OUT_CSV)
    ap.add_argument('--force', action='store_true', help='既にある分類を作り直す')
    a = ap.parse_args(argv)
    with io.open(a.source, encoding='utf-8-sig') as f:
        items, median = split(list(csv.DictReader(f)))
    if not write(items, a.out, a.force):
        return 3
    few = sum(1 for x in items if (x['impressions'] or 0) < MIN_IMPRESSIONS)
    upper = sum(1 for x in items if x['rank_split'] == UPPER)
    print(f'wrote {os.path.relpath(a.out, ROOT)}：上位 {upper}本・下位 {len(items) - upper}本'
          f'（うち表示回数{MIN_IMPRESSIONS}未満で下位 {few}本）・順位の中央値 {median:.2f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
