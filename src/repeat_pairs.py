"""repeat_pairs.py — 意図的な反復測定ペアの食い違いを数える(2026-10-10・本田さん決定)。

日次・月次・第3観測層には、4軸(質問の型・What・Who・評価軸)が同じ質問が4組ある
(output/reports/prompt_overlap_2026-10-10.md)。統合は見送り、**同じ質問の揺れ幅を知るための
反復測定ペア**として残す(M-12 と PM-L2-05 は一字一句同じなのに、1日違いで結果が分かれた)。
**将来の整理で統合しないこと。**

週次サマリに、直近4週で各ペアの結果が食い違った回数を1行で出す。
  - 比べるのは「クロスコムへの言及の有無」(experiment.is_mentioned_v2。実験と同じ判定)。
    Gemini の引用 URL は転送用の URL で、解決にネットワークが要るため比べない
  - 同じモデルどうしで、観測の少ない側の1回ごとに、相手の観測のうち日付が最も近いもの(±7日以内)と組にする
  - 窓は週次の実行日の前日までの28日
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from experiment import is_mentioned_v2
from settings import DATA_RAW_DIR, DATA_RAW_MARKETING_DIR, DATA_RAW_MONTHLY_DIR

# (組, [(質問A, 質問B), ...])。G1 は3本なので3通りの組を比べる
REPEAT_PAIRS: Sequence[Tuple[str, Sequence[Tuple[str, str]]]] = (
    ("G1", (("A-1", "M-10"), ("M-10", "PM-L0-01"), ("A-1", "PM-L0-01"))),
    ("G2", (("M-12", "PM-L2-05"),)),
    ("G3", (("M-3", "PM-BS-02"),)),
    ("G4", (("M-4", "PM-BS-10"),)),
)
WINDOW_DAYS = 28
MAX_GAP_DAYS = 7


def _layer_dir(prompt_id: str, raw_dir: Path) -> Path:
    if prompt_id.startswith("PM-"):
        return raw_dir / "marketing"
    if prompt_id.startswith("M-"):
        return raw_dir / "monthly"
    return raw_dir


def observations(prompt_id: str, start: dt.date, end: dt.date,
                 raw_dir: Optional[Path] = None) -> Dict[str, List[Tuple[dt.date, int]]]:
    """{モデル: [(日付, 言及 0/1)]}。答えが取れた回だけ(error がある回・答えが空の回は数えない)。"""
    base = _layer_dir(prompt_id, Path(raw_dir) if raw_dir is not None else DATA_RAW_DIR)
    out: Dict[str, List[Tuple[dt.date, int]]] = {}
    if not base.exists():
        return out
    for day_dir in sorted(base.iterdir()):
        try:
            day = dt.date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        for f in day_dir.glob(f"{prompt_id}_*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if rec.get("prompt_id") != prompt_id or str(rec.get("error") or "") not in ("", "None"):
                continue
            if not rec.get("answer"):
                continue
            out.setdefault(rec.get("model", ""), []).append((day, is_mentioned_v2(rec["answer"])))
    return out


def compare(a: Dict[str, List[Tuple[dt.date, int]]],
            b: Dict[str, List[Tuple[dt.date, int]]]) -> Tuple[int, int]:
    """(比べた回数, 食い違った回数)。"""
    n = k = 0
    for model in set(a) & set(b):
        few, many = sorted((a[model], b[model]), key=len)
        for day, hit in few:
            near = min(many, key=lambda x: abs((x[0] - day).days))
            if abs((near[0] - day).days) > MAX_GAP_DAYS:
                continue
            n += 1
            k += int(near[1] != hit)
    return n, k


def window(date: str) -> Tuple[dt.date, dt.date]:
    end = dt.date.fromisoformat(str(date)[:10]) - dt.timedelta(days=1)
    return end - dt.timedelta(days=WINDOW_DAYS - 1), end


def weekly_line(date: str, raw_dir: Optional[Path] = None) -> str:
    start, end = window(date)
    cache: Dict[str, Dict[str, List[Tuple[dt.date, int]]]] = {}

    def obs(pid: str):
        if pid not in cache:
            cache[pid] = observations(pid, start, end, raw_dir)
        return cache[pid]

    total_n = total_k = 0
    parts = []
    for group, pairs in REPEAT_PAIRS:
        n = k = 0
        for x, y in pairs:
            pn, pk = compare(obs(x), obs(y))
            n, k = n + pn, k + pk
        total_n, total_k = total_n + n, total_k + k
        parts.append(f"{group} {k}/{n}")
    head = f"- 反復測定ペアの食い違い(直近4週 {start:%m/%d}〜{end:%m/%d}・言及の有無)"
    if total_n == 0:
        return f"{head}: 比べられる回なし(ペアの両方が観測された回が無い)"
    return f"{head}: {total_n}回中{total_k}回({'・'.join(parts)})"
