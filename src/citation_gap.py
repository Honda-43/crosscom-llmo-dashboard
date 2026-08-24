"""citation_gap.py — 引用元ドメインの3分類(Phase 5 §3-2).

回答が引用したドメインを、自社が言及されている回答とされていない回答の
どちらに現れるかで3つに分ける。

  自社     : cross-com.jp
  共通     : 自社が言及された回答にも現れる外部ドメイン
  自社不在 : 自社が言及されていない回答でのみ現れる外部ドメイン

「自社不在」は、AIがその質問に答えるとき見ているのに自社が載っていない場所である。
掲載依頼先の候補はここから出す。

データ源は data/raw の ``cited_urls``。llm_observations は承認済みスキーマで
``all_cited_urls`` を持たないため(§7のタブ定義は変更禁止)、生データから再構成する。
ローカルのファイル読みなのでSheets APIは消費しない。

Geminiの引用URLは grounding リダイレクトで元ドメインが解決できないため、
集計から除外し ``unresolved`` として件数だけ報告する。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from settings import DATA_RAW_DIR

SELF_DOMAIN_FRAGMENTS = ("cross-com.jp", "crosscom")
UNRESOLVABLE_HOSTS = ("vertexaisearch.cloud.google.com",)

CATEGORY_SELF = "自社"
CATEGORY_SHARED = "共通"
CATEGORY_ABSENT = "自社不在"


def domain_of(url: str) -> Optional[str]:
    host = (urlparse(url).netloc or "").lower().strip()
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def is_self_domain(domain: str) -> bool:
    return any(fragment in domain for fragment in SELF_DOMAIN_FRAGMENTS)


def is_unresolvable(domain: str) -> bool:
    return any(host in domain for host in UNRESOLVABLE_HOSTS)


def load_raw_observations(since: Optional[str] = None,
                          until: Optional[str] = None) -> List[Dict[str, Any]]:
    """data/raw から観測を読む。answer本文は使わないので捨てる。"""
    out: List[Dict[str, Any]] = []
    if not DATA_RAW_DIR.exists():
        return out
    for path in sorted(DATA_RAW_DIR.glob("*/*.json")):
        date = path.parent.name
        if since and date < since:
            continue
        if until and date > until:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("error") or not record.get("answer"):
            continue
        out.append({
            "date": date,
            "prompt_id": str(record.get("prompt_id") or ""),
            "model": str(record.get("model") or ""),
            "cited_urls": [u for u in (record.get("cited_urls") or []) if u],
            "answer": record.get("answer") or "",
        })
    return out


def mention_map(observations: Sequence[Dict[str, str]]) -> Dict[Tuple[str, str, str], bool]:
    """llm_observations から (date, prompt_id, model) -> 自社言及の有無 を作る。"""
    from analyze_diff import parse_bool

    out: Dict[Tuple[str, str, str], bool] = {}
    for row in observations:
        mention = parse_bool(row.get("mention"))
        if mention is None:
            continue
        key = (str(row.get("date") or "").strip(),
               str(row.get("prompt_id") or "").strip(),
               str(row.get("model") or "").strip())
        out[key] = bool(mention)
    return out


def classify(
    raw_records: Sequence[Dict[str, Any]],
    mentions: Dict[Tuple[str, str, str], bool],
) -> Dict[str, Any]:
    """ドメインごとに3分類と引用回数・登場プロンプトを集計する。"""
    cited_when_mentioned: Dict[str, int] = defaultdict(int)
    cited_when_absent: Dict[str, int] = defaultdict(int)
    prompts_by_domain: Dict[str, set] = defaultdict(set)
    unresolved = 0
    evaluated = 0

    for record in raw_records:
        key = (record["date"], record["prompt_id"], record["model"])
        mentioned = mentions.get(key)
        if mentioned is None:
            # 抽出結果が無い観測は「自社が出たか」が判定できないので数えない
            continue
        evaluated += 1
        seen: set = set()
        for url in record["cited_urls"]:
            domain = domain_of(url)
            if not domain:
                continue
            if is_unresolvable(domain):
                unresolved += 1
                continue
            if domain in seen:
                continue  # 同一回答内の重複は1回と数える
            seen.add(domain)
            prompts_by_domain[domain].add(record["prompt_id"])
            if mentioned:
                cited_when_mentioned[domain] += 1
            else:
                cited_when_absent[domain] += 1

    rows: List[Dict[str, Any]] = []
    for domain in sorted(set(cited_when_mentioned) | set(cited_when_absent)):
        with_self = cited_when_mentioned[domain]
        without_self = cited_when_absent[domain]
        if is_self_domain(domain):
            category = CATEGORY_SELF
        elif with_self > 0:
            category = CATEGORY_SHARED
        else:
            category = CATEGORY_ABSENT
        rows.append({
            "domain": domain,
            "category": category,
            "cited_count": with_self + without_self,
            "cited_with_self": with_self,
            "cited_without_self": without_self,
            "prompts": ", ".join(sorted(prompts_by_domain[domain])),
        })

    rows.sort(key=lambda r: (-r["cited_count"], r["domain"]))
    return {
        "rows": rows,
        "unresolved_citations": unresolved,
        "evaluated_observations": evaluated,
    }


def build_rows(date: str, raw_records: Sequence[Dict[str, Any]],
               observations: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    """citation_gap タブに書く行(date × domain)。"""
    result = classify(raw_records, mention_map(observations))
    return [
        {"date": date, "domain": r["domain"], "category": r["category"],
         "cited_count": r["cited_count"], "prompts": r["prompts"]}
        for r in result["rows"]
    ]


def analyze(date: str, observations: Optional[Sequence[Dict[str, str]]] = None,
            lookback_days: int = 28) -> Dict[str, Any]:
    """当日を含む直近 ``lookback_days`` 日分を集計する。"""
    if observations is None:
        import sheets_writer

        observations = sheets_writer.read_llm_observations()

    since = (dt.date.fromisoformat(date) - dt.timedelta(days=lookback_days - 1)).isoformat()
    raw_records = load_raw_observations(since=since, until=date)
    result = classify(raw_records, mention_map(observations))
    result["date"] = date
    result["rows_for_sheet"] = [
        {"date": date, "domain": r["domain"], "category": r["category"],
         "cited_count": r["cited_count"], "prompts": r["prompts"]}
        for r in result["rows"]
    ]
    absent = [r for r in result["rows"] if r["category"] == CATEGORY_ABSENT]
    print(f"[ok] citation_gap {date}: {len(result['rows'])} ドメイン "
          f"(自社不在 {len(absent)} 件 / 解決不能な引用 {result['unresolved_citations']} 件)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="引用元ドメインの3分類")
    ap.add_argument("--date", required=True, help="集計基準日 YYYY-MM-DD")
    ap.add_argument("--lookback", type=int, default=28)
    args = ap.parse_args()

    result = analyze(args.date, lookback_days=args.lookback)
    for row in result["rows"][:30]:
        print(f"  {row['category']:6s} {row['cited_count']:4d}  {row['domain']}")


if __name__ == "__main__":
    main()
