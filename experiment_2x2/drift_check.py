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
  python experiment_2x2/drift_check.py --post-baseline # 処置後の基準を取る（2026-09-30 に1回だけ）

処置後の基準（2026-09-30 追加・効果測定チャットの指示）
　処置（D-39・FAQ ブロック・features の1文）は 2026-09-29〜30 に入れた。前回の基準（9/28）のまま比べると、
　10/5 の回で処置した35本が全部「変化あり」になり、処置の後に起きた本物の変化と見分けがつかない。
　そこで 9/30（処置の完了後）に46本の「処置後のハッシュ」を drift/post_treatment/ に取っておき、
　**前回の基準が処置の前（checked が 2026-09-30 以前）の回だけ**、前回の代わりに処置後の基準と比べる。
　→ 9/29〜30 の処置による変化は差分に出ない（想定内）。処置後の基準と違えば、それは 10/1 以降の変化＝想定外。
　その回のハッシュが新しい基準になり、翌週からは従来どおり前回と比べる。
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
POST_DIR = os.path.join(HERE, 'drift', 'post_treatment')
POST_MANIFEST = os.path.join(POST_DIR, 'manifest.json')
POST_SNAP_DIR = os.path.join(POST_DIR, 'snapshots')
# 処置の期間の最終日。前回の基準がこの日以前なら、処置後の基準と比べる
TREATMENT_END = '2026-09-30'


def choose_reference(old, post, treatment_end=TREATMENT_END):
    """比べる相手を返す。(基準の manifest, 'previous' / 'post_treatment')

    前回の基準（old）がすべて処置の前（checked <= treatment_end）で、処置後の基準（post）があれば post と比べる。
    1本でも処置の後に取った基準が old にあれば、従来どおり old と比べる（取り直しは1回だけ）。
    """
    if post and old and all(v.get('checked', '') <= treatment_end for v in old.values()):
        return post, 'post_treatment'
    return old, 'previous'

_SCRIPT = re.compile(r'<(script|style|noscript)\b[^>]*>.*?</\1>', re.S | re.I)
_COMMENT = re.compile(r'<!--.*?-->', re.S)
_ARTICLE = re.compile(r'<article\b[^>]*>(.*?)</article>', re.S | re.I)
_WS = re.compile(r'\s+')
_TAG = re.compile(r'<[^>]+>')
# 「関連記事」は <article> の中にあるが、表示のたびに中身が入れ替わる。
# ここを含めると毎週「変化あり」になり、本物の変化が埋もれる。本文の終わりで切る。
_RELATED = re.compile(r'<section\b[^>]*class="[^"]*p-entry__related', re.I)
# 「読了時間」（Reading Time プラグイン）は本文から計算し直される表示で、本文が同じでも値が動く
# （2026-09-21 の回で47本すべてが 11分→6分 などで「変化あり」になった）。本文の変化ではないので落とす（2026-09-30）
_READING_TIME = re.compile(r'<span class="span-reading-time[^"]*"[^>]*>(?:\s*<span[^>]*>[^<]*</span>)*\s*</span>', re.I)


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
    src = _READING_TIME.sub('', src)
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
    ap.add_argument('--post-baseline', action='store_true',
                    help='処置後の基準を drift/post_treatment/ に取る（通常の基準・差分には触れない）')
    ap.add_argument('--sleep', type=float, default=1.0)
    ap.add_argument('--out-dir', default=os.path.join(ROOT, 'output', 'reports'))
    a = ap.parse_args()

    os.makedirs(SNAP_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    if a.post_baseline:
        os.makedirs(POST_SNAP_DIR, exist_ok=True)
        post, bad = {}, []
        for slug, url in targets():
            try:
                body = body_of(fetch(url))
            except Exception as e:                              # noqa: BLE001
                bad.append(slug)
                print(f'  ★取得失敗 {slug}: {e}', file=sys.stderr)
                continue
            post[slug] = {'url': url, 'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
                          'bytes': len(body), 'checked': today}
            io.open(os.path.join(POST_SNAP_DIR, f'{slug}.txt'), 'w', encoding='utf-8').write(text_of(body))
            time.sleep(a.sleep)
        if bad:
            print(f'★{len(bad)} 本を取得できないため処置後の基準を保存しない：{bad}')
            return 1
        json.dump(post, io.open(POST_MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'処置後の基準 {len(post)} 本 → {POST_MANIFEST}')
        return 0
    old = {}
    if os.path.exists(MANIFEST):
        old = json.load(io.open(MANIFEST, encoding='utf-8'))
    post = json.load(io.open(POST_MANIFEST, encoding='utf-8')) if os.path.exists(POST_MANIFEST) else {}
    ref, ref_kind = choose_reference(old, post)
    ref_snap_dir = POST_SNAP_DIR if ref_kind == 'post_treatment' else SNAP_DIR
    if ref_kind == 'post_treatment':
        print(f'前回の基準が処置の前（〜{TREATMENT_END}）のため、処置後の基準と比べる（9/29〜30 の処置による変化は想定内）')
    first_run = not old or a.baseline

    new, changed, failed, markup_only = {}, [], [], []
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
        ref_snap = os.path.join(ref_snap_dir, f'{slug}.txt')
        text = text_of(body)
        prev = ref.get(slug, {}).get('sha256')
        # 基準を取り直すときは差分を出さない（取り直し自体を「変化」と呼ばない）。
        if not first_run and prev and prev != digest and os.path.exists(ref_snap):
            before = io.open(ref_snap, encoding='utf-8').read().split('\n')
            label = '処置後の基準' if ref_kind == 'post_treatment' else '前回'
            diff = list(difflib.unified_diff(before, text.split('\n'),
                                             fromfile=f'{slug} {label}({ref[slug]["checked"]})',
                                             tofile=f'{slug} 今回({today})', lineterm='', n=1))
            item = {'slug': slug, 'url': url, 'prev': prev, 'now': digest,
                    'prev_checked': ref[slug]['checked'], 'diff': diff}
            if diff:
                changed.append(item)
                print(f'  ★変化あり {slug}（{len(diff)} 行の差分）')
            else:
                # 本文テキストは同じで HTML だけが違う（2026-09-30）。9/18→9/21→9/30 で47本が ±7 バイト往復した例があり、
                # 　テキストの変化と同じ扱いにすると本物の変化が埋もれる。ただしリンク先・属性の変化もここに入るため、別枠で必ず出す
                markup_only.append(item)
                print(f'  △HTMLのみの変化 {slug}（本文テキストは同一）')
        io.open(snap, 'w', encoding='utf-8').write(text)
        time.sleep(a.sleep)

    json.dump(new, io.open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(new)} 本のハッシュを保存（失敗 {len(failed)} 本）→ {MANIFEST}')

    if first_run:
        print('基準を作りました。差分の判定は次回から。')
        return 0
    if not changed and not failed and not markup_only:
        print('前週から変化なし。報告は出しません。')
        return 0

    path = os.path.join(a.out_dir, f'experiment47_drift_{today.replace("-", "")}.md')
    os.makedirs(a.out_dir, exist_ok=True)
    L = [f'# 47本の本文の変化（{today}）', '',
         '実験期間中は47本の本文を変えない。ここに記事が出ているということは、',
         '把握していない経路で本文が変わったということ。**原因を確かめるまで、',
         'その記事の引用率の増減を処置の効果として読まないこと。**', '',
         f'- 比べた基準：{"処置後の基準（" + TREATMENT_END + " 取得。9/29〜30 の処置による変化は想定内として除いた）" if ref_kind == "post_treatment" else "前回の実行"}',
         f'- 本文テキストが変化した記事（想定外）：**{len(changed)} 本 / {len(new) + len(failed)} 本**',
         f'- HTMLのみの変化（本文テキストは同一・要確認）：{len(markup_only)} 本',
         f'- 取得できなかった記事：{len(failed)} 本', '']
    if failed:
        L += ['## 取得できなかった記事', '', '| slug | url | 理由 |', '|---|---|---|']
        L += [f'| {s} | {u} | {e} |' for s, u, e in failed]
        L.append('')
    if markup_only:
        L += ['## HTMLのみの変化（本文テキストは同一）', '',
              '表示される文字は同じで、HTML（属性・リンク先・マークアップ）だけが違う。',
              '9/18→9/21→9/30 に47本すべてが ±7 バイト往復した例がある（原因は未特定・テキストは同一）。',
              'リンク先や属性の変化もここに入るため、本数が多い週は1本を開いて確かめる。', '',
              '| slug | 基準 | 今回 |', '|---|---|---|']
        L += [f'| {c["slug"]} | {c["prev_checked"]} `{c["prev"][:12]}` | `{c["now"][:12]}` |' for c in markup_only]
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
