"""backfill_mentioned_v2.py — llm_experiment の mentioned_v2 を遡って埋める(2026-10-01).

mentioned(回答本文に「クロスコム」)は、英字表記(Cross-Com・CrossCom など)や中黒入り
(クロス・コム)を落としていた。表記ゆれを含めたルール(experiment.is_mentioned_v2)で、
2026-09-15 以降の全行を**保存されている answer_text から**数え直し、新しい列 mentioned_v2 に入れる。

- 元の mentioned 列は消さない・書き換えない
- 欠測(error のある行)は空欄(mentioned と同じ約束)
- answer_text がセルの上限で切れている行だけは raw_file の全文を使う
- **既定は下見**(違った行の件数と該当箇所を出すだけ)。--write でシートの mentioned_v2 列を書く

参考指標のため、2x2 の判定(cited_article)には影響しない。

usage:
  python src/backfill_mentioned_v2.py                 # 下見
  python src/backfill_mentioned_v2.py --write         # シートへ書く
  python src/backfill_mentioned_v2.py --report output/reports/mentioned_v2_backfill_20261001.md
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import experiment
from settings import ROOT_DIR, TAB_EXPERIMENT

FROM_DATE = "2026-09-15"
TRUNCATED_MARK = "…[続きは raw_file]"
CONTEXT = 20


def answer_of(row: Dict[str, Any], root: Path = ROOT_DIR) -> str:
    """数え直しに使う本文。セルで切れていれば raw_file の全文。"""
    text = str(row.get("answer_text") or "")
    if TRUNCATED_MARK in text and row.get("raw_file"):
        path = root / str(row["raw_file"])
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("answer") or text
    return text


def recount(row: Dict[str, Any], root: Path = ROOT_DIR) -> str:
    """その行の mentioned_v2(文字列)。対象外の日付は空、欠測も空。"""
    if str(row.get("date", ""))[:10] < FROM_DATE or str(row.get("error") or "").strip():
        return ""
    return str(experiment.is_mentioned_v2(answer_of(row, root)))


def snippets(text: str, width: int = CONTEXT) -> List[str]:
    """表記ゆれに当たった箇所の前後 width 字(NFKC 後の本文。改行は空白に)。"""
    norm = unicodedata.normalize("NFKC", text)
    out = []
    for start, end in experiment.mention_hits_v2(text):
        piece = norm[max(0, start - width):end + width].replace("\n", " ")
        out.append(f"…{piece}…")
    return out


def plan(rows: List[Dict[str, Any]], root: Path = ROOT_DIR) -> List[Dict[str, Any]]:
    """行ごとの (シートの行番号, 新しい値, 旧 mentioned, 違ったか, 該当箇所)。"""
    out = []
    for i, row in enumerate(rows, start=2):                  # 1行目は見出し
        new = recount(row, root)
        old = str(row.get("mentioned") or "").strip()
        out.append({"row": i, "date": str(row.get("date", ""))[:10],
                    "experiment_id": row.get("experiment_id", ""), "model": row.get("model", ""),
                    "mentioned": old, "mentioned_v2": new, "changed": old != new,
                    "snippets": snippets(answer_of(row, root)) if old != new else []})
    return out


def report(items: List[Dict[str, Any]]) -> str:
    target = [x for x in items if x["date"] >= FROM_DATE]
    changed = [x for x in target if x["changed"]]
    url_only = [x for x in changed
                if x["snippets"] and all("cross-com.jp" in s.casefold() for s in x["snippets"])]
    L = ["# mentioned_v2 の遡及再計算(2026-10-01)", "",
         f"- 対象: llm_experiment の {FROM_DATE} 以降 {len(target)}行"
         f"(欠測 {sum(1 for x in target if x['mentioned_v2'] == '')}行は空欄のまま)",
         f"- 新ルール: {' / '.join(experiment.MENTION_TERMS_V2)} のどれかを含めば 1"
         "(NFKC で全角半角、casefold で大文字小文字をそろえて照合)",
         f"- 旧 mentioned は残す。旧=1・新=1 {sum(1 for x in target if x['mentioned'] == x['mentioned_v2'] == '1')}行、"
         f"旧=0・新=0 {sum(1 for x in target if x['mentioned'] == x['mentioned_v2'] == '0')}行",
         f"- **mentioned と mentioned_v2 が違った行: {len(changed)}行**"
         f"(旧0→新1 {sum(1 for x in changed if x['mentioned'] == '0' and x['mentioned_v2'] == '1')}行・"
         f"旧1→新0 {sum(1 for x in changed if x['mentioned'] == '1' and x['mentioned_v2'] == '0')}行・"
         f"その他 {sum(1 for x in changed if (x['mentioned'], x['mentioned_v2']) not in (('0', '1'), ('1', '0')))}行)",
         f"  - うち、当たった箇所がすべて本文中の cross-com.jp の URL だけの行: {len(url_only)}行",
         "", "## 違った行", "",
         "| 行 | 日付 | ID | モデル | 旧 | 新 | 該当箇所(前後20字・NFKC 後) |", "|---|---|---|---|---|---|---|"]
    for x in changed:
        spots = "<br>".join(s.replace("|", "\\|") for s in x["snippets"]) or "—"
        L.append(f"| {x['row']} | {x['date']} | {x['experiment_id']} | {x['model']} | "
                 f"{x['mentioned'] or '空'} | {x['mentioned_v2'] or '空'} | {spots} |")
    return "\n".join(L) + "\n"


def write(items: List[Dict[str, Any]]) -> int:
    """シートの mentioned_v2 列だけを書く(見出しも足す)。"""
    import sheets_writer
    ss = sheets_writer._open_spreadsheet()
    ws = sheets_writer._ensure_worksheet(ss, TAB_EXPERIMENT, sheets_writer.HEADERS_EXPERIMENT)
    col = sheets_writer.HEADERS_EXPERIMENT.index("mentioned_v2")
    letter = ""
    n = col + 1
    while n:
        n, r = divmod(n - 1, 26)
        letter = chr(65 + r) + letter
    first, last = items[0]["row"], items[-1]["row"]
    ws.update(values=[[x["mentioned_v2"]] for x in items],
              range_name=f"{letter}{first}:{letter}{last}", value_input_option="RAW")
    return len(items)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="mentioned_v2 を answer_text から遡って埋める")
    ap.add_argument("--write", action="store_true", help="シートの mentioned_v2 列を書く")
    ap.add_argument("--report", help="違った行の一覧を Markdown で保存する")
    a = ap.parse_args(argv)

    import sheets_writer
    rows = sheets_writer._read_tab(TAB_EXPERIMENT)
    items = plan(rows)
    text = report(items)
    print(text)
    if a.report:
        path = Path(a.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"[ok] wrote {path}")
    if a.write:
        print(f"[ok] {TAB_EXPERIMENT}: mentioned_v2 を {write(items)}行 書いた")
    else:
        print("(下見。シートは書いていない。書くときは --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
