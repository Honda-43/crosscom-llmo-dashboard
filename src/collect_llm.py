"""collect_llm.py — fixed-point observation across LLMs (§3).

Sends each approved prompt (§2) to every enabled model as a *bare user
question* (no system instruction, default temperature) with the model's
native web-search tool enabled, then stores the full answer plus citations to
``data/raw/YYYY-MM-DD/{prompt_id}_{model}.json``.

Design notes:
- Model enable/disable + model names live in settings.py.
- Retry: exponential backoff, max 3 attempts. A model that fails all attempts
  is recorded as a missing observation for the day; other models continue.
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
    enabled_models,
    load_prompts,
)

URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


# --------------------------------------------------------------------------
# Retry helper
# --------------------------------------------------------------------------
def _with_retry(fn, *, label: str):
    """Run ``fn`` with exponential backoff. Raises the last error after
    MAX_RETRIES failures so the caller can record the day as missing."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we retry all provider errors
            last_exc = exc
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"[warn] {label} attempt {attempt}/{MAX_RETRIES} failed: {exc}")
            if attempt < MAX_RETRIES:
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


def collect(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run all enabled models across all prompts for ``date`` (YYYY-MM-DD,
    defaults to today UTC). Returns a list of record dicts (also written to
    disk). Records with ``"error"`` set represent missing observations."""
    date = date or dt.datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = DATA_RAW_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts = load_prompts()
    models = [m for m in enabled_models() if _model_runnable(m)]
    print(f"[info] date={date} models={models} prompts={len(prompts)}")

    records: List[Dict[str, Any]] = []
    for prompt in prompts:
        pid = prompt["id"]
        for model_key in models:
            model_name = MODEL_CONFIG[model_key]["model"]
            label = f"{pid}/{model_key}"
            record: Dict[str, Any] = {
                "date": date,
                "prompt_id": pid,
                "pillar": prompt["pillar"],
                "model": model_key,
                "model_name": model_name,
                "question": prompt["text"],
                "cep": prompt.get("cep"),
                "timestamp": None,
                "answer": None,
                "cited_urls": [],
                "error": None,
            }
            try:
                answer, native_cits = _with_retry(
                    lambda mk=model_key, mn=model_name, txt=prompt["text"]: _QUERY_FUNCS[mk](txt, mn),
                    label=label,
                )
                record["answer"] = answer
                record["cited_urls"] = _merge_urls(answer, native_cits)
                record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
                print(f"[ok] {label}: {len(answer)} chars, {len(record['cited_urls'])} urls")
            except Exception as exc:  # noqa: BLE001
                record["error"] = str(exc)
                record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
                print(f"[error] {label}: recorded as missing — {exc}")

            raw_path = out_dir / f"{pid}_{model_key}.json"
            with open(raw_path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
            record["raw_file"] = str(raw_path.relative_to(DATA_RAW_DIR.parent.parent))
            records.append(record)

    return records


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM fixed-point observation collector")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()
    collect(args.date)


if __name__ == "__main__":
    main()
