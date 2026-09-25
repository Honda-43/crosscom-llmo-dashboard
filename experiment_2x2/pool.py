# -*- coding: utf-8 -*-
"""pool.py｜実験のプール(統計の対象)と割付を1か所で読む(2026-09-22 新設)。

プールの正本は config/prompts_experiment.csv(2026-09-22 から46本)。
experiment_2x2/targets.csv は「編集禁止リスト(50本)」で、観測・割付の対象ではない。
観測(llmo_probe / resume_probe)・割付(allocate_47)・判定(summarize)・層(make_strata)は
すべてここを通して同じ46本を見る。スクリプトごとに本数がずれるのを防ぐため。
"""
import csv
import glob
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
POOL_CSV = os.path.join(ROOT, 'config', 'prompts_experiment.csv')
# 9/28 の割付の結果(allocate_47.py が書く)。観測の group 列はここから引く。
ALLOCATION_CSV = os.path.join(HERE, 'allocation_v1.csv')

# プールから外した記事と理由。統計・割付・判定のすべてから除く。
# E37 は観測だけ続ける(config/prompts_watch.csv・llm_experiment の experiment_flag=watch)。
EXCLUDED = {
    'agentforce-coworker': 'E37。見出し・FAQに及ぶ誤り訂正のため 2026-09-22 に除外',
}
# 引用プローブ(llmo_probe.py)の 2026-09-17 の観測(results/2026-09-17.csv・144行)は、
# 判定のビフォー(基準値)に使わない。9/22 に質問文を targets.csv の query から
# prompts_experiment.csv の prompt に切り替えたため、46本すべてで質問が異なる。
# 判定に使うビフォーは、新しい質問文で処置反映(9/29〜30)より前に取り直した回だけ。
PROBE_BASELINE_EXCLUDED = ('2026-09-17',)

# 鮮度更新の誤り訂正の対象(処置と同じ日に本文の数文が差し替わる)。
# 訂正が確定していなくても、条件 f と「込み／抜き」の集計には含める。
# 2026-09-23: features の本文1文の訂正(9/29〜30)を了承したため2本に戻した。
CORRECTION_SLUGS = ('agentforce-vibes', 'agentforce-features')


# 逆リンク追記の層(くじ引きの条件 b・e とビフォー基準値に使う)。
# 制作管制の表で作り直したら strata_backlink_YYYYMMDD.csv に置き換える。
# 新しい名前があればそちらを使う(日付の新しいものが正)。
STRATA_GLOB = os.path.join(HERE, 'strata_backlink_*.csv')
STRATA_LEGACY = os.path.join(HERE, 'strata_backlink17.csv')
# ビフォー期間の途中(9/15〜16)に追記が入った記事は、追記より後の観測だけを基準値に使う。
# 追記そのものが引用されやすさを動かすので、追記前後を混ぜると基準値が実際とずれる。
LATE_APPEND_FROM = '2026-09-15'
LATE_BASELINE_FROM = '2026-09-17'

# タイトル変更を受けた記事(2026-09-25 判明。条件 g で各組最大1本にする)。
# タイトルは引用のされ方を直接動かすので、組に固まると処置と分けられない。
TITLE_CHANGED_SLUGS = (
    'agentforce-for-sales-sdr-sales-coach',
    'agentic-ai-guide',
    'agentic-crm-pipeline-stagnation-detection',
)
# タイトル変更の日付。制作管制の全編集一覧(edits_20260911_0916.csv)で分かったら埋める。
# 9/15 以降と分かった記事は、そのまま late_appended_slugs()(9/17 以降の観測だけを
# 基準値に使う記事)に入る。空のままなら基準値の扱いは変えない。
TITLE_CHANGE_DATES = {}


def strata_path():
    """逆リンク追記の層のファイル。strata_backlink_YYYYMMDD.csv があれば新しいほうを使う。"""
    dated = sorted(glob.glob(STRATA_GLOB))
    return dated[-1] if dated else STRATA_LEGACY


def load_strata(path=None):
    """逆リンク追記を受けた記事。プールに無い記事(E37 など)は外す。"""
    path = path or strata_path()
    if not os.path.exists(path):
        return []
    pool = pool_slugs()
    return [r for r in read_csv(path)
            if r['slug'].lower() in pool and r['slug'].lower() not in EXCLUDED]


def appended_slugs(path=None):
    """9/11〜9/16 に逆リンク追記を受けた記事(条件 b)。"""
    return {r['slug'].lower() for r in load_strata(path)}


def title_changed_slugs():
    """タイトル変更を受けた記事(条件 g)。プールに無い記事は外す。"""
    return {s for s in TITLE_CHANGED_SLUGS if s in pool_slugs()}


def late_appended_slugs(path=None):
    """ビフォー期間の途中(9/15〜16)に本文・タイトルが変わった記事。

    条件 e の母数であり、ビフォー基準値を 9/17 以降に切る対象でもある。
    逆リンク追記(層の表の appended_at)に加えて、9/15 以降と分かった
    タイトル変更(TITLE_CHANGE_DATES)も入れる。
    """
    late = {r['slug'].lower() for r in load_strata(path)
            if str(r.get('appended_at', ''))[:10] >= LATE_APPEND_FROM}
    late |= {s for s, d in TITLE_CHANGE_DATES.items()
             if s in pool_slugs() and str(d)[:10] >= LATE_APPEND_FROM}
    return late


def baseline_start(slug_name, path=None):
    """その記事のビフォー基準値に使える最初の日。制限が無ければ None。"""
    return LATE_BASELINE_FROM if slug_name in late_appended_slugs(path) else None


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
