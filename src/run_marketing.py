"""run_marketing.py — 第3観測層 prompt_marketing の観測(2026-10-01).

54本(config/prompts_marketing.csv)を Gemini と Claude で月1回、毎月第1週に観測し、
llm_marketing タブと data/raw/marketing/<日付>/ に残す。llm_experiment には書かない。

Gemini(--model gemini。experiment.yml の実験の観測の**あと**に同じジョブで走る)
  - その日の Gemini の実消費(実験・日次・月次・その日の marketing。再試行込み)を先に数え、
    20 からの残りが3回以上の日だけ動かす。1本1回(再試行・掃き直しなし)で残りの本数まで。
    これで1日の合計は20を超えない
  - 日次・月次・実験の Gemini が揃っていない日は動かさない(数え漏れで20を超えないため)
  - 15:30 JST より後は投げない(Gemini の1日は太平洋時間で切り替わり、翌日の枠を食うため)
  - その月の実験の観測で 429 PerDay の欠測が1回でも出ていたら、その月の残りを止める
    (残りは error=quota_skipped。日誌 output/reports/experiment47_diary.md に1回だけ記録)
Claude(--model claude。marketing.yml)
  - Gemini の枠と無関係。期間の初日にまとめて回し、欠測は期間内の次の日に取り直す
期間(1〜14日)
  - 第1週(1〜7日)で終わらなければ第2週(8〜14日)まで延長。14日の回のあと(または15日以降の
    最初の回)に、終わっていないものを error=quota_skipped として記録する。翌月に持ち越さない
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import collect_llm
import marketing
import run_experiment
from settings import (DATA_RAW_EXPERIMENT_DIR, DATA_RAW_MARKETING_DIR, GEMINI_DAILY_REQUEST_LIMIT,
                      MARKETING_FIRST_MONTH, MARKETING_GEMINI_CUTOFF_JST,
                      MARKETING_WINDOW_LAST_DAY, ROOT_DIR,
                      experiment_plan, in_marketing_window, load_marketing_prompts,
                      marketing_gemini_allowance)

DIARY_FILE = ROOT_DIR / "output" / "reports" / "experiment47_diary.md"


# --------------------------------------------------------------------------
# その日の Gemini の実消費
# --------------------------------------------------------------------------
def _used(records: List[Dict[str, Any]]) -> int:
    return run_experiment.daily_gemini_used(records)


def experiment_gemini_records(date: str) -> List[Dict[str, Any]]:
    """その日の実験の Gemini raw。同じジョブの手元と origin で多いほう。"""
    return run_experiment._prefer_more(
        run_experiment._gemini_raw_from_origin(f"data/raw/experiment/{date}"),
        run_experiment._gemini_raw_local(DATA_RAW_EXPERIMENT_DIR / date))


def gemini_used_today(date: str,
                      experiment_records: Optional[List[Dict[str, Any]]] = None,
                      prior: Optional[List[Tuple[str, List[Dict[str, Any]], int]]] = None,
                      marketing_dir: Path = DATA_RAW_MARKETING_DIR) -> Tuple[Optional[int], str]:
    """(その日の Gemini の実消費, 説明)。先に走る観測が揃っていなければ (None, 理由)。

    数えるもの:日次・月次(揃っていること)・実験(計画した本数ぶんの raw があること)・
    その日すでに投げた marketing。どれも attempts(再試行込み)。
    """
    if prior is None:
        prior = [(label, fetch(date), expected)
                 for label, fetch, expected in run_experiment.prior_runs(date)]
    parts: Dict[str, int] = {}
    for label, recs, expected in prior:
        if not run_experiment.daily_is_done(recs, expected):
            return None, f"{label}の Gemini が揃っていない"
        parts[label] = _used(recs)
    planned = {p["id"] for p in experiment_plan(date).get("gemini") or []}
    exp = experiment_gemini_records(date) if experiment_records is None else experiment_records
    if planned - {r.get("prompt_id") for r in exp}:
        return None, "実験の Gemini が揃っていない"
    parts["実験"] = _used(exp)
    parts["marketing(同日)"] = _used(run_experiment._gemini_raw_local(marketing_dir / date))
    total = sum(parts.values())
    return total, " + ".join(f"{k}{v}" for k, v in parts.items()) + f" = {total}"


def before_cutoff(now: dt.datetime) -> bool:
    h, m = MARKETING_GEMINI_CUTOFF_JST
    local = now.astimezone(JST)
    return (local.hour, local.minute) < (h, m)


# --------------------------------------------------------------------------
# 観測・記録
# --------------------------------------------------------------------------
def observe(date: str, model: str, prompts: List[Dict[str, Any]], out_dir: Path,
            lister=None, resolver=None) -> List[Dict[str, Any]]:
    """観測して判定列を足す。Gemini は1本1回(再試行・掃き直しなし)。"""
    if not prompts:
        return []
    if model == "gemini":
        got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir, models=["gemini"],
                                  attempts=1, sweep=False, budget=collect_llm.RetryBudget(0))
    else:
        got = collect_llm.collect(date, prompts=prompts, out_dir=out_dir, models=[model])
    by_id = {p["id"]: p for p in prompts}
    for rec in got:
        if rec.get("reused") or rec.get("kept_existing"):
            continue        # 同じ日に成功した観測が既にある。判定列も raw も書き直さない
        rec.update(marketing.evaluate(rec, by_id[rec["prompt_id"]], resolver, lister))
        collect_llm._save(rec, out_dir)
    return got


def skip_rest(date: str, model: str, rest: List[Dict[str, Any]], out_dir: Path,
              detail: str = "") -> List[Dict[str, Any]]:
    """終わっていない分を error=quota_skipped として残す(翌月に持ち越さない)。"""
    name = collect_llm.MODEL_CONFIG[model]["model"]
    out = []
    for p in rest:
        rec = marketing.skipped_record(date, p, model, name, detail)
        collect_llm._save(rec, out_dir)
        out.append(rec)
    return out


def record_stop_in_diary(month: str, misses: List[str], skipped: int,
                         path: Path = DIARY_FILE) -> bool:
    """実験の PerDay 欠測で marketing を止めたことを日誌に1回だけ書く。書いたら True。"""
    marker = f"prompt_marketing（{month}）を停止"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in text:
        return False
    lines = ["", "---", "",
             f"## {dt.datetime.now(JST):%Y-%m-%d}／{marker}（自動記録）", "",
             f"- その月の実験の観測で 429 PerDay の欠測が出たため、Gemini の prompt_marketing の残り"
             f" {skipped}本を error=quota_skipped として記録し、今月はこれ以上投げない（run_marketing.py）",
             f"- 実験の PerDay 欠測: {'、'.join(misses[:10])}" + (" ほか" if len(misses) > 10 else ""),
             "- Claude の prompt_marketing は Gemini の枠と無関係のため止めない", ""]
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines))
    return True


def run_gemini(date: str, prompts: List[Dict[str, Any]], out_dir: Path,
               now: Optional[dt.datetime] = None, used: Optional[int] = None,
               used_note: str = "", lister=None,
               experiment_dir: Path = DATA_RAW_EXPERIMENT_DIR,
               diary: Path = DIARY_FILE) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Gemini の1日分。(記録したレコード, 要約の行)。``out_dir`` は <marketing の raw>/<日付>。"""
    month = marketing.month_of(date)
    root = out_dir.parent
    rest = marketing.pending(prompts, month, "gemini", root)
    day = dt.date.fromisoformat(date).day
    notes: List[str] = []
    if not rest:
        return [], [f"- Gemini: 今月の {len(prompts)}本は終わっている"]
    if day > MARKETING_WINDOW_LAST_DAY:
        recs = skip_rest(date, "gemini", rest, out_dir, "期間(1〜14日)内に終わらず")
        return recs, [f"- Gemini: 期間内に終わらなかった {len(recs)}本を quota_skipped として記録"]
    misses = marketing.experiment_perday_misses(month, experiment_dir)
    if misses:
        recs = skip_rest(date, "gemini", rest, out_dir, "実験の観測で PerDay の欠測が出たため今月は停止")
        if record_stop_in_diary(month, misses, len(recs), diary):
            notes.append("- 日誌に停止を記録した")
        return recs, [f"- Gemini: 実験の PerDay 欠測({len(misses)}件)のため今月の残り "
                      f"{len(recs)}本を停止(quota_skipped)"] + notes
    if not before_cutoff(now or dt.datetime.now(JST)):
        return [], ["- Gemini: 15:30 JST を過ぎたため投げない(翌日の枠を食うため)"]
    if used is None:
        return [], [f"- Gemini: 投げない({used_note})"]
    allowance = marketing_gemini_allowance(used)
    notes.append(f"- Gemini の実消費: {used_note} / 残り {GEMINI_DAILY_REQUEST_LIMIT - used}"
                 f" → marketing に使う本数 {allowance}")
    recs = observe(date, "gemini", rest[:allowance], out_dir, lister=lister)
    calls = _used(recs)
    assert used + calls <= GEMINI_DAILY_REQUEST_LIMIT, (used, calls)
    notes.append(f"- Gemini: {len(recs)}本を投げた(呼び出し {calls}回・1日の合計 {used + calls}/"
                 f"{GEMINI_DAILY_REQUEST_LIMIT})。今月の残り {len(rest) - len(recs)}本")
    if day == MARKETING_WINDOW_LAST_DAY:
        left = marketing.pending(prompts, month, "gemini", root)
        skipped = skip_rest(date, "gemini", left, out_dir, "期間(1〜14日)内に終わらず")
        recs += skipped
        if skipped:
            notes.append(f"- Gemini: 期間の最終日のため、残り {len(skipped)}本を quota_skipped として記録")
    return recs, notes


def run_claude(date: str, prompts: List[Dict[str, Any]], out_dir: Path,
               lister=None) -> Tuple[List[Dict[str, Any]], List[str]]:
    rest = marketing.pending(prompts, marketing.month_of(date), "claude", out_dir.parent)
    if not rest:
        return [], [f"- Claude: 今月の {len(prompts)}本は終わっている"]
    if dt.date.fromisoformat(date).day > MARKETING_WINDOW_LAST_DAY:
        recs = skip_rest(date, "claude", rest, out_dir, "期間(1〜14日)内に終わらず")
        return recs, [f"- Claude: 期間内に終わらなかった {len(recs)}本を quota_skipped として記録"]
    recs = observe(date, "claude", rest, out_dir, lister=lister)
    miss = sum(1 for r in recs if r.get("error"))
    return recs, [f"- Claude: {len(recs)}本(欠測 {miss}本。欠測は期間内の次の回に取り直す)"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="第3観測層 prompt_marketing")
    ap.add_argument("--model", choices=["gemini", "claude"], required=True)
    ap.add_argument("--date", help="観測日 YYYY-MM-DD(既定: 当日JST)")
    ap.add_argument("--no-sheets", action="store_true")
    a = ap.parse_args(argv)
    date = a.date or dt.datetime.now(JST).strftime("%Y-%m-%d")
    lines = [f"## prompt_marketing {date}({a.model})"]
    if marketing.month_of(date) < MARKETING_FIRST_MONTH:
        print("\n".join(lines + [f"- 初回の月({MARKETING_FIRST_MONTH})より前のため何もしない"]))
        return 0
    prompts = load_marketing_prompts()
    out_dir = DATA_RAW_MARKETING_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.model == "gemini":
        used, note = (None, "")
        if in_marketing_window(date):
            used, note = gemini_used_today(date)
        recs, notes = run_gemini(date, prompts, out_dir, used=used, used_note=note)
    else:
        recs, notes = run_claude(date, prompts, out_dir)
    lines += notes
    # 社名が出たのに順位が空の観測(Haiku の失敗)を、その月のうちに埋め直す(2026-10-03)。行は消さず同じ行を上書き
    refilled = marketing.refill_ranks(marketing.month_of(date))
    if refilled:
        lines.append(f"- 順位(mention_rank)を埋め直した観測: {len(refilled)}本"
                     f"({'・'.join(r['model'] + ' ' + r['prompt_id'] for r in refilled)})")
        recs = recs + refilled
    if recs and not a.no_sheets:
        import sheets_writer
        # 同じ日に成功した行は書き直さない(欠測や取り直しで置き換えない)
        sheets_writer.write_marketing(collect_llm.fresh(recs))
    if not any(out_dir.iterdir()):
        out_dir.rmdir()
    run_experiment._job_summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
