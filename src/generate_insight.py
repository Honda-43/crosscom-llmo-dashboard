"""generate_insight.py — stage 2 of the weekly insight engine (Phase 2 §3).

Turns the deterministic output of rules_engine.py into Japanese prose. The model
sees **only stats.json plus the playbook** — never a raw answer, never the
spreadsheet. It is not allowed to judge anything: every verdict it writes about
was already decided in stage 1.

If the model call fails, ``fallback_report()`` produces the same document
structure straight from stats.json. A broken LLM must degrade the report, not
delete it (§5).

Phase 7 で2つ足した:

- 実施済み施策の再提案を止める(§A)。推奨アクションを書かせる前に
  action_log を読み、決着済みの施策と同じ「根拠rule_id + 対象」を
  プロンプトで除外し、残ったものを後処理で差し替える。
- 記述ルール(§B)。率・差分の表記、パターンの日本語説明、禁止語、
  3行の箇条書き、同時発火の統合。確定的に直せるものは insight_style で直す。
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence

import insight_style
from settings import (
    INSIGHT_MAX_CHARS,
    INSIGHT_MAX_TOKENS,
    INSIGHT_MODEL,
    PLAYBOOK_FILE,
    RULES_THRESHOLDS_FILE,
    load_yaml,
)

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
- **本文の用語は日本語で書く。** 所見はダッシュボードのP5に並べて読むので、
  画面のラベルと呼び方を揃える。stats.jsonのキー名をそのまま本文に書かない。
  mention_rate は言及率 / SoV は言及シェア / share はシェア / rank は順位 /
  mention は言及 / model はモデル / KGI は成果指標(初出のみ「成果指標(KGI)」) /
  pillar A は Agentforce系(A) / pillar B は Agentic CRM系(B)。
  英字のまま書いてよいのは、製品名(Gemini・Claude・Salesforce等)、識別コードの値
  (rule_id・prompt_id・action_id)、定着した略語(AI・KBF・CEP・URL)、URLだけ。
- **URLを書くときは `https://` から始まる完全な形で書き、前後に半角スペースを入れる。**
  日本語に直付けすると（例:「E-1でcross-com.jp/...」）配信先でホスト名の一部と
  解釈され、リンクが壊れる。可能なら本文にURLを書かず、パスだけを引用する
  （例:「/service/btob-marketing-strategy/ が引用されている」）。

# 記述ルール(必ず守る)
1. **率は%で書く。** 0.4818 のような小数の生値を本文に出さない(「48%」と書く)。
2. **率の差分は「ポイント」で書く。** 「+7ポイント」。%で書くと率そのものと混ざる。
   実数(件数・セッション数)の差分は「+6件」のように単位を付ける。ポイントは使わない。
3. **前週比が±{flat_points}ポイント以内の変化は「横ばい」と書く。**
   「改善」「悪化」「低下」と書かない。括弧で実数は必ず併記する
   (例:「48%(前週50%、前週比 横ばい(-2ポイント))」)。
4. **発火パターンは初出時に日本語の説明を併記する。**
   例:「R-P2(言及消失:同一プロンプトで3観測日以上言及がない)」。2回目以降は付けない。
5. **各パターンは次の3行の箇条書きにする。**
   ```
   状態: (観測された事実。数値と対象を必ず書く)
   原因仮説: (プレイブックの対応するP-パターンを根拠にする)
   推奨アクション: (誰が何をいつまでに)
   ```
6. **本文のどこでも矢印記法(→)を使わない。**前後関係は言葉で書く
   (「前週0件、今週0件」「8位から2位」)。
7. **各文に主語を明示する。** 「AIの回答は」「クロスコムは」「競合の◯◯社は」
   のように、誰について述べているのかを文ごとに書く。主語のない文を書かない。
8. **次の語は使わない(比喩で状態をぼかすため):**
   押し出す / 定着 / 供給 / 型 / 浮上 / 急落 / 様子見。その他の比喩も使わない。
   何が何位から何位になったのか、何週続いたのか、誰が何を公開したのかを、
   そのまま書く。ただし自社サービス名「Agentforce導入・定着支援」だけは例外。
9. **同一プロンプトで R-P2 と R-P15 が同時に発火している場合は1項目に統合する。**
   自社の言及が消えたことと、同じ面に競合が出続けていることは同じ出来事の裏表で、
   2件として数えさせない。見出しは次の形に固定する:
   ```
   **R-P2(P-2の定義)・R-P15(P-15の定義) — 対象のprompt_id**
   ```
   **括弧内の定義はプレイブックの該当パターンの「状態」をそのまま使う。**
   統合したからといって2つを混ぜた新しい定義を作らない
   (「言及消失と競合の連続出現の統合:…」のような書き方をしない)。
   統合したことは見出しの並び(R-P2・R-P15)で示せば足りる。
   推奨アクションは1行にまとめ、「①競合の引用ページ調査、②自社ページ更新」の
   順に固定する。

# 出力フォーマット(この5セクション構成に固定。見出しは変更しない)
## 1. 今週のサマリ
3行以内。今週の状態を一言で。

## 2. 数値ハイライト
言及率3系列(全体 / Agentforce系(A) / Agentic CRM系(B))、言及シェア首位、
成果指標(KGI)週計(AI経由セッション・指名検索クリック)。
すべて前週比を添える。数値はstats.jsonの値をそのまま使う(表記は記述ルール1〜3に従う)。

## 3. 発火パターンと推奨アクション
発火した rule_id ごとに、見出し行 `**R-xx(日本語の説明)**` と記述ルール5の3行。
原因仮説と改善策はプレイブックの対応するP-パターンを根拠にする。
**推奨アクションは本田さんが承認/却下できる具体的な形**(誰が何をいつまでに、が決まる粒度)で、
**全体で最大3件**。発火が0件なら「今週の発火パターンはありません」と書く。
**「着手済みの施策」に載っている施策と同じ根拠rule_id・同じ対象の施策は、
新たに提案しない。**代わりにその行を
「推奨アクション: 実施済み(A-00N・実施日)。効果測定中」の1行にする。

## 4. ウォッチ項目
発火はしていないが変化の兆しがあるもの。最大3件。無ければ「なし」。

## 5. 判定不能・データ不足
insufficient_data のルールと、観測日数が不足している項目を明示する。無ければ「なし」。

# 文量
全体で{max_chars}字以内。冗長な前置きは書かない。
**5つのセクションを必ず最後まで書き切る。**途中で終わらせない。

---
# 運用プレイブック
{playbook}
"""

_USER_TEMPLATE = """以下が今週の stats.json です。この内容だけを根拠にレポートを書いてください。

```json
{stats_json}
```

# 着手済みの施策(action_log。状態が「承認」「実施済み・効果測定中」「完了」のもの)
同じ根拠rule_id・同じ対象の施策を、今週の推奨アクションとして再提案しないでください。

{settled_actions}

# 表示用の数値(本文にはこの表記で書く。小数の生値は書かない)
{formatted_numbers}
{co_fired}"""

_CO_FIRED_TEMPLATE = """
# 統合が必要な発火
次のプロンプトは R-P2 と R-P15 が同時に発火しています。1項目に統合し、
推奨アクションは「①競合の引用ページ調査、②自社ページ更新」の順にしてください。
見出しは `**R-P2(P-2の定義)・R-P15(P-15の定義) — 対象のprompt_id**` の形にし、
定義はプレイブックの「状態」をそのまま使ってください。

{prompt_ids}
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


_THRESHOLDS: Optional[Dict[str, Any]] = None


def load_thresholds() -> Dict[str, Any]:
    """記述ルールの閾値。rules_engine と同じファイルを読む。"""
    global _THRESHOLDS
    if _THRESHOLDS is None:
        _THRESHOLDS = load_yaml(RULES_THRESHOLDS_FILE) or {}
    return _THRESHOLDS


def build_system_prompt(playbook: Optional[str] = None,
                        max_chars: int = INSIGHT_MAX_CHARS,
                        thresholds: Optional[Dict[str, Any]] = None) -> str:
    return _SYSTEM_TEMPLATE.format(
        playbook=playbook if playbook is not None else load_playbook(),
        max_chars=max_chars,
        flat_points=insight_style.flat_delta_points(
            thresholds if thresholds is not None else load_thresholds()
        ),
    )


def _formatted_numbers(stats: Dict[str, Any], flat: int) -> str:
    """本文で使ってよい数値の表記を、値ごとに書き出す。

    「%で書け」と指示するだけでは、モデルは stats.json の小数をそのまま
    写すことがある。写す先の文字列を渡しておけば迷わない。
    """
    rate = stats.get("mention_rate") or {}
    lines = []
    for key, label in (("all", "言及率(全体)"),
                       ("pillar_a", "言及率(Agentforce系(A))"),
                       ("pillar_b", "言及率(Agentic CRM系(B))")):
        series = rate.get(key) or {}
        lines.append(
            f"- {label}: {insight_style.rate_text(series.get('this_week'))}"
            f"(前週 {insight_style.rate_text(series.get('prev_week'))}、"
            f"{insight_style.points_text(series.get('delta'), flat)})"
        )
    for entity in ((stats.get("sov") or {}).get("all") or {}).get("entities", [])[:3]:
        lines.append(
            f"- 言及シェア {entity.get('entity')}: "
            f"{insight_style.rate_text(entity.get('share'))}"
            f"({insight_style.count_text(entity.get('mention_count'))}、"
            f"{insight_style.count_delta_text(entity.get('delta'))})"
        )
    kgi = stats.get("kgi") or {}
    for key, label, unit in (("ai_sessions", "AI経由セッション", "セッション"),
                             ("ai_key_events", "AI経由キーイベント", "件"),
                             ("branded_clicks", "指名検索クリック", "クリック"),
                             ("branded_impressions", "指名検索表示", "回")):
        series = kgi.get(key) or {}
        note = "(母数が小さく判断できない水準)" if series.get("noise_zone") else ""
        lines.append(
            f"- 成果指標(KGI) {label}: {insight_style.count_text(series.get('this_week'), unit)}"
            f"(前週 {insight_style.count_text(series.get('prev_week'), unit)}、"
            f"{insight_style.count_delta_text(series.get('delta'), unit)}){note}"
        )
    return "\n".join(lines)


def build_user_prompt(stats: Dict[str, Any],
                      actions: Sequence[Dict[str, Any]] = (),
                      thresholds: Optional[Dict[str, Any]] = None) -> str:
    import action_log

    thresholds = thresholds if thresholds is not None else load_thresholds()
    co_fired = insight_style.co_fired_prompts(stats)
    return _USER_TEMPLATE.format(
        stats_json=json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True),
        settled_actions=action_log.prompt_block(actions),
        formatted_numbers=_formatted_numbers(
            stats, insight_style.flat_delta_points(thresholds)
        ),
        co_fired=(
            _CO_FIRED_TEMPLATE.format(
                prompt_ids="\n".join(f"- {p}" for p in co_fired)
            ) if co_fired else ""
        ),
    )


class TruncatedResponse(RuntimeError):
    """モデルが max_tokens に当たって応答を書き切れなかった。

    2026-08 まで、これが黙って通っていた。stop_reason を見ずに text ブロックを
    連結していたため、文の途中で切れた所見がそのまま配信され、
    セクション4・5が3週続けて欠落していた。
    """


def _call_model(system: str, user: str, model: str,
                max_tokens: int = INSIGHT_MAX_TOKENS) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    stop_reason = getattr(response, "stop_reason", None)
    usage = getattr(response, "usage", None)
    print(f"[ok] _call_model: stop_reason={stop_reason} "
          f"output_tokens={getattr(usage, 'output_tokens', '?')} "
          f"max_tokens={max_tokens} chars={len(text)}")
    if stop_reason == "max_tokens":
        raise TruncatedResponse(
            f"応答が max_tokens={max_tokens} で打ち切られました"
            f"(本文 {len(text)}字)"
        )
    return text


# --------------------------------------------------------------------------
# Deterministic fallback
# --------------------------------------------------------------------------
def _rate_line(label: str, series: Dict[str, Any], flat: int) -> str:
    """率の行。%と「ポイント」で書き、±flat 以内は「横ばい」(§B)。"""
    return (
        f"- {label}: {insight_style.rate_text(series.get('this_week'))}"
        f"(前週 {insight_style.rate_text(series.get('prev_week'))}、"
        f"{insight_style.points_text(series.get('delta'), flat)})"
    )


def _count_line(label: str, series: Dict[str, Any], unit: str = "件") -> str:
    """実数の行。率ではないので%にもポイントにもしない。"""
    line = (
        f"- {label}: {insight_style.count_text(series.get('this_week'), unit)}"
        f"(前週 {insight_style.count_text(series.get('prev_week'), unit)}、"
        f"{insight_style.count_delta_text(series.get('delta'), unit)})"
    )
    if series.get("noise_zone"):
        line += " ※母数が小さく判断できない水準"
    return line


def fallback_report(stats: Dict[str, Any],
                    thresholds: Optional[Dict[str, Any]] = None) -> str:
    """The same 5 sections, built from stats.json without the LLM (§5).

    Numbers only, no interpretation — an honest degraded report rather than a
    missing one.
    """
    flat = insight_style.flat_delta_points(
        thresholds if thresholds is not None else load_thresholds()
    )
    gloss = insight_style.pattern_gloss(
        thresholds if thresholds is not None else load_thresholds()
    )

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
    lines.append(_rate_line("言及率(全体)", rate.get("all", {}), flat))
    lines.append(_rate_line("言及率(Agentforce系(A))", rate.get("pillar_a", {}), flat))
    lines.append(_rate_line("言及率(Agentic CRM系(B))", rate.get("pillar_b", {}), flat))

    top = (stats.get("sov", {}).get("all", {}) or {}).get("entities") or []
    if top:
        head = top[0]
        lines.append(
            f"- 言及シェア首位: {head['entity']} "
            f"{insight_style.rate_text(head.get('share'))}"
            f"({insight_style.count_text(head.get('mention_count'))}、"
            f"{insight_style.count_delta_text(head.get('delta'))})"
        )
    kgi = stats.get("kgi", {})
    lines.append(_count_line("成果指標(KGI) AI経由セッション",
                             kgi.get("ai_sessions", {}), "セッション"))
    lines.append(_count_line("成果指標(KGI) 指名検索クリック",
                             kgi.get("branded_clicks", {}), "クリック"))
    lines.append("")

    lines += [f"## {_SECTIONS[2]}", ""]
    if fired:
        for rule in fired:
            rule_id = rule["rule_id"]
            note = gloss.get(rule_id)
            heading = f"**{rule_id}({note})**" if note else f"**{rule_id}**"
            lines.append(f"{heading}")
            lines.append(f"{insight_style.LABEL_STATE}: {rule.get('detail', '')}")
            lines.append("")
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
        floor = stats["kgi"].get("noise_floor")
        lines.append(
            f"- ノイズ域(週計 {insight_style.count_text(floor)} 未満)の指標: "
            f"{', '.join(noisy)} — 増減は判断材料にしない"
        )
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# 後処理(§A・§B)
# --------------------------------------------------------------------------
def _load_actions() -> List[Dict[str, Any]]:
    """action_log を読む。読めなくても所見の生成は止めない。

    施策記録が引けないのは「実施済みが分からない」だけで、
    今週の統計から所見を書くこと自体はできる。
    """
    try:
        import sheets_writer

        return list(sheets_writer.read_action_log())
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] action_log を読めませんでした({exc}) — 実施済みの除外は行いません")
        return []


def postprocess(report_md: str, stats: Dict[str, Any],
                actions: Sequence[Dict[str, Any]] = (),
                thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """記述ルールのうち、確定的に直せるものを当てる(§A・§B)。

    返り値は ``{"report_md", "suppressed", "warnings"}``。
    直せないもの(主語の省略、残った比喩)は warnings に積んで、
    ジョブサマリで見えるようにする。黙って直すより、直っていないことが
    分かるほうがよい。
    """
    thresholds = thresholds if thresholds is not None else load_thresholds()
    flat = insight_style.flat_delta_points(thresholds)
    gloss = insight_style.pattern_gloss(thresholds)

    text = insight_style.normalize_labels(report_md)
    text = insight_style.merge_co_fired(text, insight_style.co_fired_prompts(stats))

    import action_log

    text, suppressed = action_log.suppress_settled(text, actions)
    text = insight_style.apply_number_format(
        text, insight_style.number_replacements(stats, flat)
    )
    text = insight_style.gloss_first_mentions(text, gloss)

    warnings: List[str] = []
    for line, word, _ in insight_style.banned_words(text):
        warnings.append(f"禁止語「{word}」が {line}行目 に残っています")
    for line, value in insight_style.bare_decimals(text):
        warnings.append(f"小数の生値 {value} が {line}行目 に残っています")
    for line, _ in insight_style.arrows(text):
        warnings.append(f"矢印記法が {line}行目 に残っています")
    missing = [s for s in _SECTIONS if s.split(". ", 1)[1] not in text]
    if missing:
        warnings.append(f"セクションが欠落しています: {', '.join(missing)}")

    return {"report_md": text.strip(), "suppressed": suppressed, "warnings": warnings}


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def generate(stats: Dict[str, Any], model: Optional[str] = None,
             playbook: Optional[str] = None,
             actions: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return ``{"report_md", "source", "error", "suppressed", "warnings"}``.

    ``source`` is ``"llm"`` or ``"fallback"``. This never raises: a weekly
    report that fails to render is still delivered as numbers (§5).

    ``actions`` は action_log の行。``None`` ならシートから読む(§A)。
    """
    model = model or INSIGHT_MODEL
    actions = list(actions) if actions is not None else _load_actions()
    try:
        system = build_system_prompt(playbook)
        user = build_user_prompt(stats, actions)
        try:
            report = _call_model(system, user, model)
        except TruncatedResponse as exc:
            # 一度だけ枠を倍にして取り直す。切れた所見を配るくらいなら
            # もう1回呼ぶほうが安い(週1回の呼び出しなので)。
            print(f"[warn] {exc} — max_tokens を倍にして再試行します")
            report = _call_model(system, user, model, INSIGHT_MAX_TOKENS * 2)
        if not report.strip():
            raise RuntimeError("model returned an empty report")
        if len(report) > INSIGHT_MAX_CHARS * 2:
            # Well past the instructed limit — keep it, but say so.
            print(f"[warn] insight is {len(report)} chars, over the {INSIGHT_MAX_CHARS} target")
        result = postprocess(report, stats, actions)
        for warning in result["warnings"]:
            print(f"[warn] 記述ルール: {warning}")
        for note in result["suppressed"]:
            print(f"[ok] 実施済みのため再提案を差し替え: {note}")
        print(f"[ok] generate_insight: {len(result['report_md'])} chars via {model}")
        return {"report_md": result["report_md"], "source": "llm", "error": None,
                "suppressed": result["suppressed"], "warnings": result["warnings"]}
    except Exception as exc:  # noqa: BLE001 - degrade, never drop the report
        print(f"[warn] generate_insight failed ({exc}) — falling back to the numeric summary")
        return {"report_md": fallback_report(stats), "source": "fallback",
                "error": str(exc), "suppressed": [], "warnings": []}


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly insight generation (stage 2)")
    ap.add_argument("--stats", required=True, help="path to a stats.json produced by rules_engine")
    ap.add_argument("--model", help=f"override the model (default {INSIGHT_MODEL})")
    ap.add_argument("--fallback-only", action="store_true",
                    help="skip the API and print the deterministic report")
    ap.add_argument("--action-log", help="action_log のJSON(未指定ならシートから読む)")
    args = ap.parse_args()

    with open(args.stats, "r", encoding="utf-8") as fh:
        stats = json.load(fh)

    if args.fallback_only:
        print(fallback_report(stats))
        return

    actions = None
    if args.action_log:
        with open(args.action_log, "r", encoding="utf-8") as fh:
            actions = json.load(fh)
    print(generate(stats, args.model, actions=actions)["report_md"])


if __name__ == "__main__":
    main()
