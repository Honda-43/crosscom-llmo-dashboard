"""looker_tabs.py — Looker Studio 用の表示タブを組み立てる(Phase 6 §1).

Looker Studio はレイアウトをAPIで構築できない。そこで計算・判定・整形はすべて
パイプライン側で終わらせ、Looker は「シートのタブを置くだけ」で8面相当が
並ぶ状態にする。順位の代理値・四象限・期限までの日数といった、本来なら
Looker側の計算式になるものもここで確定させる。

この層は純関数の集まりで Sheets には触らない(書き込みは sheets_writer)。
入力は呼び出し側が読み込み済みの行だけで、ここから追加の読み取りはしない。
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import analyze_diff
import retired_urls
import display_map
import notify_slack
import verdicts
from analyze_diff import parse_bool, parse_rank
from settings import SELF_ENTITY, load_prompts

WINDOW_DAYS = 7
LOOKBACK_DAYS = 28
ANSWER_DAYS = 14
# Google Sheets のセル上限は50,000字。指示書の指定どおり40,000字で切り詰める。
ANSWER_CHAR_LIMIT = 40_000
TRUNCATION_MARK = "…(以下省略)"

SCATTER_ENTITIES = 10
TREND_ENTITIES = 5

ENTITY_PROMPT_ID = "E-1"
MISSING = display_map.MISSING

FACE_NAMES: Dict[str, str] = {
    "R1": "全体サマリ",
    "R2": "言及率トレンド",
    "R3": "ネガ検知",
    "R4": "獲得マップ",
    "R5": "競合ポジション",
    "R6": "情報源分析",
    "R7": "成果指標",
    "R8": "アクションボード",
}

# 順位の縦軸が何に基づくか。自社だけが推薦リスト内の実順位を抽出できている
# (§4の抽出スキーマは凍結のため競合の実順位は取得していない)。
RANK_SOURCE_SELF = "実順位"
RANK_SOURCE_PROXY = "シェア順位による代理値"

# lk_events に載せる変化と、その日本語名・プレイブックの参照先。
# すべての change_type を載せると読めなくなるので、判断に効くものだけに絞る。
EVENT_NAMES: Dict[str, str] = {
    analyze_diff.NEGATIVE_ON: "ネガ検知",
    analyze_diff.MENTION_LOST: "言及消失",
    analyze_diff.MENTION_GAINED: "言及獲得",
    analyze_diff.URL_REMOVED: "引用喪失",
    analyze_diff.COMPETITOR_ADDED: "競合上位入り",
}
PLAYBOOK_REFS: Dict[str, str] = {
    analyze_diff.NEGATIVE_ON: "P-7",
    analyze_diff.MENTION_LOST: "P-2",
    analyze_diff.MENTION_GAINED: MISSING,   # 単発の獲得に対応する節はない
    analyze_diff.URL_REMOVED: "P-8",
    analyze_diff.COMPETITOR_ADDED: "P-DROP",
}
# 「上位入り」と呼べるのは当日の言及シェア上位に入った競合だけ。この絞りが
# ないと、回答に一度出ただけの社名で lk_events が埋まる。
COMPETITOR_TOP_N = 5


# --------------------------------------------------------------------------
# 小さな共通処理
# --------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(row: Dict[str, Any]) -> str:
    return str(row.get("date") or "").strip()


def window_of(date: str, days: int) -> Tuple[str, str]:
    """``date`` で終わる ``days`` 日の窓(両端を含む)。"""
    end = dt.date.fromisoformat(date)
    return (end - dt.timedelta(days=days - 1)).isoformat(), date


def in_window(row: Dict[str, Any], window: Tuple[str, str]) -> bool:
    day = _day(row)
    return bool(day) and window[0] <= day <= window[1]


def _flag(value: bool) -> str:
    """Looker のフィルタで使う真偽値。board_daily の noise_flag と同じ形式。"""
    return "TRUE" if value else "FALSE"


def prompt_names() -> Dict[str, str]:
    """「A-1 導入検討初期」形式の短縮名(config/prompts.yaml の cep 先頭)。

    cep をそのまま出すとヒートマップの行ラベルが長すぎて読めないため、
    区切りの手前だけを取る。
    """
    out: Dict[str, str] = {}
    for prompt in load_prompts():
        prompt_id = str(prompt.get("id") or "").strip()
        head = str(prompt.get("cep") or "").strip()
        for separator in ("・", "+", "/", "、"):
            head = head.split(separator)[0]
        out[prompt_id] = f"{prompt_id} {head}".strip()
    return out


# --------------------------------------------------------------------------
# 観測から派生データを復元する
# --------------------------------------------------------------------------
# 日次パイプラインは llm_observations を既に読んでいる。言及率の履歴も
# 言及シェアの履歴もそこから同じ式で復元できるので、daily_summary や
# sov_daily をあらためて読み直さない(§8 のAPI予算)。
def summary_rows_from_observations(
    observations: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """日ごとの言及率を復元する。daily_summary と同じ定義。

    分母は E-1 を除く有効観測(mention が空= エラー行は除く)。
    """
    by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in observations:
        day = _day(row)
        if day:
            by_date[day].append(row)

    def rate(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
        valid = [r for r in rows if parse_bool(r.get("mention")) is not None]
        if not valid:
            return None
        hits = sum(1 for r in valid if parse_bool(r.get("mention")) is True)
        return round(hits / len(valid), 4)

    out: List[Dict[str, Any]] = []
    for day in sorted(by_date):
        rows = by_date[day]
        non_entity = [r for r in rows
                      if str(r.get("prompt_id") or "").strip() != ENTITY_PROMPT_ID]
        out.append({
            "date": day,
            "mention_rate_all": rate(non_entity),
            "mention_rate_pillar_a": rate([r for r in non_entity
                                           if str(r.get("pillar") or "") == "A"]),
            "mention_rate_pillar_b": rate([r for r in non_entity
                                           if str(r.get("pillar") or "") == "B"]),
        })
    return out


def sov_rows_from_observations(
    observations: Sequence[Dict[str, Any]],
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """言及シェアの履歴を観測から再計算する(sov_daily を読まずに済ませる)。"""
    import backfill_sov

    return backfill_sov.build_rows(observations, since=since, until=until,
                                  verbose=False)


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 4) if values else None


def mention_rate_window(summary_rows: Sequence[Dict[str, Any]], date: str,
                        column: str = "mention_rate_all",
                        days: int = WINDOW_DAYS) -> Optional[float]:
    window = window_of(date, days)
    values = [v for v in (_num(r.get(column)) for r in summary_rows if in_window(r, window))
              if v is not None]
    return _mean(values)


# --------------------------------------------------------------------------
# lk_verdicts — 判定欄
# --------------------------------------------------------------------------
def _zero_cells(observations: Sequence[Dict[str, Any]], date: str) -> Tuple[int, str]:
    """直近7日で一度も言及されなかった prompt_id × model(E-1 は除く)。"""
    window = window_of(date, WINDOW_DAYS)
    mentioned: Dict[Tuple[str, str], int] = defaultdict(int)
    seen: set = set()
    for row in observations:
        if not in_window(row, window):
            continue
        mention = parse_bool(row.get("mention"))
        if mention is None:
            continue
        key = (str(row.get("prompt_id") or "").strip(),
               str(row.get("model") or "").strip())
        seen.add(key)
        mentioned[key] += 1 if mention else 0

    zeros = sorted(f"{p}×{m}" for (p, m) in seen
                   if mentioned[(p, m)] == 0 and p != ENTITY_PROMPT_ID)
    label = "、".join(zeros[:5])
    if len(zeros) > 5:
        label += f" ほか{len(zeros) - 5}件"
    return len(zeros), label


def self_rank_median(observations: Sequence[Dict[str, Any]], date: str,
                     days: int = LOOKBACK_DAYS) -> Optional[float]:
    """推薦リスト内の自社の順位中央値。抽出できているのは自社のみ。"""
    window = window_of(date, days)
    ranks = [r for r in (parse_rank(row.get("rank")) for row in observations
                         if in_window(row, window)) if r is not None]
    return float(statistics.median(ranks)) if ranks else None


def share_table(sov_rows: Sequence[Dict[str, Any]], date: str,
                days: int) -> Dict[str, Any]:
    """``date`` で終わる窓の pillar=all の言及シェア。

    分母は日ごとの observed_total の合計。日によって観測数が違うため、
    単純な件数比ではなく観測数で割る。
    """
    window = window_of(date, days)
    rows = [r for r in sov_rows
            if str(r.get("pillar") or "") == "all" and in_window(r, window)]
    counts: Counter = Counter()
    observed_by_day: Dict[str, float] = {}
    for row in rows:
        entity = str(row.get("entity") or "").strip()
        if entity:
            counts[entity] += _num(row.get("mention_count")) or 0
        observed = _num(row.get("observed_total")) or 0
        day = _day(row)
        observed_by_day[day] = max(observed_by_day.get(day, 0.0), observed)
    observed = sum(observed_by_day.values())
    shares = {e: (c / observed if observed else 0.0) for e, c in counts.items()}
    # 件数が同じ会社の順序が実行ごとに揺れないよう社名まで見て並べる。
    ranking = sorted(counts, key=lambda e: (-counts[e], e))
    return {"counts": dict(counts), "shares": shares, "ranking": ranking,
            "observed": observed}


def _self_position(table: Dict[str, Any]) -> Dict[str, Any]:
    ranking = table["ranking"]
    if SELF_ENTITY not in ranking:
        return {"rank": None, "share": None, "top": MISSING, "gap": None}
    rank = ranking.index(SELF_ENTITY) + 1
    share = table["shares"].get(SELF_ENTITY, 0.0)
    top = ranking[0]
    gap = None if top == SELF_ENTITY else round(table["shares"][top] - share, 4)
    return {"rank": rank, "share": round(share, 4), "top": top, "gap": gap}


def actions_as_of(action_rows: Sequence[Dict[str, Any]],
                  date: str) -> List[Dict[str, Any]]:
    """``date`` 時点で存在していた施策だけを返す。

    過去日の判定を作るとき、その日にはまだ提案も実施もされていない施策を
    「直近の施策」に選ぶと、経過日数が負になるなど意味の通らない文になる。
    状態そのものは現在値しか残っていないので復元できないが、少なくとも
    「その日にはまだ無かった」ものは持ち込まない。
    """
    out: List[Dict[str, Any]] = []
    for row in action_rows:
        proposed = verdicts._date(row.get("提案日"))
        if proposed is not None and proposed.isoformat() > date:
            continue          # その日にはまだ提案されていない
        shown = dict(row)
        done = verdicts._date(row.get("実施日"))
        if done is not None and done.isoformat() > date:
            shown["実施日"] = ""   # その日にはまだ実施していない
        out.append(shown)
    return out


def face_contexts(
    date: str,
    *,
    observations: Sequence[Dict[str, Any]] = (),
    summary_rows: Sequence[Dict[str, Any]] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    action_rows: Sequence[Dict[str, Any]] = (),
    ga4_rows: Sequence[Dict[str, Any]] = (),
    gsc_rows: Sequence[Dict[str, Any]] = (),
    citation_rows: Sequence[Dict[str, Any]] = (),
    noise_floor: float = 10.0,
) -> Dict[str, Dict[str, Any]]:
    """8面それぞれの判定コンテキスト。アプリの各面と同じ値を使う。"""
    week = window_of(date, WINDOW_DAYS)
    rate_now = mention_rate_window(summary_rows, date)
    previous_end = (dt.date.fromisoformat(date) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    rate_prev = mention_rate_window(summary_rows, previous_end)
    delta = (None if rate_now is None or rate_prev is None
             else round(rate_now - rate_prev, 4))

    negatives = sum(
        1 for r in observations
        if in_window(r, week) and bool(parse_bool(r.get("negative_or_outdated")))
    )
    ai_sessions = sum(_num(r.get("sessions")) or 0 for r in ga4_rows if in_window(r, week))
    clicks = sum(_num(r.get("clicks")) or 0 for r in gsc_rows if in_window(r, week))

    table = share_table(sov_rows, date, LOOKBACK_DAYS)
    position = _self_position(table)
    zero_count, zero_label = _zero_cells(observations, date)

    absent = [r for r in citation_rows if r.get("category") == "自社不在"]
    absent.sort(key=lambda r: (-(_num(r.get("cited_count")) or 0), str(r.get("domain"))))
    self_domains = sum(_num(r.get("cited_count")) or 0
                       for r in citation_rows if r.get("category") == "自社")

    base: Dict[str, Any] = dict(
        negative_streak_days=negative_streak_days(observations, date),
        negative_count_7d=negatives,
        mention_rate_all_7d=rate_now,
        mention_rate_delta_7d=delta,
        ai_sessions_wk=ai_sessions,
        branded_clicks_wk=clicks,
        kgi_noise=max(ai_sessions, clicks) < noise_floor,
        noise_floor=noise_floor,
    )
    per_face: Dict[str, Dict[str, Any]] = {
        "R4": dict(zero_cells=zero_count, zero_cells_label=zero_label),
        "R5": dict(
            self_share=position["share"], self_share_rank=position["rank"],
            self_rank_median=self_rank_median(observations, date),
            top_competitor=position["top"], share_gap_to_top=position["gap"],
        ),
        "R6": dict(
            absent_domains=len(absent),
            top_absent_domain=str(absent[0]["domain"]) if absent else MISSING,
            top_absent_count=int(_num(absent[0].get("cited_count")) or 0) if absent else 0,
            self_domain_count=int(self_domains),
        ),
    }

    known = actions_as_of(action_rows, date)
    out: Dict[str, Dict[str, Any]] = {}
    for face in FACE_NAMES:
        scoped = verdicts.actions_for_face(face, known)
        out[face] = verdicts.build_context(
            date, scoped, **{**base, **per_face.get(face, {})}
        )
    return out


def negative_streak_days(observations: Sequence[Dict[str, Any]], date: str) -> int:
    """いずれかのプロンプトで検知が続いている日数。0なら当日は検知なし。"""
    by_date: Dict[str, bool] = {}
    for row in observations:
        day = _day(row)
        if not day or day > date:
            continue
        flag = bool(parse_bool(row.get("negative_or_outdated")))
        by_date[day] = by_date.get(day, False) or flag
    streak = 0
    for day in sorted(by_date, reverse=True):
        if not by_date[day]:
            break
        streak += 1
    return streak


def verdict_rows(date: str, contexts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """lk_verdicts の行。判定文は verdicts.py のテンプレート出力そのまま。"""
    rows = []
    for face, name in FACE_NAMES.items():
        context = contexts.get(face)
        if context is None:
            continue
        text = verdicts.render(face, context) or ""
        rows.append({"date": date, "face": face, "face_name": name,
                     "verdict_text": text})
    return rows


# --------------------------------------------------------------------------
# lk_heatgrid — 獲得マップ
# --------------------------------------------------------------------------
def heatgrid_rows(date: str,
                  observations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """直近7日の prompt_id × model ごとの言及日数。cell_label は「5/7」形式。"""
    window = window_of(date, WINDOW_DAYS)
    names = prompt_names()
    mentioned: Dict[Tuple[str, str], int] = defaultdict(int)
    observed: Dict[Tuple[str, str], int] = defaultdict(int)

    for row in observations:
        if not in_window(row, window):
            continue
        mention = parse_bool(row.get("mention"))
        if mention is None:
            continue
        key = (str(row.get("prompt_id") or "").strip(),
               str(row.get("model") or "").strip())
        observed[key] += 1
        if mention:
            mentioned[key] += 1

    rows = []
    for key in sorted(observed):
        prompt_id, model = key
        rows.append({
            "date": date,
            "prompt_id": prompt_id,
            "prompt_name": names.get(prompt_id, prompt_id),
            "model": model,
            "days_mentioned_7d": mentioned[key],
            "cell_label": f"{mentioned[key]}/{observed[key]}",
        })
    return rows


# --------------------------------------------------------------------------
# lk_scatter — 競合ポジション
# --------------------------------------------------------------------------
def scatter_rows(date: str, sov_rows: Sequence[Dict[str, Any]],
                 observations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """上位10社+クロスコムの散布図データ。四象限まで確定させて渡す。"""
    table = share_table(sov_rows, date, LOOKBACK_DAYS)
    recent = share_table(sov_rows, date, WINDOW_DAYS)
    ranking = table["ranking"]
    if not ranking:
        return []

    chosen = list(ranking[:SCATTER_ENTITIES])
    if SELF_ENTITY in ranking and SELF_ENTITY not in chosen:
        chosen.append(SELF_ENTITY)

    own_rank = self_rank_median(observations, date)
    # 競合の実順位は取得していないため、言及シェアの順位を縦軸の代理値に置く。
    axis = {e: (own_rank if e == SELF_ENTITY else float(ranking.index(e) + 1))
            for e in chosen}
    plotted = {e: v for e, v in axis.items() if v is not None}
    if not plotted:
        return []

    share_mid = statistics.median([table["shares"][e] for e in plotted])
    rank_mid = statistics.median(list(plotted.values()))

    rows = []
    for entity in chosen:
        value = axis[entity]
        is_self = entity == SELF_ENTITY
        share = table["shares"].get(entity, 0.0)
        if value is None:
            quadrant = MISSING
        else:
            quadrant = ("高シェア" if share >= share_mid else "低シェア") + "×" + \
                       ("上位" if value <= rank_mid else "下位")
        rows.append({
            "date": date,
            "entity": entity,
            "share_28d": f"{share:.4f}",
            "rank_median": "" if value is None else f"{value:g}",
            "rank_source": RANK_SOURCE_SELF if is_self else RANK_SOURCE_PROXY,
            "size_7d": int(recent["counts"].get(entity, 0)),
            "is_crosscom": _flag(is_self),
            "quadrant": quadrant,
        })
    return rows


# --------------------------------------------------------------------------
# lk_sov_trend — 言及シェア推移
# --------------------------------------------------------------------------
def trend_entities(sov_rows: Sequence[Dict[str, Any]], date: str) -> List[str]:
    """線に出す会社。上位5社+クロスコム。

    Looker側で系列を絞れないので、ここで固定した集合に限る。日ごとに
    選び直すと線が入れ替わり、推移として読めなくなる。
    """
    ranking = share_table(sov_rows, date, LOOKBACK_DAYS)["ranking"]
    chosen = [e for e in ranking[:TREND_ENTITIES]]
    if SELF_ENTITY not in chosen:
        chosen.append(SELF_ENTITY)
    return chosen


def sov_trend_rows(date: str, sov_rows: Sequence[Dict[str, Any]],
                   entities: Optional[Sequence[str]] = None,
                   dates: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """7日移動平均済みの言及シェア。``dates`` を渡すと過去分もまとめて作る。"""
    chosen = list(entities) if entities is not None else trend_entities(sov_rows, date)
    days = list(dates) if dates is not None else [date]

    rows = []
    for day in sorted(days):
        table = share_table(sov_rows, day, WINDOW_DAYS)
        if not table["observed"]:
            continue
        for entity in chosen:
            rows.append({
                "date": day,
                "entity": entity,
                "share_7d": f"{table['shares'].get(entity, 0.0):.4f}",
                "is_crosscom": _flag(entity == SELF_ENTITY),
            })
    return rows


# --------------------------------------------------------------------------
# lk_negative — ネガ検知カレンダー
# --------------------------------------------------------------------------
def negative_rows(date: str, observations: Sequence[Dict[str, Any]],
                  dates: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """モデル別の検知カレンダー。note は Slack と同じ種別要約(20字以内)。"""
    wanted = set(dates) if dates is not None else {date}
    seen_models = sorted({str(r.get("model") or "").strip() for r in observations
                          if str(r.get("model") or "").strip()})

    detected: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    observed: set = set()
    for row in observations:
        day = _day(row)
        model = str(row.get("model") or "").strip()
        if day not in wanted or not model:
            continue
        if parse_bool(row.get("mention")) is None:
            continue  # エラー行は観測なしとして扱う
        observed.add((day, model))
        if bool(parse_bool(row.get("negative_or_outdated"))):
            detected[(day, model)].append(str(row.get("negative_detail") or ""))

    rows = []
    for day in sorted(wanted):
        for model in seen_models:
            if (day, model) not in observed:
                continue
            details = detected.get((day, model)) or []
            kinds = [notify_slack.negative_kind(d) for d in details]
            # 同じ日に複数の検知があっても代表を1つだけ出す(最頻・同数なら先頭)。
            note = Counter(kinds).most_common(1)[0][0] if kinds else ""
            rows.append({
                "date": day,
                "model": model,
                "detected": 1 if details else 0,
                "note": note,
            })
    return rows


# --------------------------------------------------------------------------
# lk_events — 重要な変化
# --------------------------------------------------------------------------
def event_rows(date: str, changes: Sequence[Dict[str, Any]],
               sov_rows: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """判断に効く変化だけを日本語名で並べる。"""
    top = share_table(sov_rows, date, WINDOW_DAYS)["ranking"][:COMPETITOR_TOP_N] \
        if sov_rows else []

    rows = []
    for change in changes:
        if _day(change) != date:
            continue
        change_type = str(change.get("change_type") or "").strip()
        if change_type not in EVENT_NAMES:
            continue
        detail = str(change.get("detail") or "").strip()
        if change_type == analyze_diff.COMPETITOR_ADDED and detail not in top:
            continue  # 上位に入っていない社名は「上位入り」ではない
        rows.append({
            "date": date,
            "event_type": change_type,
            "event_name": EVENT_NAMES[change_type],
            "place": f"{change.get('prompt_id')} × {change.get('model')}",
            "detail": detail,
            "playbook_ref": PLAYBOOK_REFS[change_type],
        })
    rows.sort(key=lambda r: (r["event_name"], r["place"], r["detail"]))
    return rows


# --------------------------------------------------------------------------
# lk_actions — アクションボード表示用
# --------------------------------------------------------------------------
def action_display_rows(action_rows: Sequence[Dict[str, Any]],
                        today: str) -> List[Dict[str, Any]]:
    """action_log の表示用ミラー。元のタブは本田さんの編集用なので触らない。"""
    reference = dt.date.fromisoformat(today)
    rows = []
    for row in action_rows:
        action_id = str(row.get("action_id") or "").strip()
        if not action_id:
            continue
        deadline = verdicts._date(row.get("判断期限"))
        rows.append({
            "action_id": action_id,
            "priority": str(row.get("優先度") or "").strip(),
            "content": str(row.get("内容") or "").strip(),
            "target_display": display_map.target(row.get("対象")),
            "rule_id": str(row.get("根拠rule_id") or "").strip() or MISSING,
            "status": str(row.get("状態") or "").strip(),
            "proposed": str(row.get("提案日") or "").strip(),
            "executed": str(row.get("実施日") or "").strip(),
            "deadline": str(row.get("判断期限") or "").strip(),
            "days_to_deadline": "" if deadline is None else (deadline - reference).days,
        })
    rows.sort(key=lambda r: r["action_id"])
    return rows


# --------------------------------------------------------------------------
# lk_answers — 回答全文の閲覧用
# --------------------------------------------------------------------------
def _truncate(text: str, limit: int = ANSWER_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - len(TRUNCATION_MARK)] + TRUNCATION_MARK


def answer_rows(date: str, raw_records: Sequence[Dict[str, Any]],
                observations: Sequence[Dict[str, Any]],
                days: int = ANSWER_DAYS) -> List[Dict[str, Any]]:
    """直近 ``days`` 日の回答全文。差分表示は Looker では組めないので対象外。"""
    window = window_of(date, days)
    index: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in observations:
        index[(_day(row), str(row.get("prompt_id") or "").strip(),
               str(row.get("model") or "").strip())] = row

    rows = []
    for record in raw_records:
        if not in_window(record, window):
            continue
        key = (_day(record), str(record.get("prompt_id") or "").strip(),
               str(record.get("model") or "").strip())
        observation = index.get(key) or {}
        mention = parse_bool(observation.get("mention"))
        rank = parse_rank(observation.get("rank"))
        rows.append({
            "date": key[0],
            "prompt_id": key[1],
            "model": key[2],
            "mention": "" if mention is None else ("あり" if mention else "なし"),
            "rank": "" if rank is None else rank,
            "answer_text": _truncate(str(record.get("answer") or "")),
        })
    rows.sort(key=lambda r: (r["date"], r["prompt_id"], r["model"]))
    return rows


# --------------------------------------------------------------------------
# まとめ
# --------------------------------------------------------------------------
def build_all(
    date: str,
    *,
    observations: Sequence[Dict[str, Any]] = (),
    summary_rows: Sequence[Dict[str, Any]] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    changes: Sequence[Dict[str, Any]] = (),
    action_rows: Sequence[Dict[str, Any]] = (),
    ga4_rows: Sequence[Dict[str, Any]] = (),
    gsc_rows: Sequence[Dict[str, Any]] = (),
    citation_rows: Sequence[Dict[str, Any]] = (),
    raw_records: Sequence[Dict[str, Any]] = (),
    contexts: Optional[Dict[str, Dict[str, Any]]] = None,
    noise_floor: float = 10.0,
) -> Dict[str, List[Dict[str, Any]]]:
    """日次で書き出す lk_* 一式。キーはタブ名。

    ``contexts`` は board_daily の verdict_r1 と共用するため、呼び出し側が
    先に作ったものを渡せる(同じ判定を二度組み立てないため)。
    """
    if contexts is None:
        contexts = face_contexts(
            date, observations=observations, summary_rows=summary_rows,
            sov_rows=sov_rows, action_rows=action_rows, ga4_rows=ga4_rows,
            gsc_rows=gsc_rows, citation_rows=citation_rows, noise_floor=noise_floor,
        )
    return {
        "lk_verdicts": verdict_rows(date, contexts),
        "lk_heatgrid": heatgrid_rows(date, observations),
        "lk_scatter": scatter_rows(date, sov_rows, observations),
        "lk_sov_trend": sov_trend_rows(date, sov_rows),
        "lk_negative": negative_rows(date, observations),
        # 取り下げたURLの引用は changes 由来ではないので別立てで足す(A-011)。
        # 参照面が入れ替わるまでのラグを実測するため、0件の日も行を出す。
        # 引用URLの全量は生データにしかない(シートの cited_crosscom_urls は
        # 自社ドメインだけ)。外部ドメインを数えるので raw_records を渡す。
        "lk_events": (event_rows(date, changes, sov_rows)
                      + retired_urls.event_rows(date, raw_records, resolve=True)),
        "lk_actions": action_display_rows(action_rows, date),
        "lk_answers": answer_rows(date, raw_records, observations),
    }


def verdict_for_face(contexts: Dict[str, Dict[str, Any]], face: str) -> str:
    """board_daily に載せる1面分の判定文。"""
    context = contexts.get(face)
    return (verdicts.render(face, context) or "") if context else ""
