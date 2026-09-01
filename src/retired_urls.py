"""retired_urls.py — 取り下げたURLがまだ引用されているかを数える(A-011).

ページを消しても、モデルのインデックスやグラウンディングは古い参照を
しばらく持ち続ける。**その「しばらく」が何日なのかを実測する。**

これが分かっていないと、次に旧事業の掲載を直したときに
「直したのに所見が変わらない」の原因を、参照面のラグなのか直しが足りないのかに
切り分けられない。区別できないと待つべきか動くべきかが決まらない。

数え方:
  日次観測(E-1)の引用URLと config/retired_urls.yaml を突き合わせ、
  一致した回数をその日の件数として lk_events に「削除済みURLの引用」で記録する。
  引用が0になった日が参照面の入れ替わった日で、retired_on からの日数がラグ。

gemini の引用は grounding のリダイレクトで記録される。実測したところ
**E-1 の引用の約6割がリダイレクト**で、解決しないと中身が一切見えない。
解決せずに数えると「0回」が「引用が止まった」なのか「見えていないだけ」なのか
区別できず、ラグの実測という目的を果たせない。そのため日次で解決する
(E-1 の gemini 分だけなので1日10件程度)。

解決できなかった件数は ``unresolved`` として持ち回り、0件の日でも
「何件見えていないか」を lk_events に残す。見えない分を黙って0に含めない。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence

from settings import RETIRED_URLS_FILE, load_yaml

EVENT_TYPE = "retired_url_cited"
EVENT_NAME = "削除済みURLの引用"
# このイベントは P-8(旧事業URLの引用)の続き。消したあとの尾を見ている。
PLAYBOOK_REF = "P-8"

ENTITY_PROMPT_ID = "E-1"

# grounding のリダイレクト。実URLに解決しないと中身が分からない。
REDIRECT_MARKER = "vertexaisearch.cloud.google.com"
RESOLVE_TIMEOUT_SECONDS = 20

_CACHE: Optional[List[Dict[str, Any]]] = None
# 同じリダイレクトURLは日をまたいでも同じ先に解決する。実行内で使い回す。
_RESOLVED: Dict[str, Optional[str]] = {}


def load_retired(force: bool = False) -> List[Dict[str, Any]]:
    """取り下げたURLの定義。ファイルが無ければ空(機能を止めない)。"""
    global _CACHE
    if _CACHE is None or force:
        try:
            data = load_yaml(RETIRED_URLS_FILE) or {}
        except FileNotFoundError:
            data = {}
        _CACHE = [r for r in (data.get("retired") or []) if r.get("url")]
    return _CACHE


def _urls_of(row: Dict[str, Any]) -> List[str]:
    """観測1行の**すべての**引用URL。

    **`cited_crosscom_urls` は使えない。** あの列は自社ドメインだけを残す
    (extract.py が cross-com.jp / crosscom で絞る)ので、prtimes.jp のような
    外部ドメインは構造上1件も入らない。そこを見ると常に0件になり、
    「参照面が即日入れ替わった」と誤読する。

    使うのは生データ(data/raw)の ``cited_urls`` と、抽出直後のメモリ上に
    だけある ``all_cited_urls``。シートのタブ定義(§7)は変更禁止なので、
    citation_gap と同じく生データから読む。
    """
    for key in ("cited_urls", "all_cited_urls"):
        value = row.get(key)
        if value:
            if isinstance(value, (list, tuple)):
                return [str(u).strip() for u in value if str(u).strip()]
            return [u.strip() for u in str(value).split(",") if u.strip()]
    return []


def resolve_redirect(url: str) -> Optional[str]:
    """grounding のリダイレクトを実URLに解決する。失敗したら None。"""
    if url in _RESOLVED:
        return _RESOLVED[url]
    try:
        import requests

        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (compatible; llmo-audit/1.0)"
        for method in (session.head, session.get):
            try:
                resolved = method(url, allow_redirects=True,
                                  timeout=RESOLVE_TIMEOUT_SECONDS).url
                if resolved and REDIRECT_MARKER not in resolved:
                    _RESOLVED[url] = resolved
                    return resolved
            except Exception:  # noqa: BLE001 - 次の方法を試す
                continue
    except Exception:  # noqa: BLE001 - requests が無い等。数えられないだけ
        pass
    _RESOLVED[url] = None
    return None


def count_citations(rows: Sequence[Dict[str, Any]], date: str,
                    retired: Optional[Sequence[Dict[str, Any]]] = None,
                    resolve: bool = False) -> List[Dict[str, Any]]:
    """``date`` の E-1 観測で、取り下げたURLが何回引用されたかを数える。

    返すのはURLごとの ``{"url", "label", "status", "retired_on", "action_id",
    "count", "models", "days_since_retired"}``。引用が0でも行を返す
    (0になったことが結果なので、行が消えると入れ替わりを観測できない)。
    """
    retired = list(retired if retired is not None else load_retired())
    today = [r for r in rows
             if str(r.get("date") or "").strip() == date
             and str(r.get("prompt_id") or "").strip() == ENTITY_PROMPT_ID]

    # 引用URLを行ごとに展開し、必要ならリダイレクトを解決しておく。
    expanded: List[Dict[str, Any]] = []
    unresolved = 0
    for row in today:
        urls = []
        for u in _urls_of(row):
            if REDIRECT_MARKER in u:
                if not resolve:
                    unresolved += 1
                    continue
                real = resolve_redirect(u)
                if real is None:
                    unresolved += 1
                    continue
                urls.append(real)
            else:
                urls.append(u)
        expanded.append({"model": str(row.get("model") or "").strip(), "urls": urls})

    out: List[Dict[str, Any]] = []
    for entry in retired:
        target = str(entry["url"]).strip()
        count, models = 0, set()
        for row in expanded:
            hits = sum(1 for u in row["urls"] if target in u)
            if hits:
                count += hits
                models.add(row["model"])
        out.append({
            "url": target,
            "label": str(entry.get("label") or "").strip(),
            "status": str(entry.get("status") or "").strip(),
            "retired_on": str(entry.get("retired_on") or "").strip(),
            "action_id": str(entry.get("action_id") or "").strip(),
            "count": count,
            "models": sorted(m for m in models if m),
            "days_since_retired": _days_since(entry.get("retired_on"), date),
            # 解決できなかったリダイレクトの数。0件の日にこれが多いと、
            # 「引用が止まった」とは言い切れない。
            "unresolved": unresolved,
        })
    return out


def _days_since(retired_on: Any, date: str) -> Optional[int]:
    try:
        return (dt.date.fromisoformat(date)
                - dt.date.fromisoformat(str(retired_on))).days
    except (TypeError, ValueError):
        return None


def event_rows(date: str, rows: Sequence[Dict[str, Any]],
               retired: Optional[Sequence[Dict[str, Any]]] = None,
               resolve: bool = False) -> List[Dict[str, Any]]:
    """lk_events に足す行(Phase 6 のスキーマそのまま)。

    引用が0の日も1行出す。**0が続いた日数がラグの答え**なので、
    行が消えると「入れ替わった」のか「集計が動いていない」のかが区別できない。
    """
    out = []
    for c in count_citations(rows, date, retired, resolve=resolve):
        elapsed = "" if c["days_since_retired"] is None \
            else f"取り下げから{c['days_since_retired']}日"
        state = "引用が続いている" if c["count"] else "引用なし"
        detail = f"{c['label']}: {c['count']}回"
        if c["models"]:
            detail += f"({'/'.join(c['models'])})"
        detail += f" — {state}"
        if elapsed:
            detail += f"・{elapsed}"
        if c["unresolved"]:
            # 0件を「止まった」と読ませないための但し書き。
            detail += f"・未解決のリダイレクト{c['unresolved']}件"
        if c["status"] == "replaced":
            # 中身を差し替えただけのURLは、引用されても旧事業は入らない。
            # 同じ数え方をすると「古い参照が残っている」と誤読される。
            detail += "(URLは存置・中身は現行事業に差し替え済み)"
        out.append({
            "date": date,
            "event_type": EVENT_TYPE,
            "event_name": EVENT_NAME,
            "place": f"{ENTITY_PROMPT_ID} × {c['action_id'] or '—'}",
            "detail": detail,
            "playbook_ref": PLAYBOOK_REF,
        })
    return out


def summary_line(date: str, rows: Sequence[Dict[str, Any]],
                 retired: Optional[Sequence[Dict[str, Any]]] = None,
                 resolve: bool = False) -> str:
    """ジョブサマリ用の1行。"""
    counts = count_citations(rows, date, retired, resolve=resolve)
    still = [c for c in counts if c["count"] and c["status"] == "deleted"]
    total = sum(c["count"] for c in counts)
    if not counts:
        return "取り下げたURLの定義なし"
    unresolved = counts[0]["unresolved"] if counts else 0
    tail = (f" ※存置URLの引用は{total}回" if total else "")
    if unresolved:
        tail += f" ※未解決のリダイレクト{unresolved}件"
    if not still:
        return f"削除済みURLの引用: 0回(定義{len(counts)}件・{date}){tail}"
    return ("削除済みURLの引用: "
            + ", ".join(f"{c['label']} {c['count']}回" for c in still))
