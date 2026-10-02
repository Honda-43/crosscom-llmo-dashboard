# -*- coding: utf-8 -*-
"""pillar.py｜凍結を解いたピラー2本の編集を、判定に反映する（2026-10-02 新設・同日改訂）。

2026-10-02 に凍結範囲を統計46本に縮小し、ピラー2本（agentforce-guide／agentic-crm）と
agentforce-pricing は編集できるようになった（本田さん決定・interventions I-18）。ピラーには孤児記事
（ピラーから1本もリンクされていない46本以外の記事）へのリンクが足される。46本へのリンクの増減は無いが、
次の2つの経路で46本の引用に間接的に効きうるので、判定レポートの冒頭に出す。

偏り1（薄まり）：ピラーの発リンクが増えると、ピラーから46本への既存リンク1本あたりの重みが薄まる。
  既存リンクを受けている46本は組ごとに本数が違う（ピラーA：①6・②7・③4・④4）。①②が多いので、
  ①②だけが薄まる分、リードの効果（③④ − ①②）が大きめに見える方向に効く。組間の差が2本以上なら「偏りあり」
偏り2（横取り）：孤児が46本の実験用プロンプトに「強」で答える場合（13本）、孤児が強くなると AI が46本の代わりに
  孤児を引用しうる。2026-10-02 本田さん決定でこの13本は今は張らない（2027-01-01 以降）。
  実際に張られた孤児（pillar_links_added_*.csv）と突き合わせ、張られていれば本数と組を出す

アフター期間の切り分け：ピラー編集の完了（pillar_links_added_*.csv の最後の実施日）が 10/5 までなら
  アフター（10/6〜）の全体に同じ条件でかかるので注記だけ。10/6 以降なら、アフターを編集前・編集後に分けた結果も
  並べる（完了日の観測はどちらにも入れない）

表（どれも seo-agent 側の判断・測定。dashboard の experiment_2x2/ に写しがあればそれを優先して読む）
  pillar_links_added_*.csv          : 実施の記録（date, wp_modified, pillar, target_slug …）。seo-agent の output/reports
  pillar_existing_links_*.csv       : ピラー → 46本の既存リンク（pillar, slug, group, links）。pillar_release_balance_20261001.md §1 の写し
  pillar_strong_overlap_*.csv       : 強の重なり13本（orphan, pillar, prompt_slug, group）。同 §2 の写し
"""
import collections
import csv
import datetime as dt
import glob
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SEO_AGENT = os.path.join(ROOT, '..', 'crosscom-seo-agent', 'output')
LAG_UNTIL = dt.date(2026, 10, 5)          # 反映ラグの最終日。アフターは 10/6 から
BIAS_GAP = 2                              # 組間の差がこの本数以上なら「偏りあり」
GROUPS = ('①対照', '②FAQのみ', '③リードのみ', '④両方')
PILLARS = ('agentforce-guide', 'agentic-crm')
PILLAR_LABEL = {'agentforce-guide': 'ピラーA（agentforce-guide）', 'agentic-crm': 'ピラーB（agentic-crm）'}
DATE_COLUMNS = ('wp_modified', 'applied_at', 'added_at', 'datetime', 'date')
TARGET_COLUMNS = ('target_slug', 'target', 'slug')


def find(name_glob):
    """dashboard の写しと seo-agent の output/experiment・output/reports のうち、ファイル名(日付)が最も新しいもの。

    同じ名前なら dashboard の写しを使う。seo-agent が新しい日付の表(例：ピラーB の実施後)を出したら、そちらを読む。
    """
    best = {}
    for folder in (os.path.join(SEO_AGENT, 'reports'), os.path.join(SEO_AGENT, 'experiment'), HERE):
        for path in glob.glob(os.path.join(folder, name_glob)):
            best[os.path.basename(path)] = path            # 後の(=優先する)フォルダで上書き
    return best[max(best)] if best else None


def _rows(path):
    with io.open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


def _date_of(text):
    text = str(text or '').strip().replace('T', ' ').replace('/', '-')
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _slug(text):
    return str(text or '').strip().rstrip('/').split('/')[-1].lower()


# --------------------------------------------------------------------------
# 実施の記録
# --------------------------------------------------------------------------
def pillar_edit(path=None):
    """{'done', 'count', 'targets', 'by_pillar': {ピラー: 最後の実施日}, 'path'}。表が無ければ None。"""
    path = path or find('pillar_links_added_*.csv')
    if not path or not os.path.exists(path):
        return None
    rows = _rows(path)
    dcol = next((c for c in DATE_COLUMNS if rows and c in rows[0]), None)
    tcol = next((c for c in TARGET_COLUMNS if rows and c in rows[0]), None)
    by_pillar = {}
    for r in rows:
        d = _date_of(r.get(dcol)) if dcol else None
        p = r.get('pillar', '')
        if d and (p not in by_pillar or d > by_pillar[p]):
            by_pillar[p] = d
    return {'done': max(by_pillar.values()) if by_pillar else None, 'count': len(rows),
            'targets': [_slug(r.get(tcol)) for r in rows] if tcol else [],
            'by_pillar': by_pillar, 'path': path}


def split_after(after, done, lag_until=LAG_UNTIL):
    """アフター期間 (開始, 終了) をピラー編集の前後に分ける。

    返り値は (区分, [(見出し, (開始, 終了)), ...])。
    区分: 'none'（完了日が分からない）／'before_after'（10/5 までに完了：分けない）／
          'split'（10/6 以降に完了：前・後に分ける。完了日は入れない）／'after_end'（判定期間より後）
    """
    if done is None:
        return 'none', []
    start, end = (dt.date.fromisoformat(x) for x in after)
    if done <= lag_until or done < start:
        return 'before_after', []
    if done > end:
        return 'after_end', []
    parts = []
    if done > start:
        parts.append(('ピラー編集前', (start, done - dt.timedelta(days=1))))
    if done < end:
        parts.append(('ピラー編集後', (done + dt.timedelta(days=1), end)))
    return 'split', [(label, (a.isoformat(), b.isoformat())) for label, (a, b) in parts]


# --------------------------------------------------------------------------
# 偏り1（薄まり）：ピラー → 46本の既存リンク
# --------------------------------------------------------------------------
def existing_links(path=None):
    """[{pillar, slug, group, links}]。表が無ければ None。"""
    path = path or find('pillar_existing_links_*.csv')
    if not path or not os.path.exists(path):
        return None
    return _rows(path)


def linked_articles(path=None):
    """ピラーA・ピラーBのどちらかから既存リンクを受けている46本の slug(感度分析で抜く記事)。表が無ければ None。"""
    rows = existing_links(path)
    return None if rows is None else {_slug(r['slug']) for r in rows}


def balance(path=None):
    """[(見出し, {組: 記事数}, 差, 偏りありか)]。ピラーA・ピラーB・どちらか の3行。表が無ければ None。"""
    rows = existing_links(path)
    if rows is None:
        return None
    out = []
    for label, keep in [(PILLAR_LABEL[p], (lambda r, p=p: r['pillar'] == p)) for p in PILLARS] \
            + [('A・Bのどちらか', lambda r: True)]:
        arts = {(r['group'], _slug(r['slug'])) for r in rows if keep(r)}
        counts = {g: sum(1 for grp, _ in arts if grp == g) for g in GROUPS}
        gap = max(counts.values()) - min(counts.values())
        out.append((label, counts, gap, gap >= BIAS_GAP))
    return out


# --------------------------------------------------------------------------
# 偏り2（横取り）：強の重なりの孤児が実際に張られたか
# --------------------------------------------------------------------------
def poaching(edit=None, path=None):
    """{'linked': [(孤児, 重なる46本, 組)], 'by_group': {組: 本数}, 'total': 強の孤児の数}。表が無ければ None。"""
    path = path or find('pillar_strong_overlap_*.csv')
    if not path or not os.path.exists(path):
        return None
    rows = _rows(path)
    targets = set((edit or {}).get('targets') or [])
    linked = [(r['orphan'], r['prompt_slug'], r['group']) for r in rows if _slug(r['orphan']) in targets]
    by_group = collections.Counter(g for _, _, g in linked)
    return {'linked': linked, 'by_group': {g: by_group.get(g, 0) for g in GROUPS},
            'total': len({r['orphan'] for r in rows})}


# --------------------------------------------------------------------------
# 判定レポートの冒頭
# --------------------------------------------------------------------------
def report_lines(after):
    """判定レポートの冒頭に出す行と、アフターを分ける区間(無ければ空)。"""
    lines = ['## ピラー2本の編集（2026-10-02 に凍結を解除・interventions I-18）']
    edit = pillar_edit()
    if edit is None:
        lines.append('- ピラー編集の記録（pillar_links_added_*.csv）はまだ無い')
        mode, parts = 'none', []
    else:
        mode, parts = split_after(after, edit['done'])
        per = '・'.join(f"{PILLAR_LABEL.get(p, p)} {d}" for p, d in sorted(edit['by_pillar'].items()))
        missing = [PILLAR_LABEL[p] for p in PILLARS if p not in edit['by_pillar']]
        lines.append(f"- ピラー編集の実施：追加 {edit['count']}本（{per}）"
                     + (f"。**{'・'.join(missing)} はまだ記録が無い**" if missing else ''))
        lines.append({
            'none': '- 実施日が読めないため、アフターの切り分けはしない',
            'before_after': '- アフター期間（10/6〜）の前に完了。アフター全体に同じ条件でかかるため、追加の切り分けはしない',
            'split': '- 10/6 以降に完了。アフター期間をピラー編集の前後に分けた結果も並べる（完了日の観測はどちらにも入れない）',
            'after_end': '- 判定期間の後に完了。この判定には影響しない',
        }[mode])
    bal = balance()
    lines.append('- **偏り1（薄まり）**：ピラーから46本への既存リンクを受けている記事の数（組ごと）。'
                 f'組間の差が{BIAS_GAP}本以上なら「偏りあり」')
    if bal is None:
        lines.append('  - 既存リンクの表（pillar_existing_links_*.csv）はまだ無い')
    else:
        lines += ['', '| | ' + ' | '.join(GROUPS) + ' | 差 | 判定 |', '|---|' + '---|' * (len(GROUPS) + 2)]
        for label, counts, gap, biased in bal:
            lines.append(f'| {label} | ' + ' | '.join(str(counts[g]) for g in GROUPS)
                         + f" | {gap} | {'偏りあり' if biased else '—'} |")
        either = bal[-1][1]
        off, on = either['①対照'] + either['②FAQのみ'], either['③リードのみ'] + either['④両方']
        if off > on:
            lines.append(f'  - リードなし（①②）{off}本 > リードあり（③④）{on}本：①②だけが薄まる分、'
                         'リードの効果が大きめに見える方向')
        elif on > off:
            lines.append(f'  - リードあり（③④）{on}本 > リードなし（①②）{off}本：リードの効果が小さめに見える方向')
        lines.append('')
    poach = poaching(edit)
    if poach is None:
        lines.append('- **偏り2（横取り）**：強の重なりの表（pillar_strong_overlap_*.csv）はまだ無い')
    elif not poach['linked']:
        lines.append(f"- **偏り2（横取り）**：強の重なり{poach['total']}本は今回張らないため、対象外"
                     '（2027-01-01 以降。2026-10-02 本田さん決定）')
    else:
        spots = '・'.join(f'{o}→{s}（{g}）' for o, s, g in poach['linked'])
        lines.append(f"- **偏り2（横取り）**：★強の重なり{poach['total']}本のうち **{len(poach['linked'])}本が張られている**"
                     '（2026-10-02 の決定では除外のはず）。組ごと：'
                     + '・'.join(f'{g} {n}' for g, n in poach['by_group'].items()) + f'。{spots}')
    return lines + [''], parts
