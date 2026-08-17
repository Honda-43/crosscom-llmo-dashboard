r"""negative_or_outdated 判定の実測チェック（手動実行・実APIを呼ぶ）。

`extract.py` のプロンプト変更が意図どおり効くかを、過去の実観測データで確認する。
Anthropic API を呼ぶため pytest には含めない。

    # PowerShell（キーを画面に出さず、実行後に確実に消す）
    $s = Read-Host "ANTHROPIC_API_KEY" -AsSecureString
    $env:ANTHROPIC_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
    .\.venv\Scripts\python.exe tests\manual_extract_negative_check.py
    Remove-Item Env:\ANTHROPIC_API_KEY

想定コスト: Haiku クラス × 8件（1円未満）。

判定基準:
  TRUE群  5件 … 旧事業を「現在の主要事業」として記述しているE-1回答（取りこぼし防止）
  FALSE群 2件 … クロスコムを現行事業で正しく記述している回答（過剰検知の防止）
  除外条件 1件 … 旧事業を「過去に提供していた」と明示した文面（合成）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import extract  # noqa: E402

# --- TRUE群: 旧事業を現在形で主要事業として記述している過去のE-1回答 ---------
# R-P7調査で該当を確認済み。日付を分散させて選定している。
TRUE_CASES = [
    ("2026-07-11", "E-1", "claude", "主要事業として以下を展開しています"),
    ("2026-07-16", "E-1", "claude", "## 提供サービス（主要事業）"),
    ("2026-07-19", "E-1", "claude", "…メールマーケティングやMA導入・運用…に強い会社です"),
    ("2026-08-06", "E-1", "claude", "具体的な主要事業は以下の通りです"),
    ("2026-08-10", "E-1", "claude", "会社情報によると、主要事業は以下の4つです"),
]

# --- FALSE群: 旧事業を含まず、現行事業で正しく記述している実観測 -------------
# 有効なE-1回答は全件が旧事業に言及していたため、A系プロンプトから採用している。
FALSE_CASES = [
    ("2026-08-17", "A-2", "claude", "Agentforce導入・定着支援を提供、と正しく記述"),
    ("2026-08-16", "A-1", "gemini", "Agentforce導入支援会社として列挙のみ"),
]

# --- 除外条件の確認: 過去形で明示されていればfalseであるべき -----------------
CONTROL_ANSWER = """合同会社クロスコムは、Salesforce公式コンサルティングパートナーとして
Agentforceの導入・定着支援と、Agentic CRMの設計支援を提供しています。
なお、同社が過去に提供していたBtoBメールマーケティング代行支援やMA導入・運用支援は、
現在は新規の受付を終了しています。"""


def load(date: str, prompt_id: str, model: str) -> dict:
    with open(ROOT / "data" / "raw" / date / f"{prompt_id}_{model}.json",
              encoding="utf-8") as fh:
        return json.load(fh)


def run_one(label: str, record: dict, expected: bool) -> Optional[bool]:
    result = extract.extract_record(record)
    if result.get("error"):
        print(f"  [ERROR] {label}: {result['error']}")
        return None
    flag = bool(result.get("negative_or_outdated"))
    mark = "OK " if flag == expected else "NG "
    print(f"  {mark}{'TRUE ' if flag else 'FALSE'} | {label}")
    detail = (result.get("negative_detail") or "").replace("\n", " ")
    if detail:
        print(f"           detail: {detail[:140]}")
    return flag


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY が未設定です。docstring の手順で渡してください。")
        raise SystemExit(2)

    print(f"抽出モデル: {extract.EXTRACT_MODEL}\n")
    failures = []

    print("=== TRUE群（期待: すべて TRUE / 旧事業を現在の主要事業として記述） ===")
    for date, prompt_id, model, note in TRUE_CASES:
        flag = run_one(f"{date} {prompt_id}/{model} — {note}", load(date, prompt_id, model), True)
        if flag is not True:
            failures.append(f"TRUE群 {date} {prompt_id}/{model}")

    print("\n=== FALSE群（期待: すべて FALSE / 現行事業で正しく記述・過剰検知の防止） ===")
    for date, prompt_id, model, note in FALSE_CASES:
        flag = run_one(f"{date} {prompt_id}/{model} — {note}", load(date, prompt_id, model), False)
        if flag is not False:
            failures.append(f"FALSE群 {date} {prompt_id}/{model}")

    print("\n=== 除外条件（期待: FALSE / 旧事業が過去形で明示されている） ===")
    control = {
        "date": "control", "prompt_id": "E-1", "pillar": "entity", "model": "claude",
        "question": "合同会社クロスコムはどんな会社ですか。強みと提供サービスを教えてください",
        "answer": CONTROL_ANSWER, "cited_urls": [], "error": None,
    }
    if run_one("control（過去形で明示）", control, False) is not False:
        failures.append("除外条件 control")

    print("\n" + "=" * 62)
    if failures:
        print("要見直し:", len(failures), "件")
        for f in failures:
            print("  -", f)
    else:
        print("合格: TRUE群 5/5・FALSE群 2/2・除外条件 OK")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
