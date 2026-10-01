# -*- coding: utf-8 -*-
"""gsc_pages_v2.py｜実験46本の GSC 指標を、# 付きURLを本体に寄せて作り直す（2026-10-01）。

GSC の「ページ」には、目次アンカー（#arkb-toc-N など # を含むURL）が本体とは別の行で出る。
9/14 版（seo-agent の output/articles/experiment47_gsc_pages_20260914.csv）は、
本体とアンカーの行を合算し、順位を表示回数で加重平均していた。これを次の寄せ方に改める。

- # を含むURLは、# より前の部分で本体のURLに寄せる
- 表示回数：本体の行の値のみ（アンカーの行は足さない。同じ検索結果で本体とアンカーが
  同時に表示されると二重に数えるため）
- クリック数：本体とアンカーの行を合計
- 平均掲載順位：本体の行の値のみ
- 本体の行が無くアンカーの行だけの記事は、表示回数・順位を「データなし」（空欄）とし、備考に書く

**GSC は実験の判定には使わない。** 判定時の補助分析（Google 順位の上位・下位で処置の効き方が
違うか）だけに使う（summarize.GSC_PAGES_CSV が v2 を指す）。
ホワイトペーパーの PDF・資料DLページは46本のどれでもないので、ここには入らない。

入力：experiment_2x2/gsc_pages_export_20260914.csv
　　（seo-agent の output/articles/kw_master_sheet_export_20260914.csv の写し。9/14 版の元データで、
　　　同じ方法で集計すると 9/14 版の47行と全件一致することを確かめた）
出力：output/articles/experiment46_gsc_pages_20260914_v2.csv（既にあれば止まる。--force で作り直す）

usage:
  python experiment_2x2/gsc_pages_v2.py
"""
import argparse
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SOURCE_CSV = os.path.join(HERE, 'gsc_pages_export_20260914.csv')
POOL_CSV = os.path.join(ROOT, 'config', 'prompts_experiment.csv')
OUT_CSV = os.path.join(ROOT, 'output', 'articles', 'experiment46_gsc_pages_20260914_v2.csv')
COLUMNS = ['id', 'layer', 'url', '平均掲載順位', '表示回数', 'クリック数', '備考']


def _read(path):
    with io.open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def body_url(url):
    """# より前の部分（本体のURL）。"""
    return url.split('#', 1)[0]


def merge(export_rows):
    """{本体URL: {'body': 本体の行 or None, 'anchors': [アンカーの行]}}。"""
    out = {}
    for r in export_rows:
        url = r['上位のページ'].strip()
        slot = out.setdefault(body_url(url), {'body': None, 'anchors': []})
        if '#' in url:
            slot['anchors'].append(r)
        else:
            slot['body'] = r
    return out


def article_row(article, slot):
    """1記事分の行（COLUMNS の順の dict）。"""
    row = {'id': article['id'], 'layer': article['layer'], 'url': article['url'],
           '平均掲載順位': '', '表示回数': '', 'クリック数': '', '備考': ''}
    if slot is None:
        row['備考'] = 'GSC に行なし（表示回数・順位・クリックはデータなし）'
        return row
    body, anchors = slot['body'], slot['anchors']
    clicks = sum(int(r['クリック数']) for r in anchors) + (int(body['クリック数']) if body else 0)
    row['クリック数'] = str(clicks)
    if body is None:
        row['備考'] = (f'本体の行なし（アンカーの行のみ {len(anchors)}行）。'
                     '表示回数・順位はデータなし。クリックはアンカーの行の合計')
        return row
    row['平均掲載順位'] = f"{float(body['掲載順位']):.2f}"
    row['表示回数'] = str(int(body['表示回数']))
    if anchors:
        row['備考'] = (f'#付きURLの行 {len(anchors)}行のクリック {clicks - int(body["クリック数"])}件を合算'
                     '（表示回数・順位は本体の行のみ）')
    return row


def build(export_rows, pool):
    merged = merge(export_rows)
    return [article_row(a, merged.get(body_url(a['url']).strip())) for a in pool]


def write(rows, path, force=False):
    if os.path.exists(path) and not force:
        print(f'★{os.path.relpath(path, ROOT)} が既にある。作り直すときは --force', file=sys.stderr)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {os.path.relpath(path, ROOT)}（{len(rows)}本）')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description='実験46本の GSC 指標（# 付きURLを本体に寄せる）')
    ap.add_argument('--source', default=SOURCE_CSV)
    ap.add_argument('--out', default=OUT_CSV)
    ap.add_argument('--force', action='store_true', help='既にある v2 を作り直す')
    a = ap.parse_args(argv)
    pool = _read(POOL_CSV)
    rows = build(_read(a.source), pool)
    return 0 if write(rows, a.out, a.force) else 3


if __name__ == '__main__':
    sys.exit(main())
