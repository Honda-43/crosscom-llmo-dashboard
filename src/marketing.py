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
一覧を挙げるモデルは EXTRACTOR_MODEL に固定し、毎行 extractor_model に記録する。

Gemini の実行順は層ブロック順(GEMINI_LAYER_ORDER)で毎月固定。Claude は毎月54本すべて(id 順)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import unicodedata

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import experiment
from settings import (DATA_RAW_EXPERIMENT_DIR, DATA_RAW_MARKETING_DIR, marketing_prompt_active,
                      MARKETING_QUOTA_SKIPPED, MARKETING_WINDOW_LAST_DAY)

MODELS = ("gemini", "claude")
PERDAY_MARKER = "PerDay"

# is_first / mention_rank の会社名一覧を挙げさせるモデル(2026-10-01 固定)。
# 環境変数では変えない(日次の抽出の EXTRACT_MODEL とは別)。変えると rank の月次比較が切れるので、
# 変えるときは README と日誌に日付と理由を書いてから、この値を変える。毎行 extractor_model に記録する
EXTRACTOR_MODEL = "claude-haiku-4-5-20251001"

# Gemini の実行順(2026-10-01 改訂):層ブロック順。1つの層を最後まで終えてから次の層へ。
# 各層の中は id 順。**毎月まったく同じ順**にする(月によって変えない)。
# Gemini は月に約28本しか回らないので、通常 MOFU_L0・BOFU_single が完結し BOFU_compare が一部、
# MOFU_L1・MOFU_L2 は観測されない月が多い(L1・L2 は Claude で毎月54本すべて観測する)
GEMINI_LAYER_ORDER = ("MOFU_L0", "BOFU_single", "BOFU_compare", "MOFU_L1", "MOFU_L2")

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
        model=EXTRACTOR_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": _LIST_PROMPT.format(question=question, answer=answer)},
                  {"role": "assistant", "content": "["}],
    )
    body = "[" + "".join(getattr(b, "text", "") for b in resp.content
                         if getattr(b, "type", None) == "text")
    names = json.loads(body[:body.rfind("]") + 1])
    if not isinstance(names, list):
        raise ValueError("company list is not a JSON array")
    return [str(n) for n in names if str(n).strip()]


def run_date_jst(record: Dict[str, Any]) -> str:
    """実際に API を呼んだ日時(JST・秒まで)。投げていない観測(attempts=0)は空。

    collect_llm の timestamp(UTC・応答を受けた時刻)を JST にする。date 列は観測の日付
    (その日の実行)で、Gemini と Claude では実行日がずれるため別の列にする。
    """
    stamp = str(record.get("timestamp") or "")
    if not stamp or not record.get("attempts"):
        return ""
    when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")


def evaluate(record: Dict[str, Any], prompt: Dict[str, Any],
             resolver: Optional[experiment.Resolver] = None,
             lister: Optional[CompanyLister] = None) -> Dict[str, Any]:
    """collect_llm のレコードに足す llm_marketing の列。欠測は判定列を空にする。"""
    fields: Dict[str, Any] = {
        "layer": prompt.get("layer", ""), "prompt": prompt["prompt"],
        "answer_text": record.get("answer") or "",
        "run_date": run_date_jst(record),
        "extractor_model": EXTRACTOR_MODEL,
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
    prompts = [p for p in prompts if marketing_prompt_active(p, month)]      # 初回の月より前のプロンプトは入れない
    ordered = gemini_order(prompts) if model == "gemini" else sorted(prompts, key=lambda p: p["id"])
    return [p for p in ordered if p["id"] not in done]


def gemini_order(prompts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Gemini の実行順:GEMINI_LAYER_ORDER の層ブロック順、各層の中は id 順。毎月同じ。"""
    rank = {layer: i for i, layer in enumerate(GEMINI_LAYER_ORDER)}
    return sorted(prompts, key=lambda p: (rank.get(p.get("layer", ""), len(rank)), p["id"]))


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


def layer_sizes(prompts: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """層ごとの全本数(prompts_marketing.csv)。"""
    out: Dict[str, int] = {}
    for p in prompts:
        out[p.get("layer", "")] = out.get(p.get("layer", ""), 0) + 1
    return out


def layer_rates(rows: Iterable[Dict[str, Any]], sizes=None) -> List[Dict[str, Any]]:
    """[{month, layer, model, n, total, partial, mentioned, cited_domain}]。

    n は観測できた本数(率の分母)、total は層の全本数。n < total の層は partial(一部観測)。
    ``sizes`` は {層: 本数} か、月を受けて {層: 本数} を返す関数(月によって含むプロンプトが違うため。
    2026-11 から MOFU_L1 は18本→21本)。
    """
    cells: Dict[tuple, Dict[str, Any]] = {}
    for r in latest_observations(rows):
        key = (month_of(r["date"]), r.get("layer", ""), r.get("model", ""))
        c = cells.setdefault(key, {"month": key[0], "layer": key[1], "model": key[2],
                                   "n": 0, "mentioned": 0, "cited_domain": 0})
        c["n"] += 1
        c["mentioned"] += str(r.get("mentioned", "")).strip() == "1"
        c["cited_domain"] += str(r.get("cited_domain", "")).strip() == "1"
    for c in cells.values():
        month_sizes = sizes(c["month"]) if callable(sizes) else (sizes or {})
        c["total"] = month_sizes.get(c["layer"], c["n"])
        c["partial"] = c["n"] < c["total"]
    order = {k: i for i, k in enumerate(LAYER_ORDER)}
    return sorted(cells.values(), key=lambda c: (c["month"], order.get(c["layer"], 99), c["model"]))


def compare_months(rows: Iterable[Dict[str, Any]], month: str,
                   previous: str) -> List[Dict[str, Any]]:
    """前月との差。**両方の月で観測できたプロンプトだけ**で、層 × モデル の率を出す。

    quota_skipped・欠測の行は観測に数えない。片方の月にしか無いプロンプトを混ぜると、
    観測できた本数の違いが率の差に見えてしまうため(Gemini は月によって回る本数が違う)。
    [{layer, model, n, mentioned_now, mentioned_prev, cited_now, cited_prev}]
    """
    obs = latest_observations(rows)
    by = {(month_of(r["date"]), r.get("prompt_id"), r.get("model")): r for r in obs}
    cells: Dict[tuple, Dict[str, Any]] = {}
    for (m, pid, model), now in by.items():
        if m != month:
            continue
        prev = by.get((previous, pid, model))
        if prev is None:
            continue
        c = cells.setdefault((now.get("layer", ""), model), {
            "layer": now.get("layer", ""), "model": model, "n": 0,
            "mentioned_now": 0, "mentioned_prev": 0, "cited_now": 0, "cited_prev": 0})
        c["n"] += 1
        flag = lambda r, col: str(r.get(col, "")).strip() == "1"          # noqa: E731
        c["mentioned_now"] += flag(now, "mentioned")
        c["mentioned_prev"] += flag(prev, "mentioned")
        c["cited_now"] += flag(now, "cited_domain")
        c["cited_prev"] += flag(prev, "cited_domain")
    order = {k: i for i, k in enumerate(LAYER_ORDER)}
    return sorted(cells.values(), key=lambda c: (order.get(c["layer"], 99), c["model"]))


def previous_month(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
