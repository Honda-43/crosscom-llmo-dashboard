"""extract.py — structured extraction from raw LLM answers (§4).

Each stored answer is passed to a cheap Anthropic model (Haiku class) and
reduced to the approved JSON schema below. One answer = one extraction call.
On JSON-validation failure the extraction is retried exactly once; a second
failure produces an ``error`` record for that row.

NOTE: The output schema and the extraction rules are approved (§4) — the JSON
shape, the mention_type enum and the kbf_tags option list must not change.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from settings import BRAND_ALIASES, DATA_RAW_DIR, EXTRACT_MODEL

# --- Approved schema constants (§4) -----------------------------------------
MENTION_TYPES = {"recommended_list", "mentioned_only", "none"}
KBF_TAG_OPTIONS = {
    "ベンダー中立",
    "設計支援",
    "定着支援",
    "Agentforce専門性",
    "ソリューション営業知見",
    "実績・事例",
    "その他",
}

# The schema block is embedded verbatim from §4 so the model returns exactly it.
_SCHEMA_BLOCK = """{
  "mention": true,
  "mention_type": "recommended_list",  // recommended_list | mentioned_only | none
  "rank": 2,                            // 推薦リスト内順位。リスト外・言及なしはnull
  "kbf_tags": ["ベンダー中立", "定着支援"],
  // 選択肢: ベンダー中立 / 設計支援 / 定着支援 / Agentforce専門性 /
  //         ソリューション営業知見 / 実績・事例 / その他
  "negative_or_outdated": false,
  "negative_detail": null,              // 旧MA/メール配信事業の記述、誤情報等があれば内容を記載
  "cited_crosscom_urls": ["https://cross-com.jp/..."],
  "all_cited_urls": ["..."],
  "competitors_mentioned": ["社名1", "社名2"]
}"""


def _build_prompt(record: Dict[str, Any]) -> str:
    aliases = " / ".join(BRAND_ALIASES)
    is_entity = record.get("prompt_id") == "E-1"
    entity_note = (
        "- このE-1プロンプトはmention判定不要（必ず言及される）。"
        "negative_or_outdatedとkbf_tagsの精度を優先すること。\n"
        if is_entity
        else ""
    )
    return f"""あなたはLLMO観測の抽出エンジンです。以下の質問とAI回答を読み、指定のJSONスキーマだけを出力してください。

# 判定ルール
- 「{aliases}」の表記ゆれはすべて自社（クロスコム）への言及と判定する。
- mention: 自社が言及されていればtrue、されていなければfalse。
- mention_type: recommended_list（推薦・おすすめリストに入っている） | mentioned_only（言及のみ） | none（言及なし）。
- rank: 推薦リスト内での順位（1始まり）。リスト外・言及なしはnull。
- kbf_tags: 次の選択肢からのみ選ぶ（複数可）: ベンダー中立 / 設計支援 / 定着支援 / Agentforce専門性 / ソリューション営業知見 / 実績・事例 / その他。
- negative_or_outdated: 旧MA/メール配信事業の記述や誤情報など、ネガティブ・古い情報があればtrue。
- negative_detail: あればその内容、なければnull。
- cited_crosscom_urls: 引用URLのうちcross-com.jpドメインのもの。
- all_cited_urls: 回答が引用している全URL。
- competitors_mentioned: 言及された競合他社名。
{entity_note}
# 出力スキーマ（このJSONの形だけを、コメントを除いて出力）
{_SCHEMA_BLOCK}

# 質問
{record.get('question', '')}

# AI回答
{record.get('answer', '')}

# 参考: 回答に付随する引用URL
{json.dumps(record.get('cited_urls', []), ensure_ascii=False)}

JSONオブジェクトのみを出力してください。前置きやコードフェンスは不要です。"""


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in response")
    return json.loads(text[start : end + 1])


def _validate(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Validate & coerce to the approved schema. Raises ValueError on failure."""
    required = {
        "mention",
        "mention_type",
        "rank",
        "kbf_tags",
        "negative_or_outdated",
        "negative_detail",
        "cited_crosscom_urls",
        "all_cited_urls",
        "competitors_mentioned",
    }
    missing = required - obj.keys()
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")

    if not isinstance(obj["mention"], bool):
        raise ValueError("mention must be bool")
    if obj["mention_type"] not in MENTION_TYPES:
        raise ValueError(f"invalid mention_type: {obj['mention_type']}")
    if obj["rank"] is not None and not isinstance(obj["rank"], int):
        raise ValueError("rank must be int or null")
    if not isinstance(obj["kbf_tags"], list):
        raise ValueError("kbf_tags must be a list")
    for tag in obj["kbf_tags"]:
        if tag not in KBF_TAG_OPTIONS:
            raise ValueError(f"invalid kbf_tag: {tag}")
    if not isinstance(obj["negative_or_outdated"], bool):
        raise ValueError("negative_or_outdated must be bool")
    for key in ("cited_crosscom_urls", "all_cited_urls", "competitors_mentioned"):
        if not isinstance(obj[key], list):
            raise ValueError(f"{key} must be a list")
    return obj


def _call_model(prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
    )


def extract_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract one raw record to the §4 schema. Returns a dict that always has
    ``prompt_id``/``model``; on unrecoverable failure it carries ``error``."""
    base = {
        "date": record.get("date"),
        "prompt_id": record.get("prompt_id"),
        "pillar": record.get("pillar"),
        "model": record.get("model"),
        "raw_file": record.get("raw_file"),
    }

    if record.get("error") or not record.get("answer"):
        return {**base, "error": record.get("error") or "no answer text"}

    prompt = _build_prompt(record)
    last_err: Optional[str] = None
    for attempt in (1, 2):  # initial + one retry (§4)
        try:
            raw = _call_model(prompt)
            obj = _validate(_extract_json(raw))
            return {**base, **obj, "error": None}
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            print(f"[warn] extract {base['prompt_id']}/{base['model']} attempt {attempt} failed: {exc}")

    print(f"[error] extract {base['prompt_id']}/{base['model']}: {last_err}")
    return {**base, "error": last_err}


def extract_date(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Extract every raw record saved under data/raw/<date>/."""
    date = date or dt.datetime.utcnow().strftime("%Y-%m-%d")
    raw_dir = DATA_RAW_DIR / date
    if not raw_dir.exists():
        print(f"[warn] no raw dir for {date}")
        return []

    results: List[Dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        with open(path, "r", encoding="utf-8") as fh:
            record = json.load(fh)
        results.append(extract_record(record))
    print(f"[ok] extracted {len(results)} records for {date}")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Structured extraction of LLM answers")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()
    extract_date(args.date)


if __name__ == "__main__":
    main()
