"""collect_llm.py — fixed-point observation across LLMs (§3).

Sends each approved prompt (§2) to every enabled model as a *bare user
question* (no system instruction, default temperature) with the model's
native web-search tool enabled, then stores the full answer plus citations to
``data/raw/YYYY-MM-DD/{prompt_id}_{model}.json``.

Design notes:
- Model enable/disable + model names live in settings.py.
- Retry: exponential backoff。provider が retryDelay を返したらそちらを優先する。
  一巡したあと、失敗した観測だけを掃き直す(_sweep)。それでも取れなければ
  その日の欠測として記録し、他のモデル・プロンプトは続行する。
- **503 と 429 を区別する**(2026-09-18)。
    - 503 UNAVAILABLE は provider 側の一時的な混雑。観測した障害窓は20〜90秒で、
      待てば戻る。再試行と掃き直しの対象はこれ。
    - 429 はリクエスト枠切れ。待っても同じ日のうちは戻らないうえ、再試行が
      枠をさらに食う。**取り直さずその場で欠測にする**(翌日には戻る)。
  欠測の理由は ``miss_reason`` が quota / unavailable / permanent / error に
  分ける。呼び出し側はこれを見て、終了コードと日誌の書き方を決める。
- 日次のリクエスト枠(gemini 無料枠は1日20回)を守るため、取り直しの回数を
  ``RetryBudget`` で上から抑えられる。枠の余りを渡せば、再試行・掃き直しの
  合計がその範囲を超えない。
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

# 枠切れ(429)と一時的な混雑(503)の目印。
# 429 は「1分あたり」でも「1日あたり」でも、再試行がその枠をさらに食う。
# 実験のプロトコルで「取り直さず欠測」にするのはこの 429 だけ。
_QUOTA_CODE = "429"
_DAILY_QUOTA_MARKER = "PerDay"
_UNAVAILABLE_CODE = "503"
_UNAVAILABLE_MARKER = "UNAVAILABLE"

# 欠測の理由コード。実験日誌(data/experiment_journal.csv)に残す値でもある。
REASON_QUOTA = "quota"              # 429。枠切れ。取り直さない
REASON_UNAVAILABLE = "unavailable"  # 503。一時的な混雑。枠の余りの範囲で取り直す
REASON_PERMANENT = "permanent"      # 鍵・権限・課金。人が直すまで変わらない
REASON_OTHER = "error"              # それ以外(コードの例外を含む)

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


def is_quota(exc: Exception) -> bool:
    """リクエスト枠を使い切ったか(429)。

    「1日あたり」か「1分あたり」かは区別しない。どちらも再試行がその枠を
    さらに食うので、待たずに欠測にして次へ進む。課金切れ(insufficient_quota)は
    ``is_permanent`` が先に拾うので、ここには来ない。
    """
    return _QUOTA_CODE in str(exc)[:40] and not is_permanent(exc)


def is_daily_quota(exc: Exception) -> bool:
    """429 のうち「1日あたり」の枠切れか。枠が翌日まで戻らないことの判定。"""
    return is_quota(exc) and _DAILY_QUOTA_MARKER in str(exc)


def is_unavailable(exc: Exception) -> bool:
    """provider 側の一時的な混雑(503 UNAVAILABLE)か。取り直す価値があるもの。"""
    text = str(exc)
    transient = _UNAVAILABLE_CODE in text[:40] or _UNAVAILABLE_MARKER in text
    return transient and not is_permanent(exc) and not is_quota(exc)


def miss_reason(error: Any) -> str:
    """欠測の理由コード。空文字は「欠測ではない」。

    順番に意味がある。429 のうち課金切れ(insufficient_quota)は待っても
    戻らないので permanent、枠切れは quota。503 は unavailable。
    """
    if error in (None, ""):
        return ""
    exc = error if isinstance(error, BaseException) else Exception(str(error))
    if is_permanent(exc):
        return REASON_PERMANENT
    if is_quota(exc):
        return REASON_QUOTA
    if is_unavailable(exc):
        return REASON_UNAVAILABLE
    return REASON_OTHER


def is_retriable(error: Any) -> bool:
    """取り直す価値のある欠測か。503 だけが真。"""
    return miss_reason(error) == REASON_UNAVAILABLE


class RetryBudget:
    """その日の枠の余り。取り直し1回につき1本減る。

    実験の Gemini は、日次・月次と20回/日の枠を分け合っている。再試行と
    掃き直しをそれぞれ独立に数えると合計が読めなくなるので、1つの財布から
    引く。``spend`` が False を返したら、そこで取り直しをやめる。
    """

    def __init__(self, spare: int) -> None:
        self.remaining = max(0, int(spare))
        self.used = 0

    def spend(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        self.used += 1
        return True

    def __repr__(self) -> str:  # pragma: no cover - ログ用
        return f"RetryBudget(remaining={self.remaining}, used={self.used})"


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
                on_quota=None, budget: Optional["RetryBudget"] = None):
    """Run ``fn`` with exponential backoff. Raises the last error after
    ``attempts`` failures so the caller can record the day as missing.

    4つの理由で早く諦める:
      - 待っても直らないエラー(鍵・権限・課金)は1回で止める
      - 429(枠切れ)は、リトライがその枠をさらに食う。1回で止める
      - ``budget`` を渡した場合、余りが尽きたらそこで止める
      - provider が retryDelay を返したら、固定のバックオフより優先する

    503 の既定は「初回 + 3回」で、待ちは 5 / 10 / 20 秒(合計35秒)。
    実測した障害窓20〜90秒のうち、短いほうを跨ぐことを狙っている。
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
            if is_quota(exc):
                print(f"[warn] {label}: リクエスト枠を超過(429)。"
                      f"取り直さず欠測にする")
                if on_quota is not None:
                    on_quota()
                break
            if attempt < attempts:
                if budget is not None and not budget.spend():
                    print(f"[warn] {label}: その日の枠の余りが尽きたため再試行しない")
                    break
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
            out_dir: Optional[Path] = None,
            models: Optional[List[str]] = None,
            attempts: Optional[int] = None,
            sweep: bool = True,
            budget: Optional[RetryBudget] = None) -> List[Dict[str, Any]]:
    """Run all enabled models across all prompts for ``date`` (YYYY-MM-DD,
    defaults to today UTC). Returns a list of record dicts (also written to
    disk). Records with ``"error"`` set represent missing observations.

    ``prompts`` / ``out_dir`` を渡すと別のプロンプト集合を同じ手順で回せる
    (Phase 3 の月次観測)。リトライ・掃き直し・欠測の数え方を月次側に
    書き写さないための引数で、既定では日次のまま動く。

    ``models`` を渡すとそのモデルだけを回す(実験は Gemini と Claude で
    観測する曜日と本数が違う)。有効でない・鍵が無いモデルは従来どおり飛ばす。

    ``attempts`` / ``sweep`` はリトライの回数を呼び出し側で管理したいとき用。
    既定は従来どおり MAX_RETRIES(初回 + 3回、5/10/20秒)と掃き直しあり。

    ``budget`` を渡すと、再試行1回につき1本引く。0 になったらそれ以上
    取り直さない(実験の Gemini は、その日の枠の余りをこれで渡す)。
    """
    date = date or dt.datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = Path(out_dir) if out_dir is not None else DATA_RAW_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts = load_prompts() if prompts is None else list(prompts)
    candidates = enabled_models() if models is None else [
        m for m in enabled_models() if m in models]
    models = [m for m in candidates if _model_runnable(m)]
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
                # 欠測の理由コード(quota / unavailable / permanent / error)と、
                # この観測に投げたリクエスト数。実験日誌がこの2つを読む。
                "miss_reason": "",
                "attempts": 0,
            }
            _attempt(record, prompt["text"], attempts=(
                1 if model_key in exhausted else (attempts or MAX_RETRIES)
            ), on_quota=lambda mk=model_key: exhausted.add(mk), budget=budget)
            _save(record, out_dir)
            records.append(record)

    if sweep:
        _sweep(records, prompts, out_dir, budget=budget)
    missing = missing_observations(records)
    print(f"[info] {date}: 観測 {len(records)}件中 欠測 {len(missing)}件"
          + (f" — {', '.join(missing)}" if missing else ""))
    return records


def _attempt(record: Dict[str, Any], question: str, *, attempts: int,
             on_quota=None, budget: Optional[RetryBudget] = None) -> bool:
    """1観測を取って ``record`` を埋める。成功したら True。

    失敗しても例外は投げない。1つのモデルの不調で他のプロンプトを
    落とさないため、欠測として記録して先へ進む(§3)。

    ``attempts`` はこの呼び出しで投げる回数の上限。掃き直しで同じ record を
    もう一度渡すことがあるので、``attempts`` 列は**足し込む**(その観測に
    何本の枠を使ったかを日誌に残すため)。
    """
    label = f"{record['prompt_id']}/{record['model']}"
    tries = 0

    def call():
        nonlocal tries
        tries += 1
        return _QUERY_FUNCS[record["model"]](question, record["model_name"])

    try:
        answer, native_cits = _with_retry(
            call, label=label, attempts=attempts,
            on_quota=on_quota, budget=budget,
        )
        record["answer"] = answer
        record["cited_urls"] = _merge_urls(answer, native_cits)
        record["error"] = None
        record["miss_reason"] = ""
        record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
        print(f"[ok] {label}: {len(answer)} chars, {len(record['cited_urls'])} urls")
        return True
    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)
        record["miss_reason"] = miss_reason(exc)
        record["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
        print(f"[error] {label}: recorded as missing ({record['miss_reason']}) — {exc}")
        return False
    finally:
        record["attempts"] = (record.get("attempts") or 0) + tries


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
           out_dir: Path, cooldown: float = SWEEP_COOLDOWN_SECONDS,
           delays: Optional[Sequence[float]] = None,
           budget: Optional[RetryBudget] = None) -> int:
    """失敗した観測だけを、間を置いてもう一度取り直す。

    観測した provider 側の障害は20〜90秒で収まっており、一巡した頃には
    抜けていることが多い(08-27・08-30 の gemini は、失敗した次の
    プロンプトが35秒後に成功している)。回数を増やすのではなく
    「時間をおいて投げ直す」のは、gemini 無料枠の1日20リクエストを
    リトライで食い潰さないため。

    ``delays`` を渡すとその秒数ぶんだけ掃き直す(実験は60秒後・180秒後の
    2回。1回目で戻らない障害窓は90秒近いことがあるため)。既定は従来どおり
    ``cooldown`` 秒後に1回。

    **掃き直すのは 503 だけ**。429(枠切れ)は取り直しても同じ日のうちは
    戻らず、投げるだけ枠を食う。待っても直らないエラーも同じ。
    ``budget`` を渡した場合、1回投げるごとに1本引き、尽きたらそこで止める。
    戻した件数を返す。
    """
    rounds = list(delays) if delays else [cooldown]
    questions = {p["id"]: p["text"] for p in prompts}
    recovered = 0
    for index, wait in enumerate(rounds, start=1):
        targets = [r for r in records if is_retriable(r.get("error"))]
        if not targets:
            break
        labels = ", ".join(f"{r['prompt_id']}/{r['model']}" for r in targets)
        print(f"[info] 掃き直し{index}/{len(rounds)}: {len(targets)}件を "
              f"{wait:.0f}秒後に再取得します ({labels})")
        time.sleep(wait)
        for record in targets:
            if budget is not None and not budget.spend():
                print("[warn] 掃き直し: その日の枠の余りが尽きたため打ち切ります")
                return recovered
            # 1周につき1回だけ。ここで回数を重ねると枠の消費が読めなくなる。
            if _attempt(record, questions[record["prompt_id"]], attempts=1):
                recovered += 1
            _save(record, out_dir)
    print(f"[info] 掃き直し: {recovered}件を回復しました")
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
