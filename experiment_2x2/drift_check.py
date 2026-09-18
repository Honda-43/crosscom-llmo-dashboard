# -*- coding: utf-8 -*-
"""drift_check.py｜47本の本文が実験期間中に変わっていないかを毎週見る（2026-09-18 新設）。

なぜ要るか
　処置以外の理由で本文が変わると、引用率の増減が処置の効果かどうか分からなくなる。
　publish_followup の除外（〜2026-12-31）で自動の追記は止めたが、
　止まっているのは**こちらが把握している経路**だけ。人手の修正・プラグインの出力変化・
　テーマ更新は止められない。だから「変わっていないこと」を毎週こちらで確かめる。

やること
　①47本の公開ページを取り、<article> の中身を正規化してハッシュを取る
　②前回のハッシュと突き合わせ、変わっていれば差分を出す
　③変化があった週だけ output/reports/experiment47_drift_YYYYMMDD.md を書く

　正規化：script / style / コメントを外し、空白をつぶす。
　　nonce やビルド時刻のような**毎回変わる断片**を拾って毎週「変化あり」に
　　なってしまうと、本物の変化が埋もれる。

usage:
  python experiment_2x2/drift_check.py                 # 毎週月曜。初回は基準を作るだけ
  python experiment_2x2/drift_check.py --baseline      # 基準を取り直す（差分は出さない）
"""
import argparse
import csv
import datetime
import difflib
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
HERE = os.path.join(ROOT, 'experiment_2x2')
SNAP_DIR = os.path.join(HERE, 'drift', 'snapshots')
MANIFEST = os.path.join(HERE, 'drift', 'manifest.json')
UA = {'User-Agent': 'Mozilla/5.0 (compatible; crosscom-llmo-drift/1.0)'}

_SCRIPT = re.compile(r'<(script|style|noscript)\b[^>]*>.*?</\1>', re.S | re.I)
_COMMENT = re.compile(r'<!--.*?-->', re.S)
_ARTICLE = re.compile(r'<article\b[^>]*>(.*?)</article>', re.S | re.I)
_WS = re.compile(r'\s+')
_TAG = re.compile(r'<[^>]+>')
# 「関連記事」は <article> の中にあるが、表示のたびに中身が入れ替わる。
# ここを含めると毎週「変化あり」になり、本物の変化が埋もれる。本文の終わりで切る。
_RELATED = re.compile(r'<section\b[^>]*class="[^"]*p-entry__related', re.I)


def fetch(url, retries=3):
    last = None
    for i in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:                                  # noqa: BLE001
            last = e
            time.sleep(3 * i)
    raise RuntimeError(f'取得できない {url}: {last!r}')


def body_of(html):
    """<article> の中身を、毎回変わる断片を落として返す。"""
    m = _ARTICLE.search(html)
    src = m.group(1) if m else html
    src = _SCRIPT.sub('', src)
    src = _COMMENT.sub('', src)
    cut = _RELATED.search(src)
    if cut:
        src = src[:cut.start()]
    return _WS.sub(' ', src).strip()


def text_of(body):
    """差分を人が読める形にするための素のテキスト。"""
    t = _TAG.sub('\n', body)
    return '\n'.join(x.strip() for x in t.split('\n') if x.strip())


def targets():
    out = []
    with io.open(os.path.join(ROOT, 'config', 'prompts_experiment.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out.append((r['url'].rstrip('/').split('/')[-1], r['url']))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', action='store_true', help='基準を取り直す（差分は出さない）')
    ap.add_argument('--sleep', type=float, default=1.0)
    ap.add_argument('--out-dir', default=os.path.join(ROOT, 'output', 'reports'))
    a = ap.parse_args()

    os.makedirs(SNAP_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    old = {}
    if os.path.exists(MANIFEST):
        old = json.load(io.open(MANIFEST, encoding='utf-8'))
    first_run = not old or a.baseline

    new, changed, failed = {}, [], []
    for slug, url in targets():
        try:
            html = fetch(url)
        except Exception as e:                                  # noqa: BLE001
            failed.append((slug, url, str(e)))
            print(f'  ★取得失敗 {slug}: {e}', file=sys.stderr)
            continue
        body = body_of(html)
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        new[slug] = {'url': url, 'sha256': digest, 'bytes': len(body), 'checked': today}
        snap = os.path.join(SNAP_DIR, f'{slug}.txt')
        text = text_of(body)
        prev = old.get(slug, {}).get('sha256')
        # 基準を取り直すときは差分を出さない（取り直し自体を「変化」と呼ばない）。
        if not first_run and prev and prev != digest and os.path.exists(snap):
            before = io.open(snap, encoding='utf-8').read().split('\n')
            diff = list(difflib.unified_diff(before, text.split('\n'),
                                             fromfile=f'{slug} 前回({old[slug]["checked"]})',
                                             tofile=f'{slug} 今回({today})', lineterm='', n=1))
            changed.append({'slug': slug, 'url': url, 'prev': prev, 'now': digest,
                            'prev_checked': old[slug]['checked'], 'diff': diff})
            print(f'  ★変化あり {slug}（{len(diff)} 行の差分）')
        io.open(snap, 'w', encoding='utf-8').write(text)
        time.sleep(a.sleep)

    json.dump(new, io.open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(new)} 本のハッシュを保存（失敗 {len(failed)} 本）→ {MANIFEST}')

    if first_run:
        print('基準を作りました。差分の判定は次回から。')
        return 0
    if not changed and not failed:
        print('前週から変化なし。報告は出しません。')
        return 0

    path = os.path.join(a.out_dir, f'experiment47_drift_{today.replace("-", "")}.md')
    os.makedirs(a.out_dir, exist_ok=True)
    L = [f'# 47本の本文の変化（{today}）', '',
         '実験期間中は47本の本文を変えない。ここに記事が出ているということは、',
         '把握していない経路で本文が変わったということ。**原因を確かめるまで、',
         'その記事の引用率の増減を処置の効果として読まないこと。**', '',
         f'- 変化した記事：**{len(changed)} 本 / {len(new) + len(failed)} 本**',
         f'- 取得できなかった記事：{len(failed)} 本', '']
    if failed:
        L += ['## 取得できなかった記事', '', '| slug | url | 理由 |', '|---|---|---|']
        L += [f'| {s} | {u} | {e} |' for s, u, e in failed]
        L.append('')
    for c in changed:
        L += [f'## {c["url"]}', '',
              f'- 前回 {c["prev_checked"]}：`{c["prev"][:16]}`',
              f'- 今回 {today}：`{c["now"][:16]}`', '',
              '`' * 3 + 'diff']
        L += c['diff'][:400]
        if len(c['diff']) > 400:
            L.append(f'…（差分 {len(c["diff"])} 行のうち先頭400行）')
        L += ['`' * 3, '']
    io.open(path, 'w', encoding='utf-8').write('\n'.join(L))
    print('wrote', path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
