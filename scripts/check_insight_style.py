"""check_insight_style.py — 出来上がった週次所見が記述ルールを満たすか調べる.

`generate_insight.postprocess` は所見を作るときに warnings を出すが、それは
その場限りで、あとから「先週の所見はルールを満たしていたか」を確かめる手段が
なかった。ここでは**シートに保存済みの所見**(または手元のファイル)を読んで、
同じ検査を後からかけ直す。

検査する6つ:

1. 禁止語   — 比喩を使っていないか(insight_style.BANNED_WORDS)
2. 箇条書き — 発火パターンの項目が「状態 / 原因仮説 / 推奨アクション」の
              3行になっているか。矢印記法が残っていないか
3. 実施済み抑制 — 打ってある施策が推奨アクションとして再提案されていないか
4. 統合見出し   — 同一プロンプトの R-P2 と R-P15 が1項目にまとまっているか
5. 表記        — 小数の生値が残っていないか。5セクションが揃っているか
6. rule_id の説明 — 各 rule_id に日本語の定義が併記されているか

判定は OK / NG / —(その週は該当なし)。NG が1つでもあれば終了コード1。

使い方(リポジトリ直下から)::

    python scripts/check_insight_style.py --date 2026-09-07
    python scripts/check_insight_style.py --file path/to/report.md --stats path/to/stats.json

``--date`` はシートの weekly_reports から読む。``--file`` は手元のファイル。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import insight_style  # noqa: E402
import verdicts  # noqa: E402
from settings import DATA_REPORTS_DIR, load_yaml, RULES_THRESHOLDS_FILE  # noqa: E402

OK, NG, SKIP = "OK", "NG", "—"


def _blocks(text: str) -> List[Tuple[str, List[str]]]:
    """発火パターン1項目ぶんの (見出し, 行) を返す。"""
    lines = text.splitlines()
    out: List[Tuple[str, List[str]]] = []
    start: Optional[int] = None
    for index, line in enumerate(lines + ["## END"]):
        head = line.strip()
        is_head = bool(re.match(r"^\*\*.*R-(?:P\d+|DROP).*\*\*\s*$", head))
        if start is not None and (is_head or head.startswith("#")):
            out.append((lines[start].strip(), lines[start + 1:index]))
            start = None
        if is_head:
            start = index
    return out


def check_banned_words(text: str) -> Tuple[str, List[str]]:
    hits = insight_style.banned_words(text)
    return (OK if not hits else NG,
            [f"{line}行目「{word}」: {body[:60]}" for line, word, body in hits])


# フォールバック(LLMを使わない数値だけの所見)が自分で名乗る文言。
# フォールバックは推奨アクションを書かない設計なので、3行の検査はかけない。
FALLBACK_MARK = "推奨アクションは含まれません"


def check_bullets(text: str) -> Tuple[str, List[str]]:
    """各項目が3行の箇条書きになっているか。矢印記法が残っていないか。"""
    notes: List[str] = []
    if FALLBACK_MARK in text:
        return SKIP, ["フォールバック(数値のみ)の所見。推奨アクションを書かない設計"]
    blocks = _blocks(text)
    if not blocks:
        return SKIP, ["発火パターンの項目が見つかりません(発火0件の週)"]
    for head, body in blocks:
        joined = "\n".join(body)
        missing = [label for label in insight_style.PATTERN_LABELS
                   if f"{label}:" not in joined]
        if missing:
            notes.append(f"{head[:40]}: {', '.join(missing)} が無い")
    for line, body in insight_style.arrows(text):
        notes.append(f"{line}行目に矢印記法: {body[:60]}")
    return (OK if not notes else NG, notes)


def check_suppression(text: str,
                      actions: Sequence[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """打ってある施策が推奨アクションとして再提案されていないか。

    「実施済み(A-00N・日付)」に差し替わっていれば抑制が効いている。
    差し替わっておらず、同じ面に同じ根拠の実施済みがあるなら NG。
    """
    settled = {
        (str(r.get("根拠rule_id", "")).strip(), str(r.get("対象", "")).strip()):
            str(r.get("action_id", "")).strip()
        for r in actions
        if str(r.get("状態", "")).strip() in verdicts.IMPLEMENTED_STATUSES
        and str(r.get("根拠rule_id", "")).strip()
    }
    if not settled:
        return SKIP, ["実施済みの施策がありません"]

    replaced = len(re.findall(r"実施済み\(A-\d+", text))
    notes = [f"「実施済み(A-…)」への差し替え {replaced}件"]
    status = OK

    for head, body in _blocks(text):
        rule_ids = set(re.findall(r"R-(?:P\d+|DROP)", head))
        action_line = insight_style._label_line(body, insight_style.LABEL_ACTION)
        if not action_line or "実施済み(" in action_line:
            continue
        for (rule_id, target), action_id in settled.items():
            if rule_id in rule_ids and target and target in "".join(body):
                notes.append(
                    f"{head[:40]}: {rule_id}×{target} は {action_id} で実施済みだが"
                    f"推奨アクションが差し替わっていない")
                status = NG
    return status, notes


def check_merged_heading(text: str, stats: Dict[str, Any]) -> Tuple[str, List[str]]:
    """同一プロンプトで R-P2 と R-P15 が同時発火したら1項目にまとまっているか。"""
    prompts = insight_style.co_fired_prompts(stats)
    if not prompts:
        return SKIP, ["R-P2 と R-P15 の同時発火がありません"]
    notes, status = [], OK
    for prompt_id in prompts:
        merged = [h for h, _ in _blocks(text)
                  if "R-P2" in h and "R-P15" in h and prompt_id in h]
        if merged:
            notes.append(f"{prompt_id}: 統合済み — {merged[0][:60]}")
        else:
            notes.append(f"{prompt_id}: R-P2 と R-P15 が別項目のまま")
            status = NG
    return status, notes


def check_notation(text: str) -> Tuple[str, List[str]]:
    notes = [f"{line}行目に小数の生値 {value}"
             for line, value in insight_style.bare_decimals(text)]
    import generate_insight

    missing = [s for s in generate_insight._SECTIONS
               if s.split(". ", 1)[1] not in text]
    if missing:
        notes.append(f"セクション欠落: {', '.join(missing)}")
    return (OK if not notes else NG, notes)


def check_glossary(text: str) -> Tuple[str, List[str]]:
    """rule_id に日本語の定義が併記されているか。

    「初出に付ける」は挿入の手順であって、読み手にとっての条件は
    **本文のどこかに定義がある**こと。要約行の「発火パターン 2件(R-P7, R-P2)」
    のような列挙は説明の場ではないので、そこに定義が無いことは欠落としない。
    """
    gloss = insight_style.pattern_gloss(load_yaml(RULES_THRESHOLDS_FILE))
    notes, status = [], OK
    for rule_id in sorted({m.group(0) for m in re.finditer(r"R-(?:P\d+|DROP)", text)}):
        if rule_id not in gloss:
            continue
        annotated = any(
            text[m.end():m.end() + 1] in ("(", "（")
            or (text[max(0, m.start() - 1):m.start()] in ("(", "（")
                and text[m.end():m.end() + 1] in (")", "）"))
            for m in re.finditer(re.escape(rule_id), text)
        )
        notes.append(f"{rule_id}: {'説明あり' if annotated else '説明なし'}")
        if not annotated:
            status = NG
    return (status if notes else SKIP, notes or ["rule_id が本文にありません"])


def run(text: str, stats: Dict[str, Any],
        actions: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[str, List[str]]]:
    return {
        "1. 禁止語": check_banned_words(text),
        "2. 箇条書き(3行 + 矢印なし)": check_bullets(text),
        "3. 実施済み抑制": check_suppression(text, actions),
        "4. 統合見出し(R-P2×R-P15)": check_merged_heading(text, stats),
        "5. 表記(小数・セクション)": check_notation(text),
        "6. rule_id の説明": check_glossary(text),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="週次所見が記述ルールを満たすか調べる")
    ap.add_argument("--date", help="weekly_reports から読む週(YYYY-MM-DD)")
    ap.add_argument("--file", help="所見のファイル(--date の代わり)")
    ap.add_argument("--stats", help="stats.json(既定は data/reports/<date>.json)")
    args = ap.parse_args()

    import sheets_writer

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        date = args.date or ""
    elif args.date:
        rows = sheets_writer._read_tab("weekly_reports")
        match = [r for r in rows if str(r.get("date", "")).strip() == args.date]
        if not match:
            raise SystemExit(f"weekly_reports に {args.date} がありません")
        text, date = match[0].get("report_md", ""), args.date
    else:
        raise SystemExit("--date か --file のどちらかを指定してください")

    stats_path = Path(args.stats) if args.stats else DATA_REPORTS_DIR / f"{date}.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}
    if not stats:
        print(f"[warn] stats が読めません({stats_path}) — 統合見出しの検査は飛ばします")

    try:
        actions = sheets_writer.read_action_log()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] action_log を読めません({exc}) — 抑制の検査は飛ばします")
        actions = []

    print(f"# 週次所見の記述ルール検査 — {date or args.file}")
    print(f"本文 {len(text)}字 / 発火 {', '.join(stats.get('fired_rules') or []) or 'なし'}\n")

    results = run(text, stats, actions)
    failed = 0
    for name, (status, notes) in results.items():
        print(f"[{status}] {name}")
        for note in notes:
            print(f"      {note}")
        if status == NG:
            failed += 1
    print(f"\n判定: {len(results) - failed}/{len(results)} 項目 OK"
          + (f" / NG {failed}件" if failed else " — すべて満たしています"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
