"""backfill_experiment_sheet.py — data/raw/experiment からシート(llm_experiment)へ書き戻す(2026-10-07).

観測は data/raw に先に保存し、シートへの書き込みはそのあと(run_experiment)。ジョブが途中で止まる・シートが
読めない(403)などで、raw はあるのにシートに行が無い観測ができる。ここでは:

- raw はあるのにシートに無い観測だけを書く(既にある行は書き直さない・消さない。upsert の鍵は date・experiment_id・model)。
  判定列(cited_article など)が raw に無ければ、run_experiment と同じ experiment.evaluate で付ける
- 計画したのに raw も無い観測(本当に欠けた観測)は、理由を付けた欠測の行として raw・シート・実験日誌に残す
  (--unobserved-reason。計画は settings.experiment_plan で日付から決まる)

使い方:
  python backfill_experiment_sheet.py --date 2026-10-05 --dry-run
  python backfill_experiment_sheet.py --date 2026-10-05 --unobserved-reason "job_timeout: …"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import collect_llm
import experiment
from settings import DATA_RAW_EXPERIMENT_DIR, experiment_plan, load_observation_prompts

Key = Tuple[str, str, str]


def sheet_keys(rows: Iterable[Dict[str, Any]]) -> Set[Key]:
    return {(str(r.get("date", ""))[:10], str(r.get("experiment_id", "")), str(r.get("model", "")))
            for r in rows}


def missing_from_sheet(date: str, existing: Set[Key], raw_dir: Path = DATA_RAW_EXPERIMENT_DIR,
                       resolver=None) -> List[Dict[str, Any]]:
    """raw はあるのにシートに無い観測(判定列を付けたもの)。"""
    prompts = {p["id"]: p for p in load_observation_prompts()}
    out = []
    for f in sorted((raw_dir / date).glob("*.json")) if (raw_dir / date).exists() else []:
        rec = json.loads(f.read_text(encoding="utf-8"))
        key = (date, rec.get("prompt_id"), rec.get("model"))
        if key in existing or rec.get("prompt_id") not in prompts:
            continue
        if "cited_article" not in rec:
            rec.update(experiment.evaluate(rec, prompts[rec["prompt_id"]], resolver))
        rec.setdefault("raw_file", f"data/raw/experiment/{date}/{f.name}")
        out.append(rec)
    return out


def unobserved(date: str, reason: str, raw_dir: Path = DATA_RAW_EXPERIMENT_DIR) -> List[Dict[str, Any]]:
    """計画したのに raw が無い観測を、理由つきの欠測レコードにする(投げていないので attempts=0)。"""
    out = []
    for model, prompts in experiment_plan(date).items():
        for p in prompts:
            if (raw_dir / date / f"{p['id']}_{model}.json").exists():
                continue
            rec = {"date": date, "prompt_id": p["id"], "pillar": p.get("pillar", ""), "category": "",
                   "target_brand": "", "model": model, "model_name": collect_llm.MODEL_CONFIG[model]["model"],
                   "question": p["text"], "cep": p.get("cep"),
                   "timestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                   "answer": None, "cited_urls": [], "error": reason, "miss_reason": "skipped", "attempts": 0}
            rec.update(experiment.evaluate(rec, p))
            out.append(rec)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="data/raw/experiment から llm_experiment へ書き戻す")
    ap.add_argument("--date", required=True, action="append")
    ap.add_argument("--unobserved-reason", default="", help="計画したのに raw が無い観測を、この理由の欠測として残す")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    import run_experiment
    import sheets_writer
    from settings import TAB_EXPERIMENT
    existing = sheet_keys(sheets_writer._read_tab(TAB_EXPERIMENT))
    for date in a.date:
        fill = missing_from_sheet(date, existing)
        gone = unobserved(date, a.unobserved_reason) if a.unobserved_reason else []
        unresolved = sum(int(r.get("unresolved_redirects") or 0) for r in fill)
        print(f"{date}: raw からの書き戻し {len(fill)}行(解決できなかったリダイレクト {unresolved}件)・"
              f"本当に欠けた観測 {len(gone)}行")
        for r in fill + gone:
            print(f"  {r['model']} {r['prompt_id']} cited_article={r.get('cited_article')} error={str(r.get('error') or '')[:40]}")
        if a.dry_run:
            continue
        out_dir = DATA_RAW_EXPERIMENT_DIR / date
        for r in gone:
            collect_llm._save(r, out_dir)
        if gone:
            run_experiment.write_journal(date, fill + gone)   # その日の欠測を入れ替える(書き戻した観測の欠測も含める)
        sheets_writer.write_experiment(fill + gone)
    return 0


if __name__ == "__main__":
    sys.exit(main())
