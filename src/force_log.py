"""force_log.py — 既にある出力を --force で置き換えたことを日誌に1行残す(2026-10-01).

観測の再実行・割付・ドリフトの基準は、既にあるものを置き換えるときは止まる。
--force を付けたときだけ置き換え、その事実と理由を実験日誌に自動で1行追記する。
日誌は追記のみ(tests/test_append_only_records.py)なので、ここも追記だけ。

experiment_2x2/ のスクリプトからも読むため、標準ライブラリだけで書く。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DIARY_FILE = ROOT / "output" / "reports" / "experiment47_diary.md"
JST = dt.timezone(dt.timedelta(hours=9), name="JST")


class ForceRequired(RuntimeError):
    """既にある出力を置き換えようとして止まった(--force と --reason が要る)。"""


def require_reason(force: bool, reason: Optional[str], what: str) -> str:
    """--force のときは理由を必須にする。理由の無い置き換えは記録として読めない。"""
    text = (reason or "").strip()
    if force and not text:
        raise ForceRequired(f"{what} を置き換えるには --reason \"理由\" が必要です")
    return text


def record(script: str, what: str, reason: str, detail: str = "",
           path: Optional[Path] = None, now: Optional[dt.datetime] = None) -> str:
    """日誌の末尾に1行足し、足した行を返す。"""
    path = Path(path) if path is not None else DIARY_FILE
    now = now or dt.datetime.now(JST)
    line = (f"- {now:%Y-%m-%d %H:%M} JST／**--force で置き換え**：{script} が {what} を置き換えた"
            f"（理由：{reason}）" + (f"。{detail}" if detail else "") + "（自動記録）")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(("" if not text or text.endswith("\n") else "\n") + "\n" + line + "\n")
    print(f"[diary] {line}")
    return line
