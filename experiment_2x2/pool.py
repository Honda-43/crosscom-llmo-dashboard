# -*- coding: utf-8 -*-
"""pool.py｜実験のプール(統計の対象)と割付を1か所で読む(2026-09-22 新設)。

プールの正本は config/prompts_experiment.csv(2026-09-22 から46本)。
experiment_2x2/targets.csv は「編集禁止リスト(50本)」で、観測・割付の対象ではない。
観測(llmo_probe / resume_probe)・割付(allocate_47)・判定(summarize)・層(make_strata)は
すべてここを通して同じ46本を見る。スクリプトごとに本数がずれるのを防ぐため。
"""
import csv
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
POOL_CSV = os.path.join(ROOT, 'config', 'prompts_experiment.csv')
# 9/28 の割付の結果(allocate_47.py が書く)。観測の group 列はここから引く。
ALLOCATION_CSV = os.path.join(HERE, 'allocation_v1.csv')

# プールから外した記事と理由。統計・割付・判定のすべてから除く。
EXCLUDED = {
    'agentforce-coworker': 'E37。見出し・FAQに及ぶ誤り訂正のため 2026-09-22 に除外',
}
# 鮮度更新の誤り訂正の対象(処置と同じ日に本文の数文が差し替わる)。
# 訂正が確定していなくても、条件 f と「込み／抜き」の集計には含める。
CORRECTION_SLUGS = ('agentforce-vibes',)


def slug(u):
    return u.strip().rstrip('/').split('/')[-1].lower()


def read_csv(path):
    """# で始まる注記行を読み飛ばして DictReader で読む。"""
    with io.open(path, encoding='utf-8') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


def load_pool():
    """プールの記事(id, layer, url, prompt, slug)。E37 は CSV から除いてある。"""
    rows = read_csv(POOL_CSV)
    out = []
    for r in rows:
        s = slug(r['url'])
        assert s not in EXCLUDED, f'{s} はプールから除外済みのはず'
        out.append(dict(r, slug=s))
    return out


def pool_slugs():
    return {a['slug'] for a in load_pool()}


def load_allocation(path=ALLOCATION_CSV):
    """{slug: 組}。割付前(9/28 より前)は空。"""
    if not os.path.exists(path):
        return {}
    return {slug(r['url']): r['group'] for r in read_csv(path)}
