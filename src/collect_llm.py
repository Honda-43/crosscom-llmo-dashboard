"""collect_llm.py — fixed-point observation across LLMs (§3).

Sends each approved prompt (§2) to every enabled model as a *bare user
question* (no system instruction, default temperature) with the model's
native web-search tool enabled, then stores the full answer plus citations to
``data/raw/YYYY-MM-DD/{prompt_id}_{model}.json``.

Design notes:
- Model enable/disable + model names live in settings.py.
- Retry: exponential backoff。provider が retryDelay を返したらそちらを優先する。
  一巡したあと、失敗した観測だけを1回だけ掃き直す(_sweep)。それでも取れなければ
  その日の欠測として記録し、他のモデル・プロンプトは続行する。
- 日次のリクエスト枠(gemini 無料枠は1日20回)を守るため、リトライ回数は
  増やしすぎない。1日枠の 429 を踏んだモデルは、その実行中のリトライを止める
  (基本の1回は投げる。枠は数十秒で戻ることがあるため)。
- Perplexity stays disabled by default and a missing PERPLEXITY_API_KEY must
  never raise — activation is key + flag only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from settings import (
    BACKOFF_BASE_SECONDS,
    DATA_RAW_DIR,
    MAX_RETRIES,
    MODEL_CONFIG,
    RETRY_DELAY_CAP_SECONDS,
    SWEEP_COOLDOWN_SECONDS,
    enabled_models,
    load_prompts,
)

URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


# --------------------------------------------------------------------------
# Retry helper
# --------------------------------------------------------------------------
# 再試行しても意味がないエラー。鍵が無効・権限が無い・課金枠を使い切った、は
# 数十秒待っても変わらない。待つだけ無駄で、しかもリクエスト枠を食う。
_PERMANENT_MARKERS = (
    "insufficient_quota", "invalid_api_key", "PERMISSION_DENIED",
    "UNAUTHENTICATED", "API key not valid", "invalid_request_error",
)
_PERMANENT_CODES = ("400", "401", "403", "404")

# 「1日あたり」の枠を使い切ったことを示す quotaId。数秒〜数十秒のリトライで
# 回復する種類ではないので、そのモデルのリトライを実行中は止める。
_DAILY_QUOTA_MARKER = "PerDay"

# provider が返す再試行指示。gemini は RetryInfo.retryDelay、
# メッセージ本文にも "Please retry in 14.44845715s." の形で入る。
_RETRY_DELAY_RE = re.compile(r"retryDelay'?\s*:\s*'?([0-9.]+)s")
_RETRY_IN_RE = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)


def is_permanent(exc: Exception) -> bool:
    """待っても直らないエラーか。"""
    text = str(exc)
    if any(marker in text for marker in _PERMANENT_MARKERS):
        return True
    head = text[:40]
    return any(code in head for code in _PERMANENT_CODES)


def is_daily_quota(exc: Exception) -> bool:
    """1日あたりのリクエスト枠を使い切ったか。"""
    text = str(exc)
    return "429" in text[:40] and _DAILY_QUOTA_MARKER in text


def retry_delay(exc: Exception) -> Optional[float]:
    """provider が指定してきた再試行までの秒数。無ければ None。"""
    text = str(exc)
    for pattern in (_RETRY_DELAY_RE, _RETRY_IN_RE):
        found = pattern.search(text)
        if found:
            return min(float(found.group(1)), RETRY_DELAY_CAP_SECONDS)
    return None


def _wait_for(exc: Exception, attempt: int) -> float:
    """次の試行までの待ち時間。provider の指示があればそちらを優先する。"""
    backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    told = retry_delay(exc)
    return max(backoff, told) if told is not None else backoff


def _with_retry(fn, *, label: str, attempts: int = MAX_RETRIES,
                on_daily_quota=None):
    """Run ``fn`` with exponential backoff. Raises the last error after
    ``attempts`` failures so the caller can record the day as missing.

    3つの理由で早く諦める:
      - 待っても直らないエラー(鍵・権限・課金)は1回で止める
      - 1日枠の 429 は、リトライがその枠をさらに食う。1回で止める
      - provider が retryDelay を返したら、固定のバックオフより優先する
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we retry all provider errors
            last_exc = exc
            print(f"[warn] {label} attempt {attempt}/{attempts} failed: {exc}")
            if is_permanent(exc):
                print(f"[warn] {label}: 再試行しても変わらないエラーのため中止")
                break
            if is_daily_quota(exc):
                print(f"[warn] {label}: 1日あたりのリクエスト枠を超過。"
                      f"このモデルの再試行を実行中は止める")
                if on_daily_quota is not None:
                    on_daily_quota()
                break
            if attempt < attempts:
                wait = _wait_for(exc, attempt)
                print(f"[info] {label}: {wait:.0f}秒待って再試行します")
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def _merge_urls(answer_text: str, native_citations: List[str]) -> List[str]:
    """Union of native citation URLs and URLs found in the body text (§3),
    order-preserving and de-duplicated."""
    seen: Dict[str, None] = {}
    for u in native_citations:
        if u:
            seen.setdefault(u.strip(), None)
    for u in URL_RE.findall(answer_text or ""):
        seen.setdefault(u.strip().rstrip(".,;"), None)
    return list(seen.keys())


# --------------------------------------------------------------------------
# Per-model query functions -> (answer_text, native_citation_urls)
# --------------------------------------------------------------------------
def _query_chatgpt(prompt_text: str, model: str) -> Tuple[str, List[str]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.responses.create(
        model=model,
        input=prompt_text,
        tools=[{"type": "web_search"}],
    )
    answer = getattr(resp, "output_text", "") or ""
    citations: List[str] = []
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            for ann in getattr(content, "annotations", []) or []:
                url = getattr(ann, "url", None)
                if url:
                    citations.append(url)
    return answer, citations


def _query_gemini(prompt_text: str, model: str) -> Tuple[str, List[str]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    answer = getattr(resp, "text", "") or ""
    citations: List[str] = []
    for cand in getattr(resp, "candidates", []) or []:
        meta = getattr(cand, "grounding_metadata", None)
        for chunk in getattr(meta, "grounding_chunks", []) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None)
            if uri:
                citations.append(uri)
    return answer, citations


def _query_claude(prompt_text: str, model: str) -> Tuple[str, List[str]]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt_text}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    )
    answer_parts: List[str] = []
    citations: List[str] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            answer_parts.append(getattr(block, "text", "") or "")
            for cit in getattr(block, "citations", []) or []:
                url = getattr(cit, "url", None)
                if url:
                    citations.append(url)
    return "\n".join(answer_parts), citations


def _query_perplexity(prompt_text: str, model: str) -> Tuple[str, List[str]]:
    import requests

    key = os.environ["PERPLEXITY_API_KEY"]  # caller guarantees presence
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt_text}]},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    answer = data["choices"][0]["message"]["content"]
    citations = data.get("citations", []) or []
    return answer, citations


_QUERY_FUNCS = {
    "chatgpt": _query_chatgpt,
    "gemini": _query_gemini,
    "claude": _query_claude,
    "perplexity": _query_perplexity,
}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def _model_runnable(model_key: str) -> bool:
    """A model is runnable only if enabled AND its API key is present.
    Missing keys (notably Perplexity) never raise — the model is skipped."""
    cfg = MODEL_CONFIG[model_key]
    if not cfg["enabled"]:
        return False
    if not os.getenv(cfg["api_key_env"]):
        print(f"[info] {model_key}: {cfg['api_key_env']} not set — skipping.")
        return False
    return True


def collect(date: Optional[str] = None,
            prompts: Optional[List[Dict[str, Any]]] = None,
            out_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Run all enabled models across all prompts for ``date`` (YYYY-MM-DD,
    defaults to today UTC). Returns a list of record dicts (also written to
    disk). Records with ``"error"`` set represent missing observations.

    ``prompts`` / ``out_dir`` を渡すと別のプロンプト集合を同じ手順で回せる
    (Phase 3 の月次観測)。リトライ・掃き直し・欠測の数え方を月次側に
    書き写さないための引数で、既定では日次のまま動く。
    """
    date = date or dt.datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = Path(out_dir) if out_dir is not None else DATA_RAW_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts = load_prompts() if prompts is None else list(prompts)
    models = [m for m in enabled_models() if _model_runnable(m)]
    print(f"[info] date={date} models={models} prompts={len(prompts)}")

    # 1日あたりの枠を使い切ったモデル。以後は基本の1回だけ投げ、
    # リトライで枠をさらに消費しない。
    exhausted: set = set()
    records: List[Dict[str, Any]] = []
    for prompt in prompts:
        pid = prompt["id"]
        for model_key in models:
            model_name = MODEL_CONFIG[model_key]["model"]
            label = f"{pid}/{model_key}"
            record: Dict[str, Any] = {
                "date": date,
                "prompt_id": pid,
                # 月次プロンプトは pillar を持たず category を持つ。
                # 抽出とシート書き込みが同じ形を期待するので、両方入れておく。
                "pillar": prompt.get("pillar", ""),
                "category": prompt.get("category", ""),
                "target_brand": prompt.get("target_brand", ""),
                "model": model_key,
                "model_name": model_name,
                "question": prompt["text"],
                "cep": prompt.get("cep"),
                "timestamp": None,
                "answer": None,
                "cited_urls": [],
                "error": None,
            }
            _attempt(record, prompt["text"], attempts=(
                1 if model_key in exhausted else MAX_RETRIES
            ), on_daily_quota=lambda mk=model_key: exhausted.add(mk))
            _save(record, out_dir)
            records.append(record)

    _sweep(records, prompts, out_dir)
    missing = missing_observations(records)
    print(f"[info] {date}: 観測 {len(records)}件中 欠測 {len(missing)}件"
          + (f" — {', '.join(missing)}" if missing else ""))
    return records


def _attempt(record: Dict[str, Any], question: str, *, attempts: int,
             on_daily_quota=None) -> bool:
    """1観測を取って ``record`` を埋める。成功したら True。

    失敗しても例外は投げない。1つのモデルの不調で他のプロンプトを
    落とさないため、欠測として記録して先へ進む(§3)。
    """
    label = f"{record['prompt_id']}/{record['model']}"
    try:
        answer, native_cits = _with_retry(
            lambda: _QUERY_FUNCS[record["model"]](question, record["model_name"]),
            label=label, attempts=attempts, on_daily_quota=on_daily_quota,
        )
        record["answer"] = answer
        record["cited_urls"] = _merge_urls(answer, native_cits)
        record["error"] = None
        record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
        print(f"[ok] {label}: {len(answer)} chars, {len(record['cited_urls'])} urls")
        return True
    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)
        record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
        print(f"[error] {label}: recorded as missing — {exc}")
        return False


def _save(record: Dict[str, Any], out_dir: Path) -> None:
    """観測を data/raw に書く。掃き直しで回復した内容もここで上書きする。"""
    raw_path = out_dir / f"{record['prompt_id']}_{record['model']}.json"
    payload = {k: v for k, v in record.items() if k != "raw_file"}
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    try:
        record["raw_file"] = str(raw_path.relative_to(DATA_RAW_DIR.parent.parent))
    except ValueError:
        # リポジトリ外に書いた場合(テストの一時ディレクトリなど)。
        # 表示用の値なので、ここで落として回復した観測を失うほうが悪い。
        record["raw_file"] = str(raw_path)


def _sweep(records: List[Dict[str, Any]], prompts: List[Dict[str, Any]],
           out_dir: Path, cooldown: float = SWEEP_COOLDOWN_SECONDS) -> int:
    """失敗した観測だけを、間を置いてもう一度取り直す。

    観測した provider 側の障害は20〜90秒で収まっており、一巡した頃には
    抜けていることが多い(08-27・08-30 の gemini は、失敗した次の
    プロンプトが35秒後に成功している)。回数を増やすのではなく
    「時間をおいて1回」にするのは、gemini 無料枠の1日20リクエストを
    リトライで食い潰さないため。

    待っても直らないエラーは掃き直さない。戻した件数を返す。
    """
    targets = [r for r in records
               if r.get("error") and not is_permanent(Exception(r["error"]))]
    if not targets:
        return 0

    questions = {p["id"]: p["text"] for p in prompts}
    labels = ", ".join(f"{r['prompt_id']}/{r['model']}" for r in targets)
    print(f"[info] 掃き直し: {len(targets)}件を {cooldown:.0f}秒後に再取得します ({labels})")
    time.sleep(cooldown)

    recovered = 0
    for record in targets:
        # 掃き直しは1回だけ。ここで回数を重ねると枠の消費が読めなくなる。
        if _attempt(record, questions[record["prompt_id"]], attempts=1):
            recovered += 1
        _save(record, out_dir)
    print(f"[info] 掃き直し: {recovered}/{len(targets)}件を回復しました")
    return recovered


def missing_observations(records: List[Dict[str, Any]]) -> List[str]:
    """欠測になった観測のラベル。run_daily がこれを見て失敗として積む(§4)。"""
    return [f"{r['prompt_id']}/{r['model']}" for r in records if r.get("error")]


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM fixed-point observation collector")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()
    collect(args.date)


if __name__ == "__main__":
    main()
