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
  # 途中で止まった（止めた）ときは、続きから
  python experiment_2x2/rerandomize.py --resume
  # 中身の確認（件数・完成か作成途中か）
  python experiment_2x2/rerandomize.py --show

プールは results/rerandomization_pool.csv に保存し、判定のたびに読み直す
（同じ p値が何度でも再現できるようにするため。作り直しは --build で明示したときだけ）。
2026-09-28：条件を満たす割付を見つけるたびに1行ずつ追記し、最後に試したシードを
results/rerandomization_pool.checkpoint に残す形にした（全件をメモリに溜めない）。
100件ごとに件数・経過時間・現在のシードを出す。途中で止まっても、それまでの行は有効。
既存のプールがあるときの --build は止まる（捨てて作り直すなら --restart を足す）。
"""
import argparse
import csv
import io
import json
import os
import sys
import time

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
def search(arts, cited, actual, seed_start=SEED_START):
    """seed_start から順にシードを試し、条件 a〜g を満たす割付ごとに (seed, 組番号の文字列) を返す。

    実際の割付と同じものは入れない。シードだけで結果が決まるので、どこで止めて
    どこから再開しても、同じシードからは同じ行が出る。
    条件を満たさないシードでも、試し終えたことを知らせるため (seed, None) を返す。
    """
    feats = features(arts, cited)
    totals = [sum(f[i] for f in feats) for i in range(7)]
    seed = seed_start
    while True:
        labels = [GROUPS.index(g) for g in
                  (allocate_47.allocate(arts, seed)[a['slug']] for a in arts)]
        text = None
        if fast_ok(labels, feats, totals):
            text = ''.join(str(x + 1) for x in labels)
            if text == actual:
                text = None
        yield seed, text
        seed += 1


def build(arts, cited, actual, size=POOL_SIZE, seed_start=SEED_START):
    """条件 a〜g を満たす割付を ``size`` 通り、メモリ上で作る（テスト・小さいプール用）。"""
    got, tried, seed = [], 0, seed_start
    for seed, text in search(arts, cited, actual, seed_start):
        tried += 1
        if text is not None:
            got.append((seed, text))
            if len(got) >= size:
                break
    return got, tried, seed + 1


def _header(f, n_arts, meta):
    f.write('# 再ランダム化検定の割付プール。条件 a〜g を満たす割付だけが入っている。\n')
    f.write('# assignment は記事の並び順（config/prompts_experiment.csv）の組番号。\n')
    f.write(f'# 1=①対照 2=②FAQのみ 3=③リードのみ 4=④両方 / 記事 {n_arts}本\n')
    for k, v in meta.items():
        f.write(f'# {k}: {v}\n')
    csv.writer(f).writerow(['perm_id', 'seed', 'assignment'])


def save(rows, arts, meta, path=POOL_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        _header(f, len(arts), meta)
        w = csv.writer(f)
        for i, (seed, text) in enumerate(rows, 1):
            w.writerow([i, seed, text])
    return path


def _complete_lines(path):
    """改行で終わっている行だけ。書き込みの途中で落ちた最後の1行は捨てる。"""
    with io.open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    if text and not text.endswith('\n'):
        text = text[:text.rfind('\n') + 1]
    return text


def load(path=POOL_FILE):
    """保存したプール。[(seed, 組番号の文字列), ...]。無ければ空。作成途中でも、それまでの行は有効。"""
    if not os.path.exists(path):
        return []
    lines = _complete_lines(path).splitlines()
    rows = list(csv.DictReader(ln for ln in lines if not ln.startswith('#')))
    return [(int(r['seed']), r['assignment']) for r in rows]


# --------------------------------------------------------------------------
# プールを1行ずつ追記して作る（途中再開つき）（2026-09-28）
# --------------------------------------------------------------------------
# 9/28 に 5,000通りを一気に作ろうとして、PC のメモリ不足で途中で止められた。
# 条件を満たした割付は見つけた時点でファイルへ追記し、最後に試したシードを
# checkpoint に残す。止まっても --resume で続きから作れ、結果は一気に作った場合と同じ。
CHECKPOINT_FILE = os.path.join(HERE, 'results', 'rerandomization_pool.checkpoint')
CHECKPOINT_EVERY = 20000          # 条件を満たさないシードが続くときも、この回数ごとに保存する
PROGRESS_EVERY = 100


def read_checkpoint(path=CHECKPOINT_FILE):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def write_checkpoint(state, path=CHECKPOINT_FILE):
    """書きかけの checkpoint が残らないよう、別名で書いてから置き換える。"""
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _hms(sec):
    sec = int(sec)
    return f'{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}'


class ResumeError(Exception):
    pass


def build_to_file(arts, cited, actual, out=POOL_FILE, checkpoint=CHECKPOINT_FILE,
                  target=POOL_SIZE, seed_start=SEED_START, resume=False, meta=None,
                  progress=PROGRESS_EVERY, checkpoint_every=CHECKPOINT_EVERY,
                  clock=time.monotonic, log=print):
    """条件 a〜g を満たす割付を ``target`` 通りになるまで ``out`` へ1行ずつ追記する。

    resume=True なら checkpoint とファイルの行から続きを作る。条件 c の引用あり・
    実際の割付・開始シードが checkpoint と違えば、別のプールになるので再開しない。
    戻り値は checkpoint と同じ形の dict（done=True なら target 通りそろった）。
    """
    fingerprint = {'seed_start': seed_start, 'cited': sorted(cited), 'actual': actual}
    if resume:
        state = read_checkpoint(checkpoint)
        if state is None or not os.path.exists(out):
            raise ResumeError(f'再開できない：{checkpoint} か {out} が無い。--build で最初から作る')
        diff = [k for k, v in fingerprint.items() if state.get(k) != v]
        if diff:
            raise ResumeError(f'再開できない：checkpoint と条件が違う（{", ".join(diff)}）。'
                              '別のプールになるため、続きは作らない')
        # 正本はファイルの行。checkpoint は最後の行より古いことがある（保存の間に止まった場合）
        text = _complete_lines(out)
        with io.open(out, 'w', encoding='utf-8', newline='') as f:
            f.write(text)                   # 書きかけの最後の1行を捨てる
        rows = load(out)
        count = len(rows)
        next_seed = max(state['next_seed'], rows[-1][0] + 1 if rows else seed_start)
        elapsed0 = state.get('elapsed_sec', 0)
        state['target'] = target
    else:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, 'w', encoding='utf-8', newline='') as f:
            _header(f, len(arts), meta or {})
        state = dict(fingerprint, target=target)
        count, next_seed, elapsed0 = 0, seed_start, 0

    t0 = clock()

    def save_state(seed_next, done=False):
        state.update(next_seed=seed_next, last_tried_seed=seed_next - 1,
                     tried=seed_next - seed_start, count=count,
                     elapsed_sec=round(elapsed0 + clock() - t0, 1), done=done)
        write_checkpoint(state, checkpoint)

    if count >= target:
        save_state(next_seed, done=True)
        return state

    seed = next_seed
    try:
        with io.open(out, 'a', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            for seed, text in search(arts, cited, actual, next_seed):
                if text is not None:
                    count += 1
                    w.writerow([count, seed, text])
                    f.flush()
                    save_state(seed + 1, done=count >= target)
                    if progress and count % progress == 0:
                        log(f'  {count}/{target} 件　経過 {_hms(elapsed0 + clock() - t0)}'
                            f'　現在のシード {seed}', flush=True)
                    if count >= target:
                        break
                elif (seed + 1 - seed_start) % checkpoint_every == 0:
                    save_state(seed + 1)
    except KeyboardInterrupt:
        save_state(seed)                    # seed は試し終えていないので、次はここから
        raise
    return state


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
    ap.add_argument('--build', action='store_true', help='プールを最初から作る')
    ap.add_argument('--resume', action='store_true',
                    help='checkpoint から続きを作る（止まったあとに使う）')
    ap.add_argument('--restart', action='store_true',
                    help='--build で、既存のプールを捨てて最初から作り直すことを認める')
    ap.add_argument('--show', action='store_true', help='保存済みのプールの概要を出す')
    ap.add_argument('--target', '--size', dest='target', type=int, default=POOL_SIZE,
                    help=f'この件数に達したら止める（既定 {POOL_SIZE}）')
    ap.add_argument('--seed-start', type=int, default=SEED_START)
    ap.add_argument('--cited-from', default=CITED_FROM)
    ap.add_argument('--cited-to', default=CITED_TO)
    ap.add_argument('--cited-csv', default='')
    ap.add_argument('--out', default=POOL_FILE)
    ap.add_argument('--checkpoint', default=CHECKPOINT_FILE)
    a = ap.parse_args(argv)

    if a.show or not (a.build or a.resume):
        rows = load(a.out)
        if not rows:
            print(f'プールがまだ無い: {a.out}', file=sys.stderr)
            print('  9/28 の割付が決まったあとに --build で作る', file=sys.stderr)
            return 2
        state = read_checkpoint(a.checkpoint) or {}
        done = '完成' if state.get('done') else '★作成途中（--resume で続きを作る）'
        print(f'{len(rows)} 通り / シード {rows[0][0]}〜{rows[-1][0]} / {done} / {a.out}')
        return 0

    # 既存のプールを黙って上書きしない（途中まで作った分を失わないため）
    if a.build and not a.resume and os.path.exists(a.out) and not a.restart:
        print(f'★ {a.out} がすでにある。続きを作るなら --resume、'
              '捨てて作り直すなら --build --restart', file=sys.stderr)
        return 2

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
    meta = {'seed_start': a.seed_start,
            'cited': f'{a.cited_from}〜{a.cited_to}（{len(cited)}本）',
            'excluded_actual': actual,
            'progress': f'目標件数・最後に試したシード・完成かどうかは {os.path.basename(a.checkpoint)}'}
    try:
        state = build_to_file(arts, cited, actual, a.out, a.checkpoint, a.target,
                              a.seed_start, resume=a.resume, meta=meta)
    except ResumeError as e:
        print(f'★ {e}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        state = read_checkpoint(a.checkpoint) or {}
        print(f'\n中断：{state.get("count", 0)} 件まで保存済み（シード {state.get("next_seed")} から再開）。'
              '続きは --resume', file=sys.stderr)
        return 130
    print(f'{state["count"]} 通り（{state["tried"]:,}回試行・経過 {_hms(state["elapsed_sec"])}）'
          f'→ {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
