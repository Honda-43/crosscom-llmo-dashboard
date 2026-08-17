"""generate_insight.py — stage 2 of the weekly insight engine (Phase 2 §3).

Turns the deterministic output of rules_engine.py into Japanese prose. The model
sees **only stats.json plus the playbook** — never a raw answer, never the
spreadsheet. It is not allowed to judge anything: every verdict it writes about
was already decided in stage 1.

If the model call fails, ``fallback_report()`` produces the same document
structure straight from stats.json. A broken LLM must degrade the report, not
delete it (§5).
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

from settings import INSIGHT_MAX_CHARS, INSIGHT_MODEL, PLAYBOOK_FILE

# The five sections are fixed by §3 — the Slack formatter and the reader both
# rely on this order.
_SECTIONS = [
    "1. 今週のサマリ",
    "2. 数値ハイライト",
    "3. 発火パターンと推奨アクション",
    "4. ウォッチ項目",
    "5. 判定不能・データ不足",
]

_SYSTEM_TEMPLATE = """あなたはLLMO(LLM最適化)の週次レポートを書くアナリストです。
以下の運用プレイブックに従い、与えられた統計データ(stats.json)だけを根拠に日本語の所見を書きます。

# 絶対に守る禁止事項
- **stats.jsonに存在しない数値・事実・企業名を書いてはならない。** 推測値・概算・「約○件」も禁止。
- 判定はすでに機械的に完了している。発火・非発火を自分で判断し直さない。
  stats.jsonのrulesにあるstatusをそのまま前提として扱う。
- 根拠が薄いときは断定せず「データ上は判断できない」と書く。創作で埋めない。
- プレイブックにない独自のフレームワークを持ち出さない。
- **kgi の指標に `noise_zone: true` が付いている場合、その増減を「悪化」「改善」「要対応」と
  表現してはならない。** 母数が小さく週次の増減に意味がないという意味なので、
  実数を併記したうえで「母数が小さく判断できない水準」と明示する。
  ノイズ域の指標を推奨アクションの根拠にしてはならない。
- ルールに `coverage` がある場合、それは判定できたデータの範囲である。
  一部しか評価できていない `not_fired` を「問題なし」と言い切らない。

# 出力フォーマット(この5セクション構成に固定。見出しは変更しない)
## 1. 今週のサマリ
3行以内。今週の状態を一言で。

## 2. 数値ハイライト
mention_rate 3系列(all / pillar A / pillar B)、SoV首位、KGI週計(AI経由セッション・指名クリック)。
すべて前週比を添える。数値はstats.jsonの値をそのまま使う。

## 3. 発火パターンと推奨アクション
発火した rule_id ごとに「状態 → 原因仮説 → アクション」。
原因仮説と改善策はプレイブックの対応するP-パターンを根拠にする。
**アクションは本田さんが承認/却下できる具体的な形**(誰が何をいつまでに、が決まる粒度)で、
**全体で最大3件**。発火が0件なら「今週の発火パターンはありません」と書く。

## 4. ウォッチ項目
発火はしていないが変化の兆しがあるもの。最大3件。無ければ「なし」。

## 5. 判定不能・データ不足
insufficient_data のルールと、観測日数が不足している項目を明示する。無ければ「なし」。

# 文量
全体で{max_chars}字以内。冗長な前置きは書かない。

---
# 運用プレイブック
{playbook}
"""

_USER_TEMPLATE = """以下が今週の stats.json です。この内容だけを根拠にレポートを書いてください。

```json
{stats_json}
```
"""


def load_playbook() -> str:
    """The operational playbook that grounds the cause/action prose (§3)."""
    try:
        with open(PLAYBOOK_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"playbook not found at {PLAYBOOK_FILE}. "
            "config/playbook.md is required by Phase 2 §3."
        ) from exc


def build_system_prompt(playbook: Optional[str] = None,
                        max_chars: int = INSIGHT_MAX_CHARS) -> str:
    return _SYSTEM_TEMPLATE.format(
        playbook=playbook if playbook is not None else load_playbook(),
        max_chars=max_chars,
    )


def build_user_prompt(stats: Dict[str, Any]) -> str:
    return _USER_TEMPLATE.format(
        stats_json=json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True)
    )


def _call_model(system: str, user: str, model: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()


# --------------------------------------------------------------------------
# Deterministic fallback
# --------------------------------------------------------------------------
def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "データなし"
    if isinstance(value, float):
        return f"{round(value, digits):g}"
    return str(value)


def _fmt_delta(value: Any) -> str:
    if value is None:
        return "(前週比 データなし)"
    rounded = round(value, 4)
    if rounded == 0:
        return "(前週比 ±0)"
    return f"(前週比 {'+' if rounded > 0 else ''}{rounded:g})"


def _series_line(label: str, series: Dict[str, Any]) -> str:
    line = (
        f"- {label}: {_fmt(series.get('this_week'))} "
        f"{_fmt_delta(series.get('delta'))}"
    )
    if series.get("noise_zone"):
        line += " ※母数が小さく判断できない水準"
    return line


def fallback_report(stats: Dict[str, Any]) -> str:
    """The same 5 sections, built from stats.json without the LLM (§5).

    Numbers only, no interpretation — an honest degraded report rather than a
    missing one.
    """
    lines: List[str] = [f"# LLMO週次所見 {stats.get('date', '')}", ""]
    lines += [
        "> ⚠️ 所見文の自動生成に失敗したため、stats.json の数値サマリのみを配信しています。",
        "> 解釈・推奨アクションは含まれません。",
        "",
    ]

    fired = [r for r in stats.get("rules", []) if r.get("fired")]
    insufficient = [r for r in stats.get("rules", []) if r.get("status") == "insufficient_data"]

    lines += [f"## {_SECTIONS[0]}", ""]
    lines.append(
        f"発火パターン {len(fired)}件"
        + (f"({', '.join(r['rule_id'] for r in fired)})" if fired else "")
        + f" / 判定不能 {len(insufficient)}件。"
    )
    lines.append("")

    rate = stats.get("mention_rate", {})
    lines += [f"## {_SECTIONS[1]}", ""]
    lines.append(_series_line("mention_rate (all)", rate.get("all", {})))
    lines.append(_series_line("mention_rate (pillar A)", rate.get("pillar_a", {})))
    lines.append(_series_line("mention_rate (pillar B)", rate.get("pillar_b", {})))

    top = (stats.get("sov", {}).get("all", {}) or {}).get("entities") or []
    if top:
        head = top[0]
        lines.append(
            f"- SoV首位: {head['entity']} {_fmt(head['mention_count'])}回 "
            f"{_fmt_delta(head.get('delta'))}"
        )
    kgi = stats.get("kgi", {})
    lines.append(_series_line("AI経由セッション", kgi.get("ai_sessions", {})))
    lines.append(_series_line("指名検索クリック", kgi.get("branded_clicks", {})))
    lines.append("")

    lines += [f"## {_SECTIONS[2]}", ""]
    if fired:
        for rule in fired:
            lines.append(f"- **{rule['rule_id']}**: {rule.get('detail', '')}")
    else:
        lines.append("今週の発火パターンはありません。")
    lines.append("")

    lines += [f"## {_SECTIONS[3]}", "", "なし(自動生成失敗のため未評価)", ""]

    lines += [f"## {_SECTIONS[4]}", ""]
    if insufficient:
        for rule in insufficient:
            lines.append(f"- {rule['rule_id']}: {rule.get('detail', '')}")
    else:
        lines.append("なし")
    quality = stats.get("data_quality", {})
    lines.append(
        f"- 観測日数: 今週 {quality.get('observation_days_this_week', 0)}日 / "
        f"前週 {quality.get('observation_days_prev_week', 0)}日"
    )
    noisy = stats.get("kgi", {}).get("noise_zone_metrics") or []
    if noisy:
        lines.append(
            f"- ノイズ域(週計 {_fmt(stats['kgi'].get('noise_floor'))} 未満)の指標: "
            f"{', '.join(noisy)} — 増減は判断材料にしない"
        )
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def generate(stats: Dict[str, Any], model: Optional[str] = None,
             playbook: Optional[str] = None) -> Dict[str, Any]:
    """Return ``{"report_md", "source", "error"}``.

    ``source`` is ``"llm"`` or ``"fallback"``. This never raises: a weekly
    report that fails to render is still delivered as numbers (§5).
    """
    model = model or INSIGHT_MODEL
    try:
        system = build_system_prompt(playbook)
        report = _call_model(system, build_user_prompt(stats), model)
        if not report.strip():
            raise RuntimeError("model returned an empty report")
        if len(report) > INSIGHT_MAX_CHARS * 2:
            # Well past the instructed limit — keep it, but say so.
            print(f"[warn] insight is {len(report)} chars, over the {INSIGHT_MAX_CHARS} target")
        print(f"[ok] generate_insight: {len(report)} chars via {model}")
        return {"report_md": report, "source": "llm", "error": None}
    except Exception as exc:  # noqa: BLE001 - degrade, never drop the report
        print(f"[warn] generate_insight failed ({exc}) — falling back to the numeric summary")
        return {"report_md": fallback_report(stats), "source": "fallback", "error": str(exc)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly insight generation (stage 2)")
    ap.add_argument("--stats", required=True, help="path to a stats.json produced by rules_engine")
    ap.add_argument("--model", help=f"override the model (default {INSIGHT_MODEL})")
    ap.add_argument("--fallback-only", action="store_true",
                    help="skip the API and print the deterministic report")
    args = ap.parse_args()

    with open(args.stats, "r", encoding="utf-8") as fh:
        stats = json.load(fh)

    if args.fallback_only:
        print(fallback_report(stats))
        return
    print(generate(stats, args.model)["report_md"])


if __name__ == "__main__":
    main()
