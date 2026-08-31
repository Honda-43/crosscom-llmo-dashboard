"""verdicts.py — 判定欄の決定的な生成(Phase 5 §2).

各面の下部に出す「判定:」文を、LLMを使わずテンプレートで作る。
文面は config/verdict_templates.yaml にあり、コードは条件評価と値の差し込みだけを行う。

なぜLLMを使わないか:
判定欄は毎週同じ基準で読まれる。同じ状態なら同じ文が出ることが前提で、
言い回しが週ごとに揺れると「変わったのは状態か文章か」が判別できなくなる。

テンプレートに無い文章は生成しない。数値は呼び出し側が渡した実値のみを使う。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional, Sequence

from settings import VERDICT_TEMPLATES_FILE, load_yaml

VERDICT_PREFIX = "判定:"

# 効果測定の窓。R3で「まだ入れ替わっていない(想定内)」と言える上限。
DEFAULT_EFFECT_WINDOW_DAYS = 28

# action_log の状態(§4)
STATUS_PROPOSED = "提案中"
STATUS_AWAITING = "承認待ち"
STATUS_APPROVED = "承認"
STATUS_MEASURING = "実施済み・効果測定中"
STATUS_DONE = "完了"
STATUS_REJECTED = "却下"
STATUS_ON_HOLD = "保留"

# 「実施済み」として扱う=グラフに縦線を引く対象(§4)
IMPLEMENTED_STATUSES = (STATUS_MEASURING, STATUS_DONE)
# まだ終わっていない=重複提案の判定に使う(§5)
OPEN_STATUSES = (STATUS_PROPOSED, STATUS_AWAITING, STATUS_APPROVED,
                 STATUS_MEASURING, STATUS_ON_HOLD)
# 決着済み=週次所見が同じ施策を「これからやること」として再提案してはいけない。
# 承認まで進んだものは本田さんの判断が既に済んでいるので、提案に戻さない。
SETTLED_STATUSES = (STATUS_APPROVED, STATUS_MEASURING, STATUS_DONE)


# --------------------------------------------------------------------------
# テンプレート
# --------------------------------------------------------------------------
_TEMPLATES: Optional[Dict[str, Any]] = None


def load_templates(force: bool = False) -> Dict[str, Any]:
    global _TEMPLATES
    if _TEMPLATES is None or force:
        _TEMPLATES = load_yaml(VERDICT_TEMPLATES_FILE) or {}
    return _TEMPLATES


_OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in b,
    "exists": lambda a, b: (a is not None) == bool(b),
}


def _matches(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    for field, tests in (condition or {}).items():
        value = context.get(field)
        for operator, expected in (tests or {}).items():
            check = _OPERATORS.get(operator)
            if check is None:
                raise ValueError(f"未知の演算子です: {operator}")
            if operator != "exists" and value is None:
                return False
            try:
                if not check(value, expected):
                    return False
            except TypeError:
                return False
    return True


class MissingPlaceholder(KeyError):
    """テンプレートが参照した変数がコンテキストに無い。"""


class _StrictContext(dict):
    def __missing__(self, key):  # noqa: D105
        raise MissingPlaceholder(key)


def render(face: str, context: Dict[str, Any],
           templates: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """``face`` の判定文。該当する分岐が無ければ None。

    上から順に評価し、最初に条件を満たしたものを採用する。
    """
    rules = (templates or load_templates()).get("faces", {}).get(face) or []
    for rule in rules:
        if _matches(rule.get("when") or {}, context):
            text = " ".join(str(rule.get("text", "")).split())
            # 未定義の変数を書いたテンプレートは MissingPlaceholder で落とす。
            # 静かに空欄になるより、テストで気付けるほうがよい。
            filled = text.format_map(
                context if isinstance(context, _StrictContext)
                else _StrictContext(context)
            )
            return f"{VERDICT_PREFIX}{filled}".strip()
    return None


def rule_id_for(face: str, context: Dict[str, Any],
                templates: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """どの分岐が採用されたか(テスト・デバッグ用)。"""
    rules = (templates or load_templates()).get("faces", {}).get(face) or []
    for rule in rules:
        if _matches(rule.get("when") or {}, context):
            return rule.get("id")
    return None


# --------------------------------------------------------------------------
# コンテキスト生成
# --------------------------------------------------------------------------
def _date(value: Any) -> Optional[dt.date]:
    text = str(value or "").strip()
    if not text or text in ("—", "-"):
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.0%}"


def _signed_pct(value: Optional[float]) -> str:
    if value is None:
        return "±0"
    if abs(value) < 0.005:
        return "±0"
    return f"{value:+.0%}"


def implemented_actions(action_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """グラフに縦線を引く対象。実施日があり、状態が実施済み以降のもの(§4)。"""
    out = []
    for row in action_rows:
        if str(row.get("状態", "")).strip() not in IMPLEMENTED_STATUSES:
            continue
        done = _date(row.get("実施日"))
        if done is None:
            continue
        out.append({
            "action_id": str(row.get("action_id", "")).strip(),
            "date": done,
            "label": str(row.get("内容", "")).strip()[:12],
            "name": str(row.get("内容", "")).strip(),
            "deadline": _date(row.get("判断期限")),
        })
    # 同じ日に複数実施することがあるので action_id まで見て順序を確定させる。
    # これがないと「直近の施策」がYAMLの行順で揺れる。
    return sorted(out, key=lambda a: (a["date"], a["action_id"]))


# 判定欄で「直近の施策」を選ぶとき、面ごとに関係する施策だけを見る。
# 全施策から最新を取ると、ネガ検知の面にKGI向けの施策が出てしまう。
FACE_ACTION_SCOPES: Dict[str, Dict[str, tuple]] = {
    "R3": {"rule_ids": ("R-P7", "R-P8")},   # ネガ検知に効く施策のみ
    "R7": {"targets": ("KGI",)},            # KGIに効く施策のみ
}


def filter_actions(action_rows: Sequence[Dict[str, Any]],
                   rule_ids: Sequence[str] = (),
                   targets: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """根拠rule_id / 対象で施策を絞る。条件を渡さなければ素通し。"""
    if not rule_ids and not targets:
        return list(action_rows)
    out = []
    for row in action_rows:
        if rule_ids and str(row.get("根拠rule_id", "")).strip() not in rule_ids:
            continue
        if targets and str(row.get("対象", "")).strip() not in targets:
            continue
        out.append(row)
    return out


def actions_for_face(face: str,
                     action_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """その面の判定欄が参照すべき施策。定義のない面は全施策。"""
    return filter_actions(action_rows, **FACE_ACTION_SCOPES.get(face, {}))


def build_context(
    today: str,
    action_rows: Sequence[Dict[str, Any]] = (),
    *,
    negative_streak_days: int = 0,
    negative_count_7d: int = 0,
    mention_rate_all_7d: Optional[float] = None,
    mention_rate_delta_7d: Optional[float] = None,
    zero_cells: int = 0,
    zero_cells_label: str = "",
    self_share: Optional[float] = None,
    self_share_rank: Optional[int] = None,
    self_rank_median: Optional[float] = None,
    top_competitor: str = "—",
    share_gap_to_top: Optional[float] = None,
    absent_domains: int = 0,
    top_absent_domain: str = "—",
    top_absent_count: int = 0,
    self_domain_count: int = 0,
    ai_sessions_wk: float = 0.0,
    branded_clicks_wk: float = 0.0,
    kgi_noise: bool = True,
    noise_floor: float = 10.0,
) -> Dict[str, Any]:
    """テンプレートに渡す実値をまとめる。ここに無い値は文面に出せない。"""
    reference = _date(today) or dt.date.today()
    implemented = implemented_actions(action_rows)
    latest = implemented[-1] if implemented else None

    # 次の施策 = まだ実施していない未完了の施策のうち優先度が高いもの
    pending = [
        r for r in action_rows
        if str(r.get("状態", "")).strip() in (STATUS_ON_HOLD, STATUS_PROPOSED,
                                              STATUS_AWAITING, STATUS_APPROVED)
    ]
    pending.sort(key=lambda r: (str(r.get("優先度", "")) != "高",
                                str(r.get("action_id", ""))))
    next_action = pending[0] if pending else None

    deadlines = sorted(
        d for d in (_date(r.get("判断期限")) for r in action_rows) if d is not None
    )
    upcoming = [d for d in deadlines if d >= reference]
    next_deadline = upcoming[0] if upcoming else (deadlines[-1] if deadlines else None)

    def count_status(*statuses: str) -> int:
        return sum(1 for r in action_rows
                   if str(r.get("状態", "")).strip() in statuses)

    overdue = [
        r for r in action_rows
        if str(r.get("状態", "")).strip() in OPEN_STATUSES
        and (_date(r.get("判断期限")) is not None)
        and _date(r.get("判断期限")) < reference
    ]
    proposed = [r for r in action_rows
                if str(r.get("状態", "")).strip() in (STATUS_PROPOSED, STATUS_AWAITING)]

    def names(rows: Sequence[Dict[str, Any]], limit: int = 3) -> str:
        labels = [str(r.get("action_id", "")).strip() for r in rows[:limit]]
        suffix = f" ほか{len(rows) - limit}件" if len(rows) > limit else ""
        return (", ".join(labels) + suffix) if labels else "—"

    return _StrictContext({
        "today": reference.isoformat(),
        # ネガティブ
        "negative_streak_days": int(negative_streak_days),
        "negative_count_7d": int(negative_count_7d),
        # 言及率
        "mention_rate_all_7d": _pct(mention_rate_all_7d),
        "mention_rate_delta_7d": mention_rate_delta_7d,
        "mention_rate_delta_7d_text": _signed_pct(mention_rate_delta_7d),
        # 施策
        "last_action_name": latest["name"] if latest else "—",
        "last_action_done_date": latest["date"].isoformat() if latest else "—",
        "days_since_last_action": (reference - latest["date"]).days if latest else None,
        "next_action_name": str(next_action.get("内容", "")).strip() if next_action else "—",
        "next_deadline": next_deadline.isoformat() if next_deadline else "未設定",
        "overdue_actions": len(overdue),
        "overdue_action_names": names(overdue),
        "proposed_actions": len(proposed),
        "proposed_action_names": names(proposed),
        "running_actions": count_status(STATUS_MEASURING),
        "done_actions": count_status(STATUS_DONE),
        # R4
        "zero_cells": int(zero_cells),
        "zero_cells_label": zero_cells_label or "—",
        # R5
        "self_share": _pct(self_share),
        "self_share_rank": self_share_rank,
        "self_rank_median": "—" if self_rank_median is None else f"{self_rank_median:g}",
        "top_competitor": top_competitor or "—",
        "share_gap_to_top": _pct(share_gap_to_top),
        # R6
        "absent_domains": int(absent_domains),
        "top_absent_domain": top_absent_domain or "—",
        "top_absent_count": int(top_absent_count),
        "self_domain_count": int(self_domain_count),
        # R7
        "ai_sessions_wk": f"{ai_sessions_wk:.0f}",
        "branded_clicks_wk": f"{branded_clicks_wk:.0f}",
        "kgi_noise": bool(kgi_noise),
        "noise_floor": f"{noise_floor:.0f}",
    })
