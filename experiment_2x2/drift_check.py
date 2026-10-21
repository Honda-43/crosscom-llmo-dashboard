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
  python experiment_2x2/drift_check.py --post-baseline # 処置後の基準を取る（2026-09-30 に1回だけ。既にあれば止まる）
  python experiment_2x2/drift_check.py --post-baseline --force --reason "理由"  # 取り直す（日誌に記録）

処置後の基準（2026-09-30 追加・効果測定チャットの指示）
　処置（D-39・FAQ ブロック・features の1文）は 2026-09-29〜30 に入れた。前回の基準（9/28）のまま比べると、
　10/5 の回で処置した35本が全部「変化あり」になり、処置の後に起きた本物の変化と見分けがつかない。
　そこで 9/30（処置の完了後）に46本の「処置後のハッシュ」を drift/post_treatment/ に取っておき、
　**前回の基準が処置の前（checked が 2026-09-30 以前）の回だけ**、前回の代わりに処置後の基準と比べる。
　→ 9/29〜30 の処置による変化は差分に出ない（想定内）。処置後の基準と違えば、それは 10/1 以降の変化＝想定外。
　その回のハッシュが新しい基準になり、翌週からは従来どおり前回と比べる。

実験期間中に入れると決めた修正（2026-10-18 追加・誤情報修正の1本）
　drift/expected_edits.json に修正前後の段落を入れると、その記事の差分がその段落の中だけなら想定内として別枠に出す。
　段落の外が1行でも変わっていれば想定外。

事実訂正（2026-10-20 準備・Agentforce の導入実績があるように読める文の訂正・約20本）
　fact_corrections.csv（E番号・slug・組・リビジョン・時刻）に載り時刻の入った記事は、drift/fact_correction_sentences.csv
　（E番号・slug・修正前・修正後）の文の置き換えだけで前回の本文から今回の本文になるなら想定内（E33 と同じ考え方を文の単位で）。
　置き換えは文ごとに、今回の本文に修正後の文があるものだけ当てる（何回かに分けて直しても週ごとに確かめられる）。
　ほかが1字でも変わっていれば想定外。表に載っているのに時刻・文が無い記事が変わったら、想定外として「記録待ち」と注記する。
　2026-10-22（E22・E05）：修正前後の文は drift/expected_edits.json にも入れられる（"mode": "sentences" の項目。
　"sentences": [{before, after}]。"from" を空にすると fact_corrections.csv のその記事の訂正の日を使う）。
"""
import argparse
import csv
import datetime
import difflib
import gzip
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
sys.path.insert(0, os.path.join(ROOT, 'src'))
import force_log  # noqa: E402  標準ライブラリだけのモジュール（日誌への自動記録）

HERE = os.path.join(ROOT, 'experiment_2x2')
SNAP_DIR = os.path.join(HERE, 'drift', 'snapshots')
MANIFEST = os.path.join(HERE, 'drift', 'manifest.json')
UA = {'User-Agent': 'Mozilla/5.0 (compatible; crosscom-llmo-drift/1.0)'}
POST_DIR = os.path.join(HERE, 'drift', 'post_treatment')
POST_MANIFEST = os.path.join(POST_DIR, 'manifest.json')
POST_SNAP_DIR = os.path.join(POST_DIR, 'snapshots')
POST_HTML_DIR = os.path.join(POST_DIR, 'html')

# 2026-10-09 19:42 の著者表示の変更（interventions.csv I-31・I-32。全ページ一律・4組に同条件）による想定内の変化。
# 　I-31：本文の冒頭に「著者：本田正憲／肩書き」、末尾に新しい著者欄（紹介文・プロフィールへのリンク）を表示
# 　　（Person 構造化データは <script> の中なので、そもそも差分に出ない）
# 　I-32：テーマ標準の著者ボックス（旧紹介文・note へのリンク・記事一覧へ）をオフ
# 　差分の行が**すべて**下の文字列のどれかなら想定内。1行でも違えば（紹介文の書き換えを含む）従来どおり想定外として出す。
# 　2026-10-09 に46本の公開ページで確かめた差分（各13行・46本とも同じ）から取った
AUTHOR_CHANGE_FROM = '2026-10-09'
AUTHOR_ADDED = frozenset({
    '著者：', '本田正憲', '合同会社クロスコム 代表／Salesforce認定コンサルタント', 'この記事を書いた人',
    '双日グループの専門商社で法人営業を経験後、マーケティング支援で独立し2023年に合同会社クロスコムを設立。'
    '現在はAgentforceの導入・定着支援とAgentic CRM設計支援を専門とする。',
    'プロフィールを見る →',
})
AUTHOR_REMOVED = frozenset({
    'この記事を書いた人', '本田正憲',
    '合同会社クロスコムの代表｜専門商社にて7年間のBtoB営業を経て、マーケティング業界に参入。'
    '現在はSalesforce公式コンサルティングパートナーとして、ソリューション営業の業務プロセスに特化した'
    'Agentforce導入・定着支援と、Agentic CRM設計支援を提供している。'
    'Salesforce認定アドミニストレーター・Sales Cloudコンサルタント・Marketing Cloud Account Engagement スペシャリスト。',
    'https://note.com/honda_crosscom', '記事一覧へ',
})


def author_only_change(diff, today, since=AUTHOR_CHANGE_FROM):
    """差分が著者表示の変更（I-31・I-32）の行だけか。基準が変更の前でも後でも、今回が変更日以降なら判定する。"""
    if today < since:
        return False
    lines = [x for x in diff if x[:1] in '+-' and not x.startswith(('+++', '---'))]
    return bool(lines) and all((x[1:] in AUTHOR_ADDED) if x[0] == '+' else (x[1:] in AUTHOR_REMOVED) for x in lines)


# 実験期間中に入れると決めた本文の修正（2026-10-18・誤情報修正の1本・pool.MISINFO_FIX_SLUGS）。
# 　[{"slug", "from"(適用日 YYYY-MM-DD), "intervention"(I-xx), "paragraphs": [{"para", "before", "after"}, ...],
# 　  "faq_answers": [{"question", "before", "after"}, ...](FAQ の答え。表示の文だけを比べる。FAQPage の構造化データは
# 　  <script> の中なので body_of で落ちていて、そもそも比べていない),
# 　  "rest_changes": [{"para", "where", "before", "after"}, ...](同じ記事のあとの追加修正。本文の段落と FAQ の答え),
# 　  "update_date_display"(true なら記事の「更新」の日付が適用日に変わる行も想定内)}]。
# 　段落は seo-agent の記録をそのまま入れる（HTML でも素のテキストでもよい。"before"/"after" を1段落ぶん直接書いてもよい）。
# 　ファイルが無ければ何もしない。
# 　その記事の差分の行が**すべて**決めた段落の中（消えた行はどれかの修正前の段落の一部・足された行はどれかの修正後の段落の一部）なら想定内。
# 　1行でもその外が変わっていれば、記事ごと従来どおり想定外として出す。
# 　関連記事の並び（テーマがアクセスのたびに選び直す）は body_of で切り落としているので、そもそも差分に出ない
EXPECTED_EDITS = os.path.join(HERE, 'drift', 'expected_edits.json')
_TAGS_AND_SPACE = re.compile(r'<[^>]+>|\s+')
_DATE_LINE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def load_expected_edits(path=None, keep_pending=False, corrections_path=None):
    """expected_edits.json の決めた修正。

    事実訂正（文の単位・2026-10-22）は ``"mode": "sentences"`` の項目で入れる（形は README）。``sentences`` は
    ``paragraphs`` と同じ扱い（[{before, after}]）。``from`` が空なら fact_corrections.csv のその記事の訂正の日を使う。
    時刻がまだ無い項目は想定内にできないので返さない（``keep_pending=True`` なら from を空のまま返す）。"""
    path = EXPECTED_EDITS if path is None else path
    if not os.path.exists(path):
        return []
    out = []
    for e in json.load(io.open(path, encoding='utf-8')):
        if e.get('mode') != 'sentences':
            out.append(e)
            continue
        e = dict(e)
        if 'sentences' in e and not e.get('paragraphs'):
            e['paragraphs'] = e.pop('sentences')
        e.setdefault('update_date_display', True)
        if not e.get('from'):
            import pool
            at = pool.fact_correction_at_by_slug(corrections_path).get(pool.slug(e.get('slug') or ''))
            e['from'] = at.date().isoformat() if at else ''
        if e['from'] or keep_pending:
            out.append(e)
    return out


def _flat(text):
    return _TAGS_AND_SPACE.sub('', str(text or ''))


def _pair_list(edit):
    """決めた修正の前後の組を、当てる順（本文 → FAQ → 追加修正）に並べる。"""
    paras = [p for key in ('paragraphs', 'faq_answers', 'rest_changes') for p in (edit.get(key) or [])]
    if 'before' in edit or 'after' in edit:
        paras.append({'before': edit.get('before'), 'after': edit.get('after')})
    return paras


def _paragraphs(edit):
    paras = _pair_list(edit)
    befores = [_flat(p.get('before')) for p in paras]
    # あとの修正で書き換えた途中の文(ある修正の後 = 次の修正の前)は、足された行としては認めない。
    # 認めると、最後の修正を途中の文へ戻したのを想定内と読んでしまう(2026-10-18・I-43)
    later = set(befores)
    return befores, [a for a in (_flat(p.get('after')) for p in paras) if a not in later]


def expected_edit_for(slug, diff, today, edits, old_text=None, new_text=None):
    """差分がその記事の決めた修正の段落の中だけなら、その修正（dict）。違えば None。

    ``old_text``・``new_text``（前回と今回の本文テキスト）を渡すと、修正を当てた結果が今回と同じかも確かめる（週次はこちら）。"""
    lines = [x for x in diff if x[:1] in '+-' and not x.startswith(('+++', '---'))]
    mine = [e for e in edits if e.get('slug') == slug and today >= str(e.get('from', '9999'))]
    if len(mine) > 1 and any(e.get('mode') == 'sentences' for e in mine):
        # 同じ記事に決めた修正が2つ以上（例：E33 の修正のあとに事実訂正）。同じ週に両方が入っても確かめられるよう、合わせた形も試す
        mine = mine + [{'slug': slug, 'mode': 'sentences', 'from': max(str(e.get('from')) for e in mine),
                        'intervention': '・'.join(str(e.get('intervention', '')) for e in mine),
                        'paragraphs': [p for e in mine for p in _pair_list(e)],
                        'update_date_display': any(e.get('update_date_display') for e in mine)}]
    for e in mine:
        day = str(e.get('from', '9999'))
        if e.get('mode') == 'sentences':
            # 文の単位の修正は行の照合ができない（段落の中の一部の文だけが変わる）。本文の全体で確かめる
            if old_text is not None and new_text is not None and _replays_sentences(e, old_text, new_text, diff):
                return e
            continue
        befores, afters = _paragraphs(e)
        removed = [_flat(x[1:]) for x in lines if x[0] == '-']
        added = [_flat(x[1:]) for x in lines if x[0] == '+']
        if e.get('update_date_display'):
            # 記事の「更新」の表示：日付だけの行が適用日に変わったもの（1組だけ）
            if day in added and any(_DATE_LINE.match(x) for x in removed):
                added.remove(day)
                removed.remove(next(x for x in removed if _DATE_LINE.match(x)))
        if not (added and all(x and any(x in a for a in afters) for x in added)
                and all(any(x in b for b in befores) for x in removed if x)):
            continue
        if old_text is not None and new_text is not None and not _replays(e, old_text, new_text, diff):
            continue
        return e
    return None


def _replays(edit, old_text, new_text, diff):
    """前回の本文に決めた修正を順に当てると、今回の本文と一字一句同じになるか（2026-10-18・I-43）。

    行ごとの照合だけだと、修正後の段落の一部を消した（例：例と「当社では」を分ける一文を消した）変化も
    「修正後の段落の一部」として通ってしまう。本文の全体で確かめる。タグの位置で行が分かれても同じに比べるため、
    空白とタグを落とした文字列で比べる。"""
    text = _old_with_date(edit, old_text, diff)
    for p in _pair_list(edit):
        before, after = _flat(p.get('before')), _flat(p.get('after'))
        if before:
            text = text.replace(before, after)
    return text == _flat(new_text.replace('\n', ''))


def _old_with_date(edit, old_text, diff):
    """前回の本文（空白とタグを落とした文字列）。決めた修正で「更新」の日付が適用日に変わる記事は、その行を先に直す。"""
    lines = old_text.split('\n')
    if edit.get('update_date_display'):
        day = str(edit.get('from', ''))
        old_dates = [x[1:] for x in diff if x[:1] == '-' and not x.startswith('---') and _DATE_LINE.match(x[1:])]
        if old_dates and ('+' + day) in diff:
            lines[lines.index(old_dates[0])] = day
    return _flat(''.join(lines))


def _replays_sentences(edit, old_text, new_text, diff):
    """事実訂正（文の単位）：前回の本文に決めた文の置き換えを当てると、今回の本文と一字一句同じになるか（2026-10-20）。

    置き換えは、修正前の文が前回の本文にあり、修正後の文が今回の本文にあるものだけ当てる（何回かに分けて直した週も通るように）。
    1つも当たらなければ想定内にしない。"""
    text = _old_with_date(edit, old_text, diff)
    target = _flat(new_text.replace('\n', ''))
    hit = 0
    for p in _pair_list(edit):
        before, after = _flat(p.get('before')), _flat(p.get('after'))
        if before and before in text and after in target:
            text = text.replace(before, after)
            hit += 1
    return hit > 0 and text == target


# 事実訂正（2026-10-20 準備）の修正前後の文。列：E番号・slug・修正前・修正後（1行1文。同じ記事の文は何行でもよい）
FACT_SENTENCES = os.path.join(HERE, 'drift', 'fact_correction_sentences.csv')


def load_fact_correction_edits(sentences_path=None, corrections_path=None, keep_pending=False):
    """事実訂正の記事ごとの「決めた修正」（expected_edit_for に渡す形）。時刻と文の両方がある記事だけ
    （``keep_pending=True`` なら時刻の無い記事も from を空で返す。箇所を数えるため）。

    from は fact_corrections.csv のその記事の最も早い訂正の日。記事の「更新」の日付が訂正の日に変わる行も想定内にする。"""
    import pool
    path = FACT_SENTENCES if sentences_path is None else sentences_path
    rows = pool.load_fact_corrections(corrections_path)
    at = pool.fact_correction_at_by_slug(corrections_path)
    sentences = {}
    if os.path.exists(path):
        for r in pool.read_csv(path):
            s = pool.slug(r.get('slug') or '')
            if s and (str(r.get('修正前') or '').strip() or str(r.get('修正後') or '').strip()):
                sentences.setdefault(s, []).append({'before': r.get('修正前') or '', 'after': r.get('修正後') or ''})
    out = []
    for s in sorted({r['slug'] for r in rows} | (set(sentences) if keep_pending else set())):
        if s not in sentences or (s not in at and not keep_pending):
            continue
        eids = sorted({r['eid'] for r in rows if r['slug'] == s and r['eid']})
        revs = sorted({r['revision'] for r in rows if r['slug'] == s and r['revision']})
        tag = '・'.join(eids) + (f"・リビジョン {'・'.join(revs)}" if revs else '')
        out.append({'slug': s, 'from': at[s].date().isoformat() if s in at else '', 'mode': 'sentences',
                    'intervention': f'事実訂正（{tag}）' if tag else '事実訂正',
                    'paragraphs': sentences[s], 'update_date_display': True})
    return out


def fact_sentence_edits(with_pending=False, corrections_path=None, sentences_path=None, edits_path=None):
    """事実訂正（文の単位）の決めた修正の全部：expected_edits.json の sentences の項目と fact_correction_sentences.csv。"""
    js = [e for e in load_expected_edits(edits_path, keep_pending=with_pending, corrections_path=corrections_path)
          if e.get('mode') == 'sentences']
    return js + load_fact_correction_edits(sentences_path, corrections_path, keep_pending=with_pending)


def fact_correction_pending(corrections_path=None, sentences_path=None, edits_path=None):
    """fact_corrections.csv に載っているが、時刻か修正前後の文が無い記事（想定内にできない）。"""
    import pool
    listed = {r['slug'] for r in pool.load_fact_corrections(corrections_path)}
    ready = {pool.slug(e.get('slug') or '')
             for e in fact_sentence_edits(False, corrections_path, sentences_path, edits_path)}
    return listed - ready


def markup_diff(before, after, limit=6, ctx=60):
    """HTML の違う箇所を最大 limit 件、前後 ctx 文字つきで返す（テキストが同じ記事の原因を示すため）。"""
    sm = difflib.SequenceMatcher(None, before, after, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        out.append(f'{op}: …{before[max(0, i1 - ctx):i2 + ctx]}… → …{after[max(0, j1 - ctx):j2 + ctx]}…')
        if len(out) >= limit:
            break
    return out
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


def post_baseline_exists():
    """処置後の基準（manifest・テキスト・HTML のどれか）が既にあるか。"""
    return os.path.exists(POST_MANIFEST) or any(
        os.path.isdir(d) and os.listdir(d) for d in (POST_SNAP_DIR, POST_HTML_DIR))


def post_baseline_checked():
    """既にある処置後の基準の取得日（無ければ ''）。日誌に旧と新を並べるため。"""
    if not os.path.exists(POST_MANIFEST):
        return 'manifest なし' if post_baseline_exists() else ''
    days = {v.get('checked', '') for v in json.load(io.open(POST_MANIFEST, encoding='utf-8')).values()}
    return '・'.join(sorted(d for d in days if d)) or '不明'


def post_baseline_guard(force, reason):
    """処置後の基準を取り直してよいか。止めるときは理由の文、よければ None（2026-10-01）。

    9/30 に取った処置後の基準は、10/5 の回で「9/29〜30 の処置による変化」と
    「10/1 以降の想定外の変化」を分ける物差し。取り直すと今の本文が基準になり、
    10/1 以降に起きた変化が見えなくなる。取得の途中でもファイルを書くので、取る前に止める。
    """
    if not post_baseline_exists():
        return None
    if not force:
        return (f'★処置後の基準（{post_baseline_checked()} 取得）が既にある。取り直さない。'
                '置き換えるときは --force と --reason "理由" を付ける')
    if not str(reason or '').strip():
        return '★--force には --reason "理由" が必要（日誌に残す）'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', action='store_true', help='基準を取り直す（差分は出さない）')
    ap.add_argument('--post-baseline', action='store_true',
                    help='処置後の基準を drift/post_treatment/ に取る（通常の基準・差分には触れない）')
    ap.add_argument('--sleep', type=float, default=1.0)
    ap.add_argument('--out-dir', default=os.path.join(ROOT, 'output', 'reports'))
    ap.add_argument('--force', action='store_true',
                    help='既にある処置後の基準を取り直して置き換える（--reason 必須・日誌に記録）')
    ap.add_argument('--reason', default='', help='--force の理由（日誌に残す）')
    a = ap.parse_args()

    os.makedirs(SNAP_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    if a.post_baseline:
        stop = post_baseline_guard(a.force, a.reason)
        if stop:
            print(stop, file=sys.stderr)
            return 3
        previous = post_baseline_checked()
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
            # HTML も残す（2026-09-30）。「テキストは同じで HTML だけ違う」を 10/5 に差分で示せるようにするため
            os.makedirs(POST_HTML_DIR, exist_ok=True)
            with gzip.open(os.path.join(POST_HTML_DIR, f'{slug}.html.gz'), 'wt', encoding='utf-8') as g:
                g.write(body)
            time.sleep(a.sleep)
        if bad:
            print(f'★{len(bad)} 本を取得できないため処置後の基準を保存しない：{bad}')
            return 1
        json.dump(post, io.open(POST_MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'処置後の基準 {len(post)} 本 → {POST_MANIFEST}')
        if previous:
            force_log.record('drift_check.py', '処置後の基準（drift/post_treatment/ のハッシュと HTML）',
                             a.reason.strip(), f'取得日 {previous} → {today}・{len(post)}本')
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

    new, changed, failed, markup_only, author_expected = {}, [], [], [], []
    edits, edit_expected = load_expected_edits() + load_fact_correction_edits(), []
    fact_pending = fact_correction_pending()
    edit_slugs = {e.get('slug') for e in edits} | fact_pending
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
            edit = expected_edit_for(slug, diff, today, edits, '\n'.join(before), text) if diff else None
            if diff and author_only_change(diff, today):
                author_expected.append(item)
                print(f'  ○想定内の変化 {slug}（著者表示の変更 I-31・I-32 の行だけ）')
            elif edit:
                item['edit'] = edit
                edit_expected.append(item)
                print(f'  ○想定内の変化 {slug}（決めた修正 {edit.get("intervention", "")} の段落だけ）')
            elif diff:
                if slug in fact_pending:
                    item['fact_pending'] = True
                elif slug in edit_slugs:
                    item['edit_outside'] = True
                changed.append(item)
                print(f'  ★変化あり {slug}（{len(diff)} 行の差分）')
            else:
                # 本文テキストは同じで HTML だけが違う（2026-09-30）。9/18→9/21→9/30 で47本が ±7 バイト往復した例があり、
                # 　テキストの変化と同じ扱いにすると本物の変化が埋もれる。ただしリンク先・属性の変化もここに入るため、別枠で必ず出す
                ref_html = os.path.join(POST_HTML_DIR, f'{slug}.html.gz')
                if ref_kind == 'post_treatment' and os.path.exists(ref_html):
                    with gzip.open(ref_html, 'rt', encoding='utf-8') as g:
                        item['markup'] = markup_diff(g.read(), body)
                markup_only.append(item)
                print(f'  △HTMLのみの変化 {slug}（本文テキストは同一）')
        io.open(snap, 'w', encoding='utf-8').write(text)
        time.sleep(a.sleep)

    json.dump(new, io.open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(new)} 本のハッシュを保存（失敗 {len(failed)} 本）→ {MANIFEST}')

    if first_run:
        print('基準を作りました。差分の判定は次回から。')
        return 0
    if not changed and not failed and not markup_only and not author_expected and not edit_expected:
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
         f'- 取得できなかった記事：{len(failed)} 本']
    if author_expected:
        L.append(f'- 想定内の変化（著者表示の変更 I-31・I-32 の行だけ）：{len(author_expected)} 本')
    if edit_expected:
        L.append(f'- 想定内の変化（実験期間中に入れると決めた修正の段落だけ）：{len(edit_expected)} 本')
    L.append('')
    if edit_expected:
        L += ['## 想定内の変化（実験期間中に入れると決めた修正）', '',
              '差分の行がすべて、決めた修正の段落の中（修正前の段落の一部が消え、修正後の段落の一部が足された）だった記事。',
              '段落の外が1行でも変わった記事は下の「想定外」に出る。', '',
              '| slug | 介入 | 適用日 |', '|---|---|---|']
        L += [f'| {c["slug"]} | {c["edit"].get("intervention", "")} | {c["edit"].get("from", "")} |'
              for c in edit_expected]
        L.append('')
    if author_expected:
        L += ['## 想定内の変化（著者表示の変更・2026-10-09 19:42）', '',
              '差分の行がすべて著者表示の行（冒頭の「著者：本田正憲」・末尾の新しい著者欄・オフにしたテーマ標準の著者ボックス）だった記事。',
              '本文の変化ではない。全ページ一律・4組に同条件（interventions.csv I-31・I-32）。著者欄以外の行が1行でも変わった記事は下の「想定外」に出る。', '',
              ', '.join(c['slug'] for c in author_expected), '']
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
        shown = [c for c in markup_only if c.get('markup')][:3]
        for c in shown:   # 処置後の基準の HTML があるときだけ、どこが違うかを示す（最大3本）
            L += ['', f'### {c["slug"]}：HTML の違う箇所', '', '`' * 3] + c['markup'] + ['`' * 3]
        L.append('')
    for c in changed:
        L += [f'## {c["url"]}', '']
        if c.get('fact_pending'):
            L += ['**この記事は事実訂正の対象（fact_corrections.csv）。ただし訂正の時刻か修正前後の文'
                  '（drift/expected_edits.json の mode=sentences の項目か drift/fact_correction_sentences.csv）が記録待ちのため、想定内か確かめられない。想定外として扱う**', '']
        if c.get('edit_outside'):
            L += ['**この記事は実験期間中に入れると決めた修正（drift/expected_edits.json）の対象。'
                  'ただし、決めた段落の外も変わっている（または決めた内容と違う）。想定外として扱う**', '']
        L += [
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
