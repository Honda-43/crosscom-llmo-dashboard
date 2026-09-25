"""interventions.py — 介入ログ(output/interventions.csv)を読む(2026-09-25).

観測の増減を読むときに「その週に何をしたか」を突き合わせるための記録。
ダッシュボードの折れ線(R2・R3)に縦線で注記し、週次レポートにも一覧を出す。

- 日付は JST。``2026-09-25〜`` のような継続の書き方も許す(開始日として読む)
- 日付が空の行は「日付が未確定」。縦線には出さず、未確定として別に見せる
  (0 や今日として描くと、線の位置が事実と違ってしまう)
- ``touches_pool46`` が yes の介入は 2x2 の処置と混ざる。判定ではその日を境に分ける
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from settings import ROOT_DIR

INTERVENTIONS_FILE = ROOT_DIR / "output" / "interventions.csv"
FIELDS = ["date", "intervention_id", "description", "scope", "executor", "touches_pool46"]
UNCONFIRMED = "要確認"
# 継続の介入("2026-09-25〜")は開始日を縦線にする。**末尾の印だけを見る** —
# "-" は ISO の日付(2026-09-25)の区切りにも出るので、含むかどうかで判定しない。
ONGOING_MARKS = ("〜", "~", "-")


def parse_date(text: Any) -> Optional[dt.date]:
    """日付欄を date にする。空欄・読めない値は None(縦線に出さない)。"""
    head = str(text or "").strip()[:11].rstrip("".join(ONGOING_MARKS))
    try:
        return dt.date.fromisoformat(head)
    except ValueError:
        return None


def load(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """介入ログ。``date`` に parse した日付、``ongoing`` に継続かどうかを足して返す。"""
    path = Path(path if path is not None else INTERVENTIONS_FILE)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    out = []
    for row in rows:
        raw = str(row.get("date") or "").strip()
        out.append(dict(row, raw_date=raw, date=parse_date(raw),
                        ongoing=raw.rstrip().endswith(ONGOING_MARKS)))
    return sorted(out, key=lambda r: (r["date"] is None, r["date"] or dt.date.max,
                                      r["intervention_id"]))


def dated(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """日付の分かっている介入(縦線に出せるもの)。"""
    return [r for r in (load() if rows is None else rows) if r["date"]]


def undated(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """日付が未確定の介入。縦線には出さないが、見落とさないよう別に出す。"""
    return [r for r in (load() if rows is None else rows) if not r["date"]]


def in_window(start: dt.date, end: dt.date,
              rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """``start``〜``end`` に実施した介入(継続は開始日で判定)。"""
    return [r for r in dated(rows) if start <= r["date"] <= end]


def label(row: Dict[str, Any]) -> str:
    """縦線の注釈と凡例に使う短い名前。"""
    return f"{row['intervention_id']}{'〜' if row.get('ongoing') else ''}"
