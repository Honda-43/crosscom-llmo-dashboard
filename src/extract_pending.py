"""extract_pending.py — Claude が使えない日の「抽出保留」を残し、後日まとめて抽出する(2026-10-06).

抽出(extract.py)は Claude(Haiku)で行う。2026-10-06 はクレジット切れで抽出が止まり、
Gemini の回答まで抽出されずに llm_observations へ空の行が入り、daily_summary の言及率が 0% になった
(実際は「分からない」)。モデル単位で切り分けるため、次のようにする:

- Claude を止めている日(claude_budget の credit_exhausted / daily_cap)の抽出は ``extract.PENDING`` の印が付く
- 保留した観測は data/extract_pending/<種類>_<日付>.json に残す(回答そのものは data/raw にある)。
  シートには書かず、その日の言及率・言及シェアの計算にも入れない(空の行・0% を書かない)
- Claude が使える日に ``catch_up()`` が raw を読み直して抽出し、シートに書く。日次は
  llm_observations の行と、その日の daily_summary の言及率・否定の件数、sov_daily を作り直す
  (changes は作り直さない。前回との差分は抽出したその日の観測で見る)。月次は monthly_observations に書く

種類は daily(日次・data/raw/<日付>)と monthly(月次・data/raw/monthly/<日付>)。実験は文字列照合なので抽出が無い。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import extract
from settings import DATA_RAW_DIR, DATA_RAW_MONTHLY_DIR, ROOT_DIR

PENDING_DIR = ROOT_DIR / "data" / "extract_pending"
KINDS = ("daily", "monthly")
RAW_DIRS = {"daily": DATA_RAW_DIR, "monthly": DATA_RAW_MONTHLY_DIR}


def _path(kind: str, date: str, root: Optional[Path] = None) -> Path:
    return Path(root or PENDING_DIR) / f"{kind}_{date}.json"


def _read(path: Path) -> List[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("pending", [])
    except (OSError, ValueError):
        return []


def _write(path: Path, kind: str, date: str, entries: List[Dict[str, Any]]) -> None:
    if not entries:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": kind, "date": date, "pending": entries},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split(extractions: List[Dict[str, Any]]):
    """(抽出できたもの, 抽出保留)。"""
    done = [e for e in extractions if not extract.is_pending(e)]
    return done, [e for e in extractions if extract.is_pending(e)]


def save(kind: str, date: str, pending: List[Dict[str, Any]], root: Optional[Path] = None) -> int:
    """抽出保留を台帳に足す(同じ prompt_id × model は1件)。台帳の件数を返す。"""
    if not pending:
        return len(_read(_path(kind, date, root)))
    path = _path(kind, date, root)
    entries = {(e["prompt_id"], e["model"]): e for e in _read(path)}
    now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    for rec in pending:
        key = (rec.get("prompt_id"), rec.get("model"))
        entries.setdefault(key, {"prompt_id": key[0], "model": key[1],
                                 "raw_file": rec.get("raw_file", ""), "since": now,
                                 "reason": str(rec.get("error") or "")[:300]})
    _write(path, kind, date, sorted(entries.values(), key=lambda e: (e["prompt_id"], e["model"])))
    return len(entries)


def pending_files(root: Optional[Path] = None) -> List[Path]:
    folder = Path(root or PENDING_DIR)
    return sorted(folder.glob("*.json")) if folder.exists() else []


def count(root: Optional[Path] = None) -> int:
    return sum(len(_read(p)) for p in pending_files(root))


def _load_raw(kind: str, date: str, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = RAW_DIRS[kind] / date / f"{entry['prompt_id']}_{entry['model']}.json"
    if not path.exists() and entry.get("raw_file"):
        path = ROOT_DIR / entry["raw_file"]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# 後日まとめて抽出する
# --------------------------------------------------------------------------
def _rewrite_daily(date: str, done: List[Dict[str, Any]], writer: Any) -> None:
    """日次:llm_observations に書き、その日の daily_summary の言及率と sov_daily を作り直す。"""
    import looker_tabs
    writer.write_llm_observations(done)
    fresh = {(e["prompt_id"], e["model"]): writer._llm_row(e) for e in done}
    rows = [r for r in writer.read_llm_observations()
            if str(r.get("date", ""))[:10] == date and (r.get("prompt_id"), r.get("model")) not in fresh]
    rows += list(fresh.values())
    summary = looker_tabs.summary_rows_from_observations(rows)
    if summary:
        stored = next((r for r in writer.read_daily_summary() if str(r.get("date", ""))[:10] == date), {})
        row = dict(stored, date=date)
        for key in ("mention_rate_all", "mention_rate_pillar_a", "mention_rate_pillar_b"):
            row[key] = summary[0].get(key)
        row["negative_flag_count"] = sum(
            1 for r in rows if str(r.get("negative_or_outdated", "")).strip().upper() == "TRUE"
            or r.get("negative_or_outdated") is True)
        writer.write_daily_summary(row)
    writer.write_sov_daily(looker_tabs.sov_rows_from_observations(rows, since=date, until=date))


def _rewrite_monthly(date: str, done: List[Dict[str, Any]], raws: Dict[tuple, Dict[str, Any]],
                     writer: Any) -> None:
    for e in done:
        src = raws.get((e.get("prompt_id"), e.get("model")), {})
        e.setdefault("category", src.get("category", ""))
        e.setdefault("target_brand", src.get("target_brand", ""))
    writer.write_monthly_observations(done)


def catch_up(writer: Any = None, root: Optional[Path] = None,
             extractor: Callable[[Dict[str, Any]], Dict[str, Any]] = None,
             log: Callable[..., None] = print) -> Dict[str, int]:
    """台帳の観測を抽出してシートに書く。{'done': 書いた件数, 'left': 残った件数}。

    Claude がまだ止まっていれば(抽出がまた保留になれば)そこでやめ、台帳は残す。
    raw が見つからない観測は台帳に残す(消さない)。
    """
    if writer is None:
        import sheets_writer as writer  # noqa: N813 - シートに書くのは実行時だけ
    extractor = extractor or extract.extract_record
    written = 0
    for path in pending_files(root):
        meta = json.loads(path.read_text(encoding="utf-8"))
        kind, date = meta["kind"], meta["date"]
        entries = meta.get("pending", [])
        done, left, raws, stopped = [], [], {}, False
        for entry in entries:
            if stopped:
                left.append(entry)
                continue
            raw = _load_raw(kind, date, entry)
            if raw is None:
                log(f"[warn] 抽出保留 {kind} {date} {entry['prompt_id']}/{entry['model']}: raw が見つからない")
                left.append(entry)
                continue
            got = extractor(raw)
            if extract.is_pending(got):
                stopped = True                    # Claude はまだ止まっている
                left.append(entry)
                continue
            raws[(entry["prompt_id"], entry["model"])] = raw
            done.append(got)
        if done:
            if kind == "daily":
                _rewrite_daily(date, done, writer)
            else:
                _rewrite_monthly(date, done, raws, writer)
            written += len(done)
            log(f"[ok] 抽出保留を抽出した: {kind} {date} {len(done)}件")
        _write(path, kind, date, left)
        if stopped:
            break
    return {"done": written, "left": count(root)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="抽出保留の観測を後日まとめて抽出する")
    ap.add_argument("--list", action="store_true", help="台帳を表示するだけ")
    a = ap.parse_args(argv)
    if a.list:
        for p in pending_files():
            print(f"{p.name}: {len(_read(p))}件")
        return 0
    import claude_budget
    claude_budget.start("extract_catch_up")
    got = catch_up()
    print(f"抽出 {got['done']}件・残り {got['left']}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
