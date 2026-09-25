"""experiment_weekly.py — LLMO効果測定実験の週次集計(2026-09-22).

毎週月曜に weekly.yml から呼ばれ、前の週(月〜日)の llm_experiment を集計して
``output/reports/experiment47_weekN_YYYYMMDD.md`` に書く。N は 9/15 の週を1とした週番号、
日付は生成日(月曜)。ファイル名の「47」は記録の連番を揃えるためで、中身はプール46本。

何を数えるか
- 記事ごと・モデルごと: 観測回数 / cited_article=1 / cited_domain=1 / 欠測
- 全体: cited_article の率・cited_domain の率(モデル別。分母は欠測を除いた観測)、
  記事URLが1回でも出た記事の本数
- Gemini の1日あたり呼び出し数(日次・月次・実験。data/raw の attempts、再試行込み)と、
  欠測の理由(枠切れ・503・投げずに記録)
- mentioned(回答本文に社名)は参考欄に回す。社名は記事の引用が無くても出るので、
  処置(リード・FAQ)の効果とは別の指標として読む

プールに無い記事(9/22 に除外した E37 など)の行は数えない。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import interventions
from settings import (DATA_RAW_DIR, DATA_RAW_EXPERIMENT_DIR, DATA_RAW_MONTHLY_DIR, ROOT_DIR,
                      TAB_EXPERIMENT, WEEKDAY_LABELS, load_experiment_prompts)

REPORTS_DIR = ROOT_DIR / "output" / "reports"
# 週番号の起点。9/15(火)〜9/21(月)を手で集計した回が1週目。自動の回は月〜日で切る。
WEEK1_MONDAY = dt.date(2026, 9, 14)
# 処置の反映(9/29〜30)と、判定に使わない反映後1週間(README の運用)
TREATMENT_FROM = dt.date(2026, 9, 29)
TREATMENT_LAG_UNTIL = dt.date(2026, 10, 7)
GEMINI_DAILY_LIMIT = 20


def week_window(report_date: dt.date) -> Tuple[dt.date, dt.date]:
    """生成日(月曜)の前の月〜日。"""
    end = report_date - dt.timedelta(days=1)
    return end - dt.timedelta(days=6), end


def week_number(report_date: dt.date) -> int:
    """9/15 の週を1とした週番号(9/28 生成 → 2)。"""
    start, _ = week_window(report_date)
    return (start - WEEK1_MONDAY).days // 7 + 1


def report_path(report_date: dt.date) -> Path:
    return REPORTS_DIR / f"experiment47_week{week_number(report_date)}_{report_date:%Y%m%d}.md"


def _flag(value: Any) -> bool:
    return str(value).strip() == "1"


def miss_reason(error: Any) -> str:
    """欠測の理由(シートには理由列が無いので error 文から戻す)。"""
    text = str(error or "").strip()
    if not text:
        return ""
    if text.startswith("skipped"):
        return "skipped"
    import collect_llm
    return collect_llm.miss_reason(text)


def _gemini_calls(folder: Path) -> Tuple[int, bool]:
    """フォルダの Gemini raw の呼び出し回数と、attempts が全件そろっていたか。"""
    if not folder.exists():
        return 0, True
    recs = [json.loads(f.read_text(encoding="utf-8")) for f in folder.glob("*_gemini.json")]
    exact = all("attempts" in r for r in recs)
    return sum(int(r.get("attempts") or 1) for r in recs), exact


def _phase(start: dt.date, end: dt.date) -> str:
    if end < TREATMENT_FROM:
        return "ビフォー(処置反映 9/29〜30 より前)"
    if start <= TREATMENT_LAG_UNTIL:
        return "処置反映・反映ラグの期間(判定には使わない)"
    return "アフター"


def build(report_date: dt.date, rows: Iterable[Dict[str, Any]],
          pool: Optional[List[Dict[str, Any]]] = None,
          raw_dir: Path = DATA_RAW_DIR, experiment_dir: Path = DATA_RAW_EXPERIMENT_DIR,
          monthly_dir: Path = DATA_RAW_MONTHLY_DIR,
          intervention_rows: Optional[List[Dict[str, Any]]] = None) -> str:
    """週次集計の Markdown を返す。"""
    pool = pool if pool is not None else load_experiment_prompts()
    pool_ids = [p["id"] for p in pool]
    meta = {p["id"]: (p.get("layer", ""), p["url"].rstrip("/").rsplit("/", 1)[-1]) for p in pool}
    start, end = week_window(report_date)
    s, e = start.isoformat(), end.isoformat()
    in_week = [r for r in rows if s <= str(r.get("date", ""))[:10] <= e]
    wk = [r for r in in_week if r.get("experiment_id") in meta]
    dropped = len(in_week) - len(wk)
    missing = lambda r: bool(str(r.get("error") or "").strip())      # noqa: E731

    n = week_number(report_date)
    L = [f"# LLMO効果測定実験 {n}週目の集計({s}〜{e})", "",
         f"- 生成日: {report_date.isoformat()}(自動・毎週月曜) / 出典: Google Sheets "
         f"`llm_experiment`(同期間 {len(wk)}行)",
         f"- 期間の区分: {_phase(start, end)}",
         f"- 対象: プール{len(pool_ids)}本(config/prompts_experiment.csv)"
         + (f"。プール外の記事の行 {dropped}件は数えていない" if dropped else ""),
         "- 率の分母は観測できた回数(欠測を除く)",
         "- Gemini の呼び出し回数は `data/raw` の `attempts`(再試行込み)。"
         "attempts の無い raw がある日は下限(≥)で示す"]
    if n == 2:
        L.append("- 1週目(手集計)は 9/15(火)〜9/21(月) で切ったため、9/21 は1週目と重なる")
    L.append("")

    # ---- 1. 全体 -----------------------------------------------------------
    L += ["## 1. 全体", "",
          "| モデル | 観測行 | 欠測 | 有効観測 | cited_article=1 | 記事引用率 | "
          "cited_domain=1 | ドメイン引用率 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for model in ("gemini", "claude"):
        rs = [r for r in wk if r.get("model") == model]
        ok = [r for r in rs if not missing(r)]
        art = sum(_flag(r.get("cited_article")) for r in ok)
        dom = sum(_flag(r.get("cited_domain")) for r in ok)
        rate = (lambda k: f"{k / len(ok):.1%}" if ok else "—")
        L.append(f"| {model.capitalize()} | {len(rs)} | {len(rs) - len(ok)} | {len(ok)} | "
                 f"{art} | {rate(art)} | {dom} | {rate(dom)} |")
    L.append("")
    hit = lambda model, col: {r["experiment_id"] for r in wk        # noqa: E731
                              if (model is None or r.get("model") == model)
                              and not missing(r) and _flag(r.get(col))}
    arts_any, arts_g, arts_c = hit(None, "cited_article"), hit("gemini", "cited_article"), \
        hit("claude", "cited_article")
    order = lambda ids: sorted(ids, key=pool_ids.index)              # noqa: E731
    L.append(f"- **記事URLが1回でも出た記事: {len(arts_any)}本 / {len(pool_ids)}本**"
             f"(Gemini {len(arts_g)}本・Claude {len(arts_c)}本・両方 {len(arts_g & arts_c)}本)")
    if arts_any:
        L.append("  - " + "、".join(f"{i}({meta[i][1]})" for i in order(arts_any)))
    dom_any = hit(None, "cited_domain")
    L.append(f"- cross-com.jp のどれかのURLが1回でも出た記事: {len(dom_any)}本 / {len(pool_ids)}本")
    unobserved = [i for i in pool_ids
                  if not any(r["experiment_id"] == i and r.get("model") == "gemini"
                             and not missing(r) for r in wk)]
    if unobserved:
        L.append(f"- Gemini の有効観測が0回の記事: {len(unobserved)}本({'、'.join(unobserved)})")
    L.append("")

    # ---- 2. Gemini の呼び出しと欠測 ------------------------------------------
    L += ["## 2. Gemini の1日あたり呼び出し数と欠測", "",
          "| 日付 | 曜 | 日次 | 月次 | 実験 | 合計 / 20 | 実験の欠測 | 枠切れ | 503 | 投げずに記録 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    totals = collections.Counter()
    day = start
    while day <= end:
        d = day.isoformat()
        calls = [_gemini_calls(raw_dir / d), _gemini_calls(monthly_dir / d),
                 _gemini_calls(experiment_dir / d)]
        fmt = lambda c: f"{c[0]}" if c[1] else f"≥{c[0]}"            # noqa: E731
        exact = all(c[1] for c in calls)
        total = sum(c[0] for c in calls)
        misses = [miss_reason(r.get("error")) for r in wk
                  if str(r.get("date", ""))[:10] == d and r.get("model") == "gemini"
                  and missing(r)]
        reasons = collections.Counter(misses)
        totals.update(reasons)
        L.append(f"| {d} | {WEEKDAY_LABELS[day.weekday()]} | {fmt(calls[0])} | {fmt(calls[1])} | "
                 f"{fmt(calls[2])} | {total if exact else f'≥{total}'}"
                 f"{' ⚠️' if total > GEMINI_DAILY_LIMIT else ''} | {len(misses)} | "
                 f"{reasons['quota']} | {reasons['unavailable']} | {reasons['skipped']} |")
        day += dt.timedelta(days=1)
    L += ["",
          f"- 実験 Gemini の欠測の内訳: 枠切れ(429){totals['quota']}件・503 {totals['unavailable']}件・"
          f"投げずに記録(日次・月次の実消費で枠が足りない日){totals['skipped']}件"
          + (f"・その他 {sum(totals.values()) - totals['quota'] - totals['unavailable'] - totals['skipped']}件"
             if sum(totals.values()) > totals['quota'] + totals['unavailable'] + totals['skipped']
             else ""),
          "- 合計には 429 で拒否された回も含む(投げた回数であり、枠を消費した回数ではない)", ""]

    # ---- 3. 記事ごと ---------------------------------------------------------
    per: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in wk:
        m, c = r["model"], per[r["experiment_id"]]
        c[f"{m}_n"] += 1
        if missing(r):
            c[f"{m}_miss"] += 1
        else:
            c[f"{m}_art"] += _flag(r.get("cited_article"))
            c[f"{m}_dom"] += _flag(r.get("cited_domain"))
            c[f"{m}_men"] += _flag(r.get("mentioned"))
    L += ["## 3. 記事ごと", "",
          "「観測」は観測行数(欠測を含む)、「記事」は cited_article=1、「ドメイン」は cited_domain=1 の回数。",
          "",
          "| ID | 層 | 記事 | Gemini 観測 | 記事 | ドメイン | 欠測 | Claude 観測 | 記事 | ドメイン | 欠測 |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for i in pool_ids:
        c = per[i]
        L.append(f"| {i} | {meta[i][0]} | {meta[i][1]} | {c['gemini_n']} | {c['gemini_art']} | "
                 f"{c['gemini_dom']} | {c['gemini_miss']} | {c['claude_n']} | {c['claude_art']} | "
                 f"{c['claude_dom']} | {c['claude_miss']} |")
    L.append("")

    # ---- 4. 介入 -------------------------------------------------------------
    # 数字の増減を「処置の効果」と読む前に、その週に何をしたかを並べる。
    # 日付が未確定の介入は、いつの週に効いたか分からないので毎回末尾に出す。
    known = interventions.load() if intervention_rows is None else list(intervention_rows)
    this_week = interventions.in_window(start, end, known)
    pending = interventions.undated(known)
    L += ["## 4. この週の介入(output/interventions.csv)", ""]
    if this_week:
        L += ["| 日付 | ID | 内容 | 範囲 | プール46本に触れる |", "|---|---|---|---|---|"]
        for row in this_week:
            L.append(f"| {row['raw_date']} | {row['intervention_id']} | {row['description']} | "
                     f"{row['scope']} | {row['touches_pool46']} |")
        if any(str(r.get("touches_pool46")) == "yes" for r in this_week):
            L.append("")
            L.append("- **プール46本に触れる介入がこの週にある。** 引用率の変化を 2x2 の処置だけの"
                     "効果として読まない")
    else:
        L.append("この週に実施した介入はない(日付の分かっているもの)。")
    if pending:
        L += ["", "日付が未確定の介入(どの週に効いたか分からない):"]
        L += [f"- {r['intervention_id']} {r['description']}({r['scope']}・{r['executor']})"
              for r in pending]
    L.append("")

    # ---- 5. 参考: mentioned -------------------------------------------------
    L += ["## 5. 参考:回答本文の社名言及(mentioned)", "",
          "社名は記事が引用されなくても出るため、処置の効果の判定には使わない。"
          "ブランド想起の目安として並べる。", ""]
    for model in ("gemini", "claude"):
        ok = [r for r in wk if r.get("model") == model and not missing(r)]
        men = [r["experiment_id"] for r in ok if _flag(r.get("mentioned"))]
        rate = f"{len(men) / len(ok):.1%}" if ok else "—"
        L.append(f"- {model.capitalize()}: {len(men)} / {len(ok)}({rate})"
                 + (f" — {'、'.join(order(set(men)))}" if men else ""))
    L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="LLMO実験の週次集計")
    ap.add_argument("--date", help="生成日 YYYY-MM-DD(既定: 当日JST)。前の月〜日を集計する")
    ap.add_argument("--print", action="store_true", help="書き出したあと本文を表示する")
    args = ap.parse_args()
    report_date = (dt.date.fromisoformat(args.date) if args.date
                   else dt.datetime.now(JST).date())

    import sheets_writer
    rows = sheets_writer._read_tab(TAB_EXPERIMENT)
    text = build(report_date, rows)
    path = report_path(report_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"[ok] wrote {path}")
    if args.print:
        print(text)


if __name__ == "__main__":
    main()
