# -*- coding: utf-8 -*-
"""make_strata.py｜割付の層（条件 b）の表を作る。

2026-09-25 から本命は **制作管制の全編集一覧**（14列）。
  python make_strata.py --copy-from ../../crosscom-seo-agent/output/reports/edits_20260911_0916.csv
「pool_class=統計46 かつ links_after > links_before の行を1行以上持つ記事」を抽出し、
`strata_backlink_YYYYMMDD.csv` と `title_changes_YYYYMMDD.csv` を作る
（pool.strata_path / pool.title_change_dates が新しいほうを自動で使う）。

**列名・列数・型が仕様と1つでも違えば、何も書かずに止める。** 推測で読むと、
層に入るはずの記事が静かに抜け落ちて、条件 b が偏ったまま通ってしまう。

旧: 便GL の記録（Markdown）から17本を起こすモード。--from-bungl で残してある。
"""
import argparse
import csv
import datetime
import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool import EXCLUDED, pool_slugs, strata_path, title_change_path  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEO_AGENT_EDITS = os.path.join(HERE, '..', '..', 'crosscom-seo-agent', 'output',
                               'reports', 'edits_20260911_0916.csv')
EDITS_COPY = os.path.join(HERE, 'edits_20260911_0916.csv')
BUNGL_RECORD = os.environ.get(
    'BUNGL_RECORD',
    os.path.join(HERE, '..', '..', 'crosscom-seo-agent', 'output', 'reports',
                 'bunGL_experiment48_append_record_20260917.md'))

# 制作管制の全編集一覧の仕様（この順・この名前でなければ止める。2026-09-25 に17列へ）
EDIT_COLUMNS = ['slug', 'post_id', 'edited_at_jst', 'pool_class', 'edit_type', 'source',
                'chars_delta', 'links_before', 'links_after', 'added_link_targets',
                'removed_link_targets', 'title_changed', 'title_before', 'title_after',
                'links_before_all', 'links_after_all', 'note']
INT_COLUMNS = ('post_id', 'chars_delta', 'links_before', 'links_after',
               'links_before_all', 'links_after_all')
POOL_CLASS = '統計46'
STRATA_COLUMNS = ['slug', 'url', 'post_id', 'appended_at', 'backlinks', 'parents']
DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')
JST = datetime.timezone(datetime.timedelta(hours=9))
# 観測開始の時刻。ビフォー期間の「途中で変わった記事」はこの時刻で切る。
# 日付(JST・GMT)の境目で切ると、9/15 01:34 の編集まで巻き込んでしまう。
# あの2本は観測が始まる前の編集で、ビフォーの1回目から新しい本文を見ている。
OBSERVATION_START = datetime.datetime(2026, 9, 15, 8, 0, 0, tzinfo=JST)
LATE_WINDOW_END = datetime.datetime(2026, 9, 16, 23, 59, 59, tzinfo=JST)


def _parse_dt(text):
    """ISO-8601(+09:00 付き)も、素の "YYYY-MM-DD HH:MM:SS" も読む。JST に揃える。"""
    raw = str(text).strip()
    try:
        got = datetime.datetime.fromisoformat(raw)
    except ValueError:
        got = None
        for fmt in DATE_FORMATS:
            try:
                got = datetime.datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if got is None:
        return None
    return got.astimezone(JST) if got.tzinfo else got.replace(tzinfo=JST)


def validate_edits(rows, header):
    """仕様と合っているか。合わない点を文字列のリストで返す（空なら合格）。"""
    problems = []
    if header != EDIT_COLUMNS:
        missing = [c for c in EDIT_COLUMNS if c not in (header or [])]
        extra = [c for c in (header or []) if c not in EDIT_COLUMNS]
        problems.append(f'列が仕様と違う（{len(header or [])}列。期待 {len(EDIT_COLUMNS)}列）'
                        + (f'／足りない: {", ".join(missing)}' if missing else '')
                        + (f'／余分: {", ".join(extra)}' if extra else '')
                        + ('／並びが違う' if not missing and not extra else ''))
        return problems                      # 列が違う時点で型は見ない
    for i, r in enumerate(rows, start=2):    # 2行目からがデータ
        if not str(r.get('slug', '')).strip():
            problems.append(f'{i}行目: slug が空')
        for col in INT_COLUMNS:
            value = str(r.get(col, '')).strip()
            try:
                int(value)
            except ValueError:
                problems.append(f'{i}行目: {col} が整数でない（{value!r}）')
        if _parse_dt(r.get('edited_at_jst')) is None:
            problems.append(f'{i}行目: edited_at_jst を日時として読めない'
                            f'（{str(r.get("edited_at_jst"))!r}）')
        if str(r.get('title_changed', '')).strip() not in ('0', '1'):
            problems.append(f'{i}行目: title_changed が 0/1 でない'
                            f'（{str(r.get("title_changed"))!r}）')
        if not str(r.get('note', '')).strip():
            problems.append(f'{i}行目: note が空')
    return problems


def read_edits(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def link_increases(rows):
    """{slug: 最初にリンクが増えた日時} — pool_class=統計46 の行だけ見る。"""
    got = {}
    for r in rows:
        if str(r['pool_class']).strip() != POOL_CLASS:
            continue
        if int(r['links_after']) <= int(r['links_before']):
            continue
        slug = str(r['slug']).strip().lower()
        when = _parse_dt(r['edited_at_jst'])
        if slug not in got or when < got[slug][0]:
            got[slug] = (when, r)
    return got


def late_changes(rows):
    """観測開始(9/15 08:00 JST)〜9/16 23:59:59 に変わった記事。{slug: 最初の編集時刻}。

    条件 e の母数であり、ビフォー基準値を 9/17 以降に切る対象でもある。
    編集の種類は問わない(本文・リンク・タイトルのどれでも、観測の途中で変われば同じ)。
    """
    got = {}
    for r in rows:
        if str(r['pool_class']).strip() != POOL_CLASS:
            continue
        when = _parse_dt(r['edited_at_jst'])
        if when is None or not (OBSERVATION_START <= when <= LATE_WINDOW_END):
            continue
        slug = str(r['slug']).strip().lower()
        if slug not in got or when < got[slug]:
            got[slug] = when
    return got


def title_changes(rows):
    """{slug: 最初にタイトルが変わった日時}。pool_class は問わない（統計46は後で絞る）。"""
    got = {}
    for r in rows:
        if str(r['title_changed']).strip() != '1':
            continue
        slug = str(r['slug']).strip().lower()
        when = _parse_dt(r['edited_at_jst'])
        if slug not in got or when < got[slug]:
            got[slug] = when
    return got


def from_edits(path, out_name, title_out_name, late_out_name):
    rows, header = read_edits(path)
    problems = validate_edits(rows, header)
    if problems:
        print(f'★ {os.path.basename(path)} が仕様と合わないため取り込みを止めた'
              f'（{len(problems)}件）:', file=sys.stderr)
        for p in problems[:20]:
            print(f'  - {p}', file=sys.stderr)
        if len(problems) > 20:
            print(f'  ... 他 {len(problems) - 20}件', file=sys.stderr)
        return None, None, 2

    pool = pool_slugs()
    increases = link_increases(rows)
    outside = sorted(s for s in increases if s not in pool or s in EXCLUDED)
    for s in outside:
        increases.pop(s)
    strata = []
    for slug in sorted(increases):
        when, r = increases[slug]
        strata.append({
            'slug': slug,
            'url': f'https://cross-com.jp/{slug}/',
            'post_id': r['post_id'],
            'appended_at': when.strftime('%Y-%m-%d %H:%M:%S'),
            'backlinks': int(r['links_after']) - int(r['links_before']),
            'parents': str(r.get('added_link_targets', '')).strip(),
        })

    before = {r['slug'].lower() for r in _read_strata(strata_path())}
    now = {r['slug'] for r in strata}
    out = os.path.join(HERE, out_name)
    with io.open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=STRATA_COLUMNS)
        w.writeheader(); w.writerows(strata)

    # 観測開始(9/15 08:00 JST)以降に変わった記事 — 条件 e と「9/17 以降のみ」の母数
    late = {s: w for s, w in late_changes(rows).items() if s in pool}
    late_out = os.path.join(HERE, late_out_name)
    with io.open(late_out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['slug', 'changed_at'])
        for slug in sorted(late):
            w.writerow([slug, late[slug].strftime('%Y-%m-%d %H:%M:%S%z')])

    titles = {s: w for s, w in title_changes(rows).items() if s in pool}
    title_out = os.path.join(HERE, title_out_name)
    with io.open(title_out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['slug', 'changed_at'])
        for slug in sorted(titles):
            w.writerow([slug, titles[slug].strftime('%Y-%m-%d %H:%M:%S')])

    print(f'取り込み: {len(rows)}行 → リンクが増えた記事 {len(strata)}本 → {out}')
    if outside:
        print(f'プール46本の外(pool_class=統計46 だが46本に無い) {len(outside)}本: '
              + '、'.join(outside))
    print(f'差分（前 {len(before)}本 → 今 {len(now)}本）')
    print('  増えた記事: ' + ('、'.join(sorted(now - before)) or 'なし'))
    print('  消えた記事: ' + ('、'.join(sorted(before - now)) or 'なし'))
    print(f'条件 e(観測開始 {OBSERVATION_START:%Y-%m-%d %H:%M} 〜 '
          f'{LATE_WINDOW_END:%m-%d %H:%M} に変わった記事) {len(late)}本 → {late_out}')
    for slug in sorted(late):
        print(f'  {slug} {late[slug]:%Y-%m-%d %H:%M}')
    others = [r for r in rows
              if str(r['pool_class']).strip() == POOL_CLASS
              and str(r['edit_type']).strip() == 'その他'
              and (_parse_dt(r['edited_at_jst']) or OBSERVATION_START) >= OBSERVATION_START]
    print(f'edit_type=その他 かつ 統計46 かつ 観測開始以降: {len(others)}行')
    for r in others:
        print(f'  {r["slug"]} {r["edited_at_jst"]} {r["note"]}')
    print(f'タイトル変更 {len(titles)}本 → {title_out}')
    for slug in sorted(titles):
        mark = '（9/15 以降。条件 e と「9/17 以降のみ」の対象）' \
            if titles[slug].strftime('%Y-%m-%d') >= '2026-09-15' else ''
        print(f'  {slug} {titles[slug]:%Y-%m-%d %H:%M}{mark}')
    return out, title_out, 0


def _read_strata(path):
    if not path or not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8', newline='') as f:
        return [r for r in csv.DictReader(f) if r.get('slug')]


def from_bungl(out_name):
    """旧: 便GL の記録(Markdown)から17本を起こす。"""
    text = io.open(BUNGL_RECORD, encoding='utf-8').read()
    rows = []
    for line in text.splitlines():
        if not line.startswith('| ') or 'https://cross-com.jp/' not in line:
            continue
        c = [x.strip() for x in line.strip('|').split('|')]
        if len(c) < 8 or not c[0].isdigit():
            continue
        url = c[1]
        rows.append({'slug': url.rstrip('/').split('/')[-1], 'url': url, 'post_id': c[3],
                     'appended_at': c[4], 'backlinks': c[5],
                     'parents': c[6].replace('<br>', ' ; ')})
    assert rows, '記録の表を読めていない'
    pool = pool_slugs()
    dropped = [r['slug'] for r in rows if r['slug'] in EXCLUDED or r['slug'] not in pool]
    rows = [r for r in rows if r['slug'] not in dropped]
    if dropped:
        print('プール外のため除いた:', ', '.join(dropped))
    out = os.path.join(HERE, out_name)
    with io.open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=STRATA_COLUMNS)
        w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} 本 → {out}')
    print('合計リンク本数:', sum(int(r['backlinks']) for r in rows))
    return 0


def main(argv=None):
    today = datetime.date.today().strftime('%Y%m%d')
    ap = argparse.ArgumentParser()
    ap.add_argument('--copy-from', nargs='?', const=SEO_AGENT_EDITS,
                    help='制作管制の全編集一覧をここにコピーしてから取り込む'
                         f'（既定: {os.path.relpath(SEO_AGENT_EDITS, HERE)}）')
    ap.add_argument('--from-edits', help='コピー済みの全編集一覧から作る')
    ap.add_argument('--from-bungl', action='store_true', help='旧: 便GL の記録から17本')
    ap.add_argument('--out', help='層の表の名前（既定: strata_backlink_YYYYMMDD.csv）')
    ap.add_argument('--title-out', help='タイトル変更の表（既定: title_changes_YYYYMMDD.csv）')
    ap.add_argument('--late-out', help='観測開始以降に変わった記事（既定: late_changes_YYYYMMDD.csv）')
    a = ap.parse_args(argv)

    if a.from_bungl:
        return from_bungl(a.out or 'strata_backlink17.csv')

    src = a.from_edits
    if a.copy_from:
        if not os.path.exists(a.copy_from):
            print(f'★ 全編集一覧が見つからない: {a.copy_from}', file=sys.stderr)
            return 2
        # seo-agent 側のファイルは読むだけ。手元にコピーしてから取り込む
        rows, header = read_edits(a.copy_from)
        problems = validate_edits(rows, header)
        if problems:
            print(f'★ {a.copy_from} が仕様と合わないためコピーも取り込みもしない'
                  f'（{len(problems)}件）:', file=sys.stderr)
            for p in problems[:20]:
                print(f'  - {p}', file=sys.stderr)
            return 2
        shutil.copyfile(a.copy_from, EDITS_COPY)
        print(f'コピー: {a.copy_from} → {os.path.relpath(EDITS_COPY, HERE)}')
        src = EDITS_COPY
    if not src:
        src = EDITS_COPY
    if not os.path.exists(src):
        print(f'★ 全編集一覧がまだ無い: {src}', file=sys.stderr)
        print('  届くまでは条件 b は便GL の17本のまま'
              f'（{os.path.basename(strata_path())}）', file=sys.stderr)
        return 2
    _, _, code = from_edits(src, a.out or f'strata_backlink_{today}.csv',
                            a.title_out or f'title_changes_{today}.csv',
                            a.late_out or f'late_changes_{today}.csv')
    if code == 0:
        print('次: python experiment_2x2/allocate_47.py --cited-to <日付> で条件 a〜g を確認')
    return code


if __name__ == '__main__':
    sys.exit(main())
