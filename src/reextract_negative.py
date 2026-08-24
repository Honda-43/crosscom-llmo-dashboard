"""reextract_negative.py — 判定基準の変更（2026-08-24）に伴う再抽出。

2026-08-24、negative_or_outdated の判定基準を事業3区分ベースに精緻化した
（extract.py のモジュール docstring を参照）。今回の変更は「true になる範囲を
狭める」方向のみなので、**再判定が必要なのは既に true のレコードだけ**である。
false のレコードが新たに true になることはない。

そのため本スクリプトは llm_observations タブの
``negative_or_outdated == TRUE`` の行だけを対象に、data/raw に保存済みの
生回答を新しいプロンプトで再抽出し、判定が変わった行を書き戻す。

**書き戻すのは negative_or_outdated と negative_detail の2列だけ。**
mention / rank / kbf_tags などは再抽出結果で上書きしない。抽出は決定的では
ないため、それらまで書き換えると「基準変更による差分」と「モデルの揺らぎ」が
混ざって、変更の効果が測れなくなる。

    # 対象の確認だけ（APIも書き込みも無し）
    .\\.venv\\Scripts\\python.exe src\\reextract_negative.py --dry-run

    # 再抽出して書き戻す
    $env:ANTHROPIC_API_KEY = "..."
    $env:SHEETS_SPREADSHEET_ID = (Get-Content credentials\\spreadsheet_id.txt)
    $env:GOOGLE_APPLICATION_CREDENTIALS = "credentials\\service_account.json"
    .\\.venv\\Scripts\\python.exe src\\reextract_negative.py

    # 再抽出はするがシートには書かない（結果だけ見る）
    .\\.venv\\Scripts\\python.exe src\\reextract_negative.py --no-write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import sheets_writer  # noqa: E402
from settings import DATA_RAW_DIR, TAB_LLM, TAB_SUMMARY  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"

# 基準を変更した日。レポートに残し、効果測定の解釈で参照できるようにする。
CRITERIA_CHANGE_DATE = "2026-08-24"


def _is_true(cell: str) -> bool:
    return str(cell).strip().upper() == "TRUE"


def raw_path(row: Dict[str, str]) -> Path:
    """シート1行に対応する data/raw の生回答ファイル。

    raw_file 列が入っていればそれを優先し、空なら
    data/raw/<date>/<prompt_id>_<model>.json という保存規約から組み立てる。
    """
    stored = (row.get("raw_file") or "").strip()
    if stored:
        p = Path(stored)
        if not p.is_absolute():
            p = REPORT_DIR.parent.parent / stored
        if p.exists():
            return p
    return DATA_RAW_DIR / row["date"] / f"{row['prompt_id']}_{row['model']}.json"


def collect_targets(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """再判定の対象（現在 TRUE の行）を、日付昇順で返す。"""
    targets = [r for r in rows if _is_true(r.get("negative_or_outdated", ""))]
    targets.sort(key=lambda r: (r.get("date", ""), r.get("prompt_id", ""), r.get("model", "")))
    return targets


def daily_counts(rows: List[Dict[str, str]]) -> Counter:
    """日付ごとの negative TRUE 件数。"""
    return Counter(r["date"] for r in rows if _is_true(r.get("negative_or_outdated", "")))


def observed_dates(rows: List[Dict[str, str]]) -> List[str]:
    return sorted({r["date"] for r in rows if r.get("date")})


def reextract_one(row: Dict[str, str]) -> Dict[str, Any]:
    """1行を再抽出する。生ファイルが無い場合は missing を返す。"""
    path = raw_path(row)
    key = f"{row['date']} {row['prompt_id']}/{row['model']}"
    if not path.exists():
        return {"key": key, "row": row, "status": "missing_raw", "path": str(path)}

    with open(path, "r", encoding="utf-8") as fh:
        record = json.load(fh)
    result = extract.extract_record(record)
    if result.get("error"):
        return {"key": key, "row": row, "status": "error", "error": result["error"]}

    after = bool(result.get("negative_or_outdated"))
    return {
        "key": key,
        "row": row,
        "status": "ok",
        "before": True,               # 対象は定義上すべて TRUE
        "after": after,
        "changed": after is False,    # TRUE -> FALSE のみ起こりうる
        "detail_before": row.get("negative_detail", ""),
        "detail_after": result.get("negative_detail"),
    }


def patch_rows(rows: List[Dict[str, str]], changed_keys: set) -> List[Dict[str, Any]]:
    """判定が変わった行だけを、2列だけ差し替えた upsert 用の行にする。"""
    patched: List[Dict[str, Any]] = []
    for row in rows:
        key = (row.get("date"), row.get("prompt_id"), row.get("model"))
        if key not in changed_keys:
            continue
        new_row = dict(row)
        new_row["negative_or_outdated"] = "FALSE"
        new_row["negative_detail"] = ""
        patched.append({h: new_row.get(h, "") for h in sheets_writer.HEADERS_LLM})
    return patched


def changed_keys_from_results(results: List[Dict[str, Any]]) -> set:
    return {
        (r["row"]["date"], r["row"]["prompt_id"], r["row"]["model"])
        for r in results if r["status"] == "ok" and r["changed"]
    }


def write_back(changed_keys: set, after: Counter) -> None:
    """llm_observations の2列と daily_summary.negative_flag_count を書き戻す。"""
    rows = sheets_writer.read_llm_observations()
    ss = sheets_writer._open_spreadsheet()
    patched = patch_rows(rows, changed_keys)
    if patched:
        sheets_writer._upsert(ss, TAB_LLM, sheets_writer.HEADERS_LLM,
                              sheets_writer.KEYS_LLM, patched)
    summary_patch = patch_summary(after)
    if summary_patch:
        sheets_writer._upsert(ss, TAB_SUMMARY, sheets_writer.HEADERS_SUMMARY,
                              sheets_writer.KEYS_SUMMARY, summary_patch)
    print(f"[ok] シート更新: llm_observations {len(patched)} 行 / "
          f"daily_summary {len(summary_patch)} 行")


def patch_summary(after_counts: Counter) -> List[Dict[str, Any]]:
    """daily_summary の negative_flag_count だけを差し替えた行を作る。

    他の列（mention_rate 等）は再計算せず、シートの値をそのまま持ち回る。
    """
    summary_rows = sheets_writer._read_tab(TAB_SUMMARY)
    patched: List[Dict[str, Any]] = []
    for row in summary_rows:
        date = row.get("date")
        if not date:
            continue
        new_count = str(after_counts.get(date, 0))
        if str(row.get("negative_flag_count", "")).strip() == new_count:
            continue
        new_row = dict(row)
        new_row["negative_flag_count"] = new_count
        patched.append({h: new_row.get(h, "") for h in sheets_writer.HEADERS_SUMMARY})
    return patched


def print_calendar(dates: List[str], before: Counter, after: Counter) -> None:
    print("\n=== negative_flag の日次推移（before → after） ===")
    print(f"{'date':<12} {'before':>7} {'after':>7}   {'変化':<6}")
    print("-" * 44)
    for d in dates:
        b, a = before.get(d, 0), after.get(d, 0)
        if b == a:
            mark = "" if b == 0 else "変化なし"
        elif a == 0:
            mark = "★消滅"
        else:
            mark = f"-{b - a}"
        print(f"{d:<12} {b:>7} {a:>7}   {mark:<6}")
    fired_b = sum(1 for d in dates if before.get(d, 0) > 0)
    fired_a = sum(1 for d in dates if after.get(d, 0) > 0)
    print("-" * 44)
    print(f"{'発火日数':<12} {fired_b:>7} {fired_a:>7}   / 観測 {len(dates)} 日")
    print(f"{'合計件数':<12} {sum(before.values()):>7} {sum(after.values()):>7}")


def main() -> None:
    ap = argparse.ArgumentParser(description="negative_or_outdated=TRUE の行を再抽出する")
    ap.add_argument("--dry-run", action="store_true",
                    help="対象の確認のみ。APIを呼ばず、シートにも書かない")
    ap.add_argument("--no-write", action="store_true",
                    help="再抽出はするが、シートには書き戻さない")
    ap.add_argument("--limit", type=int, help="先頭N件だけ処理する（動作確認用）")
    ap.add_argument("--from-report", metavar="PATH",
                    help="保存済みレポートJSONの結果をシートへ書き戻す（再抽出しない）。"
                         "書き込みだけが失敗したときの再開用。APIは呼ばない")
    args = ap.parse_args()

    if args.from_report:
        with open(args.from_report, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        keys = {(c["date"], c["prompt_id"], c["model"]) for c in report["changed_rows"]}
        after = Counter({d: int(n) for d, n in report["daily_after"].items()})
        print(f"レポート: {args.from_report}")
        print(f"  再抽出日     : {report['run_date']}")
        print(f"  TRUE→FALSE   : {len(keys)} 件")
        for k in sorted(keys):
            print(f"    - {k[0]} {k[1]}/{k[2]}")
        if not keys:
            print("書き戻す変更はありません。")
            return
        write_back(keys, after)
        return

    rows = sheets_writer.read_llm_observations()
    if not rows:
        print("[error] llm_observations が読めませんでした。認証と SHEETS_SPREADSHEET_ID を確認してください。")
        raise SystemExit(2)

    dates = observed_dates(rows)
    before = daily_counts(rows)
    targets = collect_targets(rows)

    print(f"llm_observations: {len(rows)} 行 / 観測日 {len(dates)} 日"
          f"（{dates[0]} 〜 {dates[-1]}）")
    print(f"再判定の対象（現在 TRUE）: {len(targets)} 行\n")

    print("=== 対象の内訳 ===")
    by_date = Counter(r["date"] for r in targets)
    by_prompt = Counter(r["prompt_id"] for r in targets)
    by_model = Counter(r["model"] for r in targets)
    print("  日付別:", ", ".join(f"{d}:{n}" for d, n in sorted(by_date.items())))
    print("  prompt別:", ", ".join(f"{p}:{n}" for p, n in by_prompt.most_common()))
    print("  model別:", ", ".join(f"{m}:{n}" for m, n in by_model.most_common()))

    missing = [r for r in targets if not raw_path(r).exists()]
    print(f"\n  生ファイル: {len(targets) - len(missing)}/{len(targets)} 件が data/raw に存在")
    for r in missing:
        print(f"    [missing] {r['date']} {r['prompt_id']}/{r['model']} -> {raw_path(r)}")

    if args.dry_run:
        print("\n--dry-run のため、ここで終了します（APIも書き込みも実行していません）。")
        print_calendar(dates, before, before)
        return

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\n[error] ANTHROPIC_API_KEY が未設定です。docstring の手順で渡してください。")
        raise SystemExit(2)

    work = targets[: args.limit] if args.limit else targets
    print(f"\n=== 再抽出（{len(work)} 件・モデル {extract.EXTRACT_MODEL}） ===")
    results: List[Dict[str, Any]] = []
    for i, row in enumerate(work, 1):
        res = reextract_one(row)
        results.append(res)
        if res["status"] != "ok":
            print(f"  [{i:>3}/{len(work)}] {res['key']}: {res['status']}")
            continue
        mark = "TRUE  -> FALSE  ★変化" if res["changed"] else "TRUE  -> TRUE   維持"
        print(f"  [{i:>3}/{len(work)}] {res['key']}: {mark}")

    ok = [r for r in results if r["status"] == "ok"]
    changed = [r for r in ok if r["changed"]]
    kept = [r for r in ok if not r["changed"]]
    failed = [r for r in results if r["status"] != "ok"]

    print("\n=== 集計 ===")
    print(f"  再抽出成功 : {len(ok)} 件")
    print(f"  TRUE→FALSE : {len(changed)} 件（誤検知だったもの）")
    print(f"  TRUE のまま : {len(kept)} 件（実態としてネガ）")
    print(f"  失敗       : {len(failed)} 件")

    after = Counter(before)
    for r in changed:
        after[r["row"]["date"]] -= 1
    print_calendar(dates, before, after)

    report = {
        "run_date": dt.datetime.now().strftime("%Y-%m-%d"),
        "criteria_change_date": CRITERIA_CHANGE_DATE,
        "scope": "negative_or_outdated == TRUE のみ再抽出（false→true は構造上起こらない）",
        "written_columns": ["negative_or_outdated", "negative_detail"],
        "targets": len(targets),
        "reextracted": len(ok),
        "changed_true_to_false": len(changed),
        "kept_true": len(kept),
        "failed": [{"key": r["key"], "status": r["status"],
                    "error": r.get("error"), "path": r.get("path")} for r in failed],
        "daily_before": dict(sorted(before.items())),
        "daily_after": {d: after.get(d, 0) for d in sorted(after)},
        "changed_rows": [
            {"date": r["row"]["date"], "prompt_id": r["row"]["prompt_id"],
             "model": r["row"]["model"], "detail_before": r["detail_before"]}
            for r in changed
        ],
        "kept_rows": [
            {"date": r["row"]["date"], "prompt_id": r["row"]["prompt_id"],
             "model": r["row"]["model"], "detail_after": r["detail_after"]}
            for r in kept
        ],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"reextract_negative_{report['run_date']}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"\n[ok] レポート: {out}")

    if args.no_write:
        print("--no-write のため、シートには書き戻していません。")
        return
    if not changed:
        print("判定が変わった行はありません。シートへの書き戻しは不要です。")
        return

    try:
        write_back(changed_keys_from_results(results), after)
    except Exception as exc:  # noqa: BLE001
        # 再抽出は成功してレポートに残っているので、APIを再消費せずに再開できる。
        print(f"\n[error] シートへの書き戻しに失敗しました: {exc}")
        print("再抽出の結果はレポートに保存済みです。権限を直したあと、次で書き戻せます:")
        print(f"  python src/reextract_negative.py --from-report {out}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
