# -*- coding: utf-8 -*-
"""pillar.py｜凍結を解いたピラー2本の編集を、判定に反映する（2026-10-02 新設）。

2026-10-02 に凍結範囲を統計46本に縮小し、ピラー2本（agentforce-guide／agentic-crm）と
agentforce-pricing は編集できるようになった（本田さん決定・interventions I-18）。ピラーには孤児記事への
リンクが足される。46本へのリンクの増減は無いが、ピラーの発リンクの希釈や孤児記事の強化を通じて、
46本の引用に間接的に効きうる。そこで判定では次の2つを出す。

1. ピラー編集の完了日（seo-agent の pillar_links_added_*.csv の最後の実施日時）
   - 2026-10-05 までに完了 → アフター期間（10/6〜）の全体に同じ条件でかかるので、注記だけ
   - 10/6 以降に完了 → アフター期間を「編集前」「編集後」に分けた結果も並べる（完了日そのものは
     どちらにも入れない。同じ日の観測が編集の前か後か分からないため）
2. ピラーと46本の釣り合い（seo-agent の pillar_release_balance_*.csv）
   - 組ごとの本数（ピラーから46本への既存リンク・孤児と46本の話題の重なり など）を判定レポートの冒頭に転記し、
     組間の差（最大−最小）が2本以上の列は「偏りあり」と出す

どちらの表も seo-agent 側が作る。dashboard の experiment_2x2/ に写しがあればそれを、無ければ
seo-agent の output/experiment/（次に output/reports/）を読む。まだ無ければ「未作成」と出す。

想定する列（seo-agent に依頼する形。名前の揺れはある程度受ける）
  pillar_links_added_*.csv     : applied_at（JST の日時）, pillar, target（slug か URL）
  pillar_release_balance_*.csv : group（①対照 など）, 以降は組ごとの本数の列（例 existing_links, orphan_topic_overlap）
"""
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
DATE_COLUMNS = ('applied_at', 'added_at', 'modified', 'datetime', 'date')
GROUP_COLUMNS = ('group', '組')


def find(name_glob):
    """dashboard の写し → seo-agent の output/experiment → output/reports の順で、日付の新しいもの。"""
    for folder in (HERE, os.path.join(SEO_AGENT, 'experiment'), os.path.join(SEO_AGENT, 'reports')):
        found = sorted(glob.glob(os.path.join(folder, name_glob)))
        if found:
            return found[-1]
    return None


def _rows(path):
    with io.open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


def _date_of(text):
    text = str(text or '').strip().replace('T', ' ').replace('/', '-')
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def pillar_edit(path=None):
    """{'done': 完了日, 'count': 追加したリンクの本数, 'path': 表}。表が無ければ None。"""
    path = path or find('pillar_links_added_*.csv')
    if not path or not os.path.exists(path):
        return None
    rows = _rows(path)
    column = next((c for c in DATE_COLUMNS if rows and c in rows[0]), None)
    dates = [d for d in (_date_of(r.get(column)) for r in rows) if d] if column else []
    return {'done': max(dates) if dates else None, 'count': len(rows), 'path': path}


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


def balance(path=None):
    """{'groups': [組...], 'metrics': [(列, {組: 本数}, 差, 偏りありか)], 'path': 表}。表が無ければ None。"""
    path = path or find('pillar_release_balance_*.csv')
    if not path or not os.path.exists(path):
        return None
    rows = _rows(path)
    if not rows:
        return {'groups': [], 'metrics': [], 'path': path}
    gcol = next((c for c in GROUP_COLUMNS if c in rows[0]), None)
    groups = [r[gcol] for r in rows] if gcol else []
    metrics = []
    for col in rows[0]:
        if col == gcol:
            continue
        try:
            values = {r[gcol]: float(r[col]) for r in rows}
        except (TypeError, ValueError):
            continue                       # 数ではない列(注記など)は飛ばす
        gap = max(values.values()) - min(values.values())
        metrics.append((col, values, gap, gap >= BIAS_GAP))
    return {'groups': groups, 'metrics': metrics, 'path': path}


def _n(x):
    return str(int(x)) if float(x).is_integer() else f'{x:g}'


def report_lines(after):
    """判定レポートの冒頭に出す行と、アフターを分ける区間(無ければ空)。"""
    lines = ['## ピラー2本の編集（2026-10-02 に凍結を解除・interventions I-18）']
    edit = pillar_edit()
    if edit is None:
        lines.append('- ピラー編集の記録（pillar_links_added_*.csv）はまだ無い')
        mode, parts = 'none', []
    else:
        mode, parts = split_after(after, edit['done'])
        lines.append(f"- ピラー編集の完了：{edit['done'] or '日時が読めない'}"
                     f"（追加 {edit['count']}本・{os.path.basename(edit['path'])}）")
        lines.append({
            'none': '- 完了日が読めないため、アフターの切り分けはしない',
            'before_after': '- アフター期間（10/6〜）の前に完了。アフター全体に同じ条件でかかるため、追加の切り分けはしない',
            'split': '- 10/6 以降に完了。アフター期間をピラー編集の前後に分けた結果も並べる（完了日の観測はどちらにも入れない）',
            'after_end': '- 判定期間の後に完了。この判定には影響しない',
        }[mode])
    bal = balance()
    if bal is None:
        lines.append('- ピラーと46本の釣り合い（pillar_release_balance_*.csv）はまだ無い')
    else:
        lines.append(f"- ピラーと46本の釣り合い（{os.path.basename(bal['path'])}）："
                     f"組間の差が{BIAS_GAP}本以上の列は「偏りあり」")
        if bal['metrics']:
            lines.append('| 列 | ' + ' | '.join(bal['groups']) + ' | 差 | 判定 |')
            lines.append('|---|' + '---|' * (len(bal['groups']) + 2))
            for col, values, gap, biased in bal['metrics']:
                lines.append(f'| {col} | ' + ' | '.join(_n(values[g]) for g in bal['groups'])
                             + f" | {_n(gap)} | {'偏りあり' if biased else '—'} |")
    return lines + [''], parts
