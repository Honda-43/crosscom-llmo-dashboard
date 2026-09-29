# -*- coding: utf-8 -*-
"""imbalance_check.py｜条件に入れていなかった性質の偏りを、くじ引きの確率で見る（2026-09-29 新設）。

なぜ見るか
　FAQ の回答が複数段落の7本（faq_multiparagraph_*.csv）が、9/28 の割付ですべて ②④（FAQ あり）に
　入った。この性質は条件 a〜g に入れていなかった。「同じ条件 a〜g を満たす割付」の中で、
　7本がすべて ②④ に入る割合を数え、偶然として起こりうる範囲かを記録する。

どの割付で数えるか
　再ランダム化プール（results/rerandomization_pool.csv）が --n 件以上あればその先頭 --n 件。
　足りなければ、条件 a〜g を満たす割付を --n 件その場で作る（シード 20390101 から。
　プールとは別の番号帯。--workers 本のプロセスで番号を分けて探す）。作った割付は --save に残す。
　各プロセスは見つけるたびに results/imbalance_parts/ へ追記するので、止まっても同じ
　--workers で再実行すれば続きから作る（結果は一気に作った場合と同じ）。

usage:
  python experiment_2x2/imbalance_check.py --n 1000 --workers 6
"""
import argparse
import csv
import io
import multiprocessing as mp
import os
import sys
import time
from math import comb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import allocate_47  # noqa: E402
import rerandomize  # noqa: E402
from pool import load_allocation, multi_paragraph_path, multi_paragraph_slugs  # noqa: E402

SEED_START = 20390101
FAQ_ON = [rerandomize.GROUPS.index(g) for g in rerandomize.FAQ_ON]
SAVE = os.path.join(rerandomize.HERE, 'results', 'imbalance_sample_20260929.csv')


PARTS_DIR = os.path.join(rerandomize.HERE, 'results', 'imbalance_parts')


def part_path(i, step, parts_dir=PARTS_DIR):
    return os.path.join(parts_dir, f'worker_{i}_of_{step}.csv')


def read_part(path):
    """途中まで見つけた (seed, assignment)。書きかけの最後の1行は捨てる。"""
    if not os.path.exists(path):
        return []
    rows = []
    for ln in rerandomize._complete_lines(path).splitlines():
        seed, _, text = ln.partition(',')
        if seed.isdigit() and text:
            rows.append((int(seed), text))
    return rows


def _worker(args):
    """seed_start+i, +i+W, +i+2W, ... を試し、条件を満たす割付を n 件集める。

    見つけるたびに自分のファイルへ追記する（2026-09-29：メモリ不足で途中で止められ、
    500件超を失ったため）。同じ W で再実行すると、ファイルの最後のシードの次から続ける。
    """
    i, step, n, seed_start, cited, actual, q, parts_dir = args
    path = part_path(i, step, parts_dir)
    got = read_part(path)[:n]
    if q is not None:
        for _ in got:
            q.put(1)
    if len(got) >= n:
        return got
    arts, _ = allocate_47.load_articles()
    feats = rerandomize.features(arts, cited)
    totals = [sum(f[k] for f in feats) for k in range(7)]
    seed = got[-1][0] + step if got else seed_start + i
    os.makedirs(parts_dir, exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(''.join(f'{sd},{t}\n' for sd, t in got))     # 書きかけの行を捨てて書き直す
    with io.open(path, 'a', encoding='utf-8', newline='') as f:
        while len(got) < n:
            labels = [rerandomize.GROUPS.index(g) for g in
                      (allocate_47.allocate(arts, seed)[a['slug']] for a in arts)]
            if rerandomize.fast_ok(labels, feats, totals):
                text = ''.join(str(x + 1) for x in labels)
                if text != actual:
                    got.append((seed, text))
                    f.write(f'{seed},{text}\n')
                    f.flush()
                    if q is not None:
                        q.put(1)
            seed += step
    return got


def generate(n, workers, cited, actual, seed_start=SEED_START, log=print, parts_dir=PARTS_DIR):
    per = [n // workers + (1 if k < n % workers else 0) for k in range(workers)]
    t0 = time.monotonic()
    with mp.Manager() as m:
        q = m.Queue()
        with mp.Pool(workers) as p:
            res = p.map_async(_worker, [(k, workers, per[k], seed_start, cited, actual, q, parts_dir)
                                        for k in range(workers)])
            done = 0
            while not res.ready() or not q.empty():
                try:
                    q.get(timeout=5)
                    done += 1
                    if done % 100 == 0:
                        log(f'  {done}/{n} 件　経過 {rerandomize._hms(time.monotonic() - t0)}',
                            flush=True)
                except Exception:
                    pass
            rows = [r for part in res.get() for r in part]
    return sorted(rows)


def all_in(text, idx, groups):
    """idx の記事がすべて groups（組番号 0〜3）に入っているか。"""
    return all(int(text[k]) - 1 in groups for k in idx)


def count_in(text, idx, groups):
    return sum(int(text[k]) - 1 in groups for k in idx)


def summarize(rows, idx, n_arts, n_on):
    k = len(idx)
    hits = sum(all_in(t, idx, FAQ_ON) for _, t in rows)
    dist = [0] * (k + 1)
    for _, t in rows:
        dist[count_in(t, idx, FAQ_ON)] += 1
    # 条件なしのくじ（FAQ あり n_on 本／n_arts 本）で k 本すべてが FAQ ありに入る確率
    free = comb(n_on, k) / comb(n_arts, k)
    return hits, dist, free


def main(argv=None):
    ap = argparse.ArgumentParser(description='複数段落回答の偏りの確率')
    ap.add_argument('--n', type=int, default=1000)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--save', default=SAVE)
    a = ap.parse_args(argv)

    arts, _ = allocate_47.load_articles()
    groups = load_allocation()
    actual = ''.join(str(rerandomize.GROUPS.index(groups[x['slug']]) + 1) for x in arts)
    multi = multi_paragraph_slugs()
    if multi is None:
        print('★ faq_multiparagraph_*.csv が無い', file=sys.stderr)
        return 2
    idx = [k for k, x in enumerate(arts) if x['slug'] in multi[0]]
    print(f'複数段落回答 {len(idx)}本（{multi_paragraph_path()}）')
    print('実際の割付：' + '・'.join(f'{x["slug"]}={groups[x["slug"]]}'
                                    for x in arts if x['slug'] in multi[0]))

    pool_rows = rerandomize.load()
    if len(pool_rows) >= a.n:
        rows, src = pool_rows[:a.n], f'再ランダム化プールの先頭 {a.n} 件'
    else:
        cited, _ = allocate_47.load_cited(argparse.Namespace(
            cited_csv='', cited_from=rerandomize.CITED_FROM, cited_to=rerandomize.CITED_TO))
        print(f'プールが {len(pool_rows)} 件のため、条件 a〜g を満たす割付を {a.n} 件作る'
              f'（シード {SEED_START} から・{a.workers} プロセス）')
        rows = generate(a.n, a.workers, cited, actual)
        src = (f'条件 a〜g を満たす割付 {a.n} 件（シード {SEED_START} から '
               f'{a.workers} プロセスで番号を分けて探索）')
        os.makedirs(os.path.dirname(a.save), exist_ok=True)
        with io.open(a.save, 'w', encoding='utf-8', newline='') as f:
            f.write(f'# {src}。assignment の並びは rerandomization_pool.csv と同じ\n')
            w = csv.writer(f)
            w.writerow(['seed', 'assignment'])
            w.writerows(rows)
        print('wrote', a.save)

    n_on = sum(1 for c in actual if int(c) - 1 in FAQ_ON)
    hits, dist, free = summarize(rows, idx, len(arts), n_on)
    print(f'\n使った割付：{src}')
    print(f'{len(idx)}本すべてが ②④ に入る割付：{hits}/{len(rows)} = {hits / len(rows):.4f}')
    print(f'（参考）条件なしのくじ：C({n_on},{len(idx)})/C({len(arts)},{len(idx)}) = {free:.4f}')
    print('②④ に入る本数の分布：' + '　'.join(f'{k}本 {v}' for k, v in enumerate(dist)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
