"""marketing.py — 第3観測層 prompt_marketing の判定と月内の進み具合(2026-10-01).

戦略管制塔が確定した54本(config/prompts_marketing.csv)を、Gemini と Claude で月1回
観測する。実験(llm_experiment)とは別の層で、タブも raw の置き場所も分ける。

判定列
- mentioned     … 社名の6表記(experiment.MENTION_TERMS_V2)のどれかを含むか。文字列照合のみ
- mention_rank  … 回答に出てくる会社の中で、社名が何番目に出たか。出なければ空
- is_first      … mention_rank が 1 か(1/0)
- cited_domain  … 引用元に cross-com.jp(サブドメイン含む)の URL があるか
- cited_domains … 引用元のドメイン一覧

mention_rank の数え方:会社名の一覧だけを Haiku に挙げさせ(本文に書かれた表記のまま)、
**並び順は本文での初出の位置で決める**(文字列照合)。LLM に順位そのものは決めさせない。
製品・プラットフォームの提供元(Salesforce など)は会社の一覧に入れない。
一覧に出たが本文で位置が取れない名前は数えない。社名が出ない回答では Haiku を呼ばない。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import experiment
from settings import (DATA_RAW_EXPERIMENT_DIR, DATA_RAW_MARKETING_DIR, EXTRACT_MODEL,
                      MARKETING_QUOTA_SKIPPED, MARKETING_WINDOW_LAST_DAY)

MODELS = ("gemini", "claude")
PERDAY_MARKER = "PerDay"

CompanyLister = Callable[[str, str], List[str]]


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------
def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def mention_rank(answer: str, companies: Iterable[str]) -> Optional[int]:
    """社名が回答の会社の中で何番目に出たか(1始まり)。社名が無ければ None。

    自社の位置 = 6表記のどれかの初出。他社の位置 = その名前の初出(NFKC・大文字小文字無視)。
    自社より前に初出する他社の数 + 1。自社の表記を含む名前は他社に数えない。
    """
    hits = experiment.mention_hits_v2(answer)
    if not hits:
        return None
    ours = hits[0][0]
    folded = _fold(answer)
    earlier = set()
    for name in companies:
        key = _fold(name).strip()
        if not key or experiment.is_mentioned_v2(name):
            continue
        pos = folded.find(key)
        if 0 <= pos < ours:
            earlier.add(key)
    return len(earlier) + 1


_LIST_PROMPT = """次のAI回答に、サービスを提供する会社(導入支援・コンサルティング・開発会社など)として登場する企業名を、
本文に書かれている表記のまま、重複なく全て挙げてください。
- 製品・プラットフォームの提供元(Salesforce、Google、Microsoft など、支援会社として挙げられていないもの)は含めない
- 企業名でない語(「大手SIer」「コンサルティングファーム」など)は含めない
- 合同会社クロスコム(クロスコム・Cross-Com 等の表記)も登場していれば含める
JSON の配列だけを出力してください。例: ["株式会社A", "B社"]

# 質問
{question}

# AI回答
{answer}"""


def list_companies_with_haiku(question: str, answer: str) -> List[str]:
    """回答に出てくる会社名の一覧(Haiku)。並び順は使わない(mention_rank が本文の位置で決める)。"""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=EXTRACT_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": _LIST_PROMPT.format(question=question, answer=answer)},
                  {"role": "assistant", "content": "["}],
    )
    body = "[" + "".join(getattr(b, "text", "") for b in resp.content
                         if getattr(b, "type", None) == "text")
    names = json.loads(body[:body.rfind("]") + 1])
    if not isinstance(names, list):
        raise ValueError("company list is not a JSON array")
    return [str(n) for n in names if str(n).strip()]


def evaluate(record: Dict[str, Any], prompt: Dict[str, Any],
             resolver: Optional[experiment.Resolver] = None,
             lister: Optional[CompanyLister] = None) -> Dict[str, Any]:
    """collect_llm のレコードに足す llm_marketing の列。欠測は判定列を空にする。"""
    fields: Dict[str, Any] = {
        "layer": prompt.get("layer", ""), "prompt": prompt["prompt"],
        "answer_text": record.get("answer") or "",
    }
    if record.get("error"):
        fields.update(mentioned="", is_first="", mention_rank="", cited_domain="",
                      cited_domains=[], companies=[])
        return fields
    urls, unresolved = experiment.resolve_urls(record.get("cited_urls") or [], resolver)
    domains: List[str] = []
    for url in urls:
        d = experiment.domain_of(url)
        if d and d not in domains:
            domains.append(d)
    answer = fields["answer_text"]
    mentioned = experiment.is_mentioned_v2(answer)
    companies: List[str] = []
    rank: Any = ""                       # 社名が出ない回答は空
    is_first: Any = 0
    if mentioned:
        try:
            companies = (lister or list_companies_with_haiku)(prompt["prompt"], answer)
            rank = mention_rank(answer, companies)
            is_first = int(rank == 1)
        except Exception as exc:  # noqa: BLE001 - 順位が取れなくても観測は残す
            fields["rank_error"] = str(exc)
            rank = is_first = ""
    fields.update(
        mentioned=mentioned, mention_rank=rank, is_first=is_first,
        cited_domain=int(any(experiment.is_self_domain(d) for d in domains)),
        cited_domains=domains, resolved_urls=urls, unresolved_redirects=unresolved,
        companies=companies,
    )
    return fields


# --------------------------------------------------------------------------
# 月内の進み具合(data/raw/marketing/<日付>/<id>_<model>.json)
# --------------------------------------------------------------------------
def month_of(date: str) -> str:
    return str(date)[:7]


def month_records(month: str, root: Path = DATA_RAW_MARKETING_DIR) -> List[Dict[str, Any]]:
    """その月に記録した marketing の raw(日付順)。"""
    out = []
    for folder in sorted(root.glob(f"{month}-*")):
        for f in sorted(folder.glob("*.json")):
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def done_ids(month: str, model: str, root: Path = DATA_RAW_MARKETING_DIR) -> Set[str]:
    """その月に、そのモデルで**終わった**プロンプト(観測できた・quota_skipped と記録した)。

    503 などの欠測は終わっていない扱い(期間内の次の日にもう一度投げる)。
    """
    out = set()
    for rec in month_records(month, root):
        if rec.get("model") != model:
            continue
        err = str(rec.get("error") or "")
        if not err or err.startswith(MARKETING_QUOTA_SKIPPED):
            out.add(rec["prompt_id"])
    return out


def pending(prompts: List[Dict[str, Any]], month: str, model: str,
            root: Path = DATA_RAW_MARKETING_DIR) -> List[Dict[str, Any]]:
    """その月・そのモデルでまだ終わっていないプロンプト(投げる順)。"""
    done = done_ids(month, model, root)
    return [p for p in interleave_layers(prompts) if p["id"] not in done]


def interleave_layers(prompts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """層を1本ずつ順に回す並び(MOFU_L0 の1本目 → MOFU_L1 の1本目 → …)。

    Gemini は枠が足りず、月に54本すべては回りきらない(第1〜2週で約28本)。CSV の順に
    投げると後ろの層(BOFU)が毎月まるごと quota_skipped になるので、層ごとに少しずつ進める。
    """
    layers: Dict[str, List[Dict[str, Any]]] = {}
    for p in prompts:
        layers.setdefault(p.get("layer", ""), []).append(p)
    queues = list(layers.values())
    longest = max((len(q) for q in queues), default=0)
    return [q[i] for i in range(longest) for q in queues if i < len(q)]


def experiment_perday_misses(month: str,
                             root: Path = DATA_RAW_EXPERIMENT_DIR) -> List[str]:
    """その月の実験の観測で、1日あたりの枠切れ(429 PerDay)で欠測した観測。"""
    out = []
    for folder in sorted(root.glob(f"{month}-*")):
        for f in sorted(folder.glob("*_gemini.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            err = str(rec.get("error") or "")
            if "429" in err[:40] and PERDAY_MARKER in err:
                out.append(f"{folder.name} {rec.get('prompt_id')}")
    return out


def is_last_window_day(date: str) -> bool:
    return dt.date.fromisoformat(str(date)[:10]).day >= MARKETING_WINDOW_LAST_DAY


def skipped_record(date: str, prompt: Dict[str, Any], model: str, model_name: str,
                   detail: str = "") -> Dict[str, Any]:
    """投げずに終えた観測(error=quota_skipped)。翌月には持ち越さない。"""
    record = {
        "date": date, "prompt_id": prompt["id"], "model": model, "model_name": model_name,
        "question": prompt["prompt"], "answer": None, "cited_urls": [],
        "error": MARKETING_QUOTA_SKIPPED + (f": {detail}" if detail else ""),
        "miss_reason": "skipped", "attempts": 0,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    record.update(evaluate(record, prompt))
    return record


# --------------------------------------------------------------------------
# ダッシュボード:層 × モデル の月次の率
# --------------------------------------------------------------------------
LAYER_ORDER = ("MOFU_L0", "MOFU_L1", "MOFU_L2", "BOFU_single", "BOFU_compare")


def latest_observations(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """観測できた行だけを、(月, プロンプト, モデル) ごとに1行にする(同じ月に2回あれば後の日)。"""
    kept: Dict[tuple, Dict[str, Any]] = {}
    for r in sorted(rows, key=lambda x: str(x.get("date", ""))):
        if str(r.get("error") or "").strip() or not str(r.get("date") or "").strip():
            continue
        kept[(month_of(r["date"]), r.get("prompt_id"), r.get("model"))] = r
    return list(kept.values())


def layer_rates(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{month, layer, model, n, mentioned, cited_domain}]。率の分母 n は観測できた本数。"""
    cells: Dict[tuple, Dict[str, Any]] = {}
    for r in latest_observations(rows):
        key = (month_of(r["date"]), r.get("layer", ""), r.get("model", ""))
        c = cells.setdefault(key, {"month": key[0], "layer": key[1], "model": key[2],
                                   "n": 0, "mentioned": 0, "cited_domain": 0})
        c["n"] += 1
        c["mentioned"] += str(r.get("mentioned", "")).strip() == "1"
        c["cited_domain"] += str(r.get("cited_domain", "")).strip() == "1"
    order = {k: i for i, k in enumerate(LAYER_ORDER)}
    return sorted(cells.values(), key=lambda c: (c["month"], order.get(c["layer"], 99), c["model"]))
