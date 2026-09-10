"""format_looker_sheets.py — シートで直接読むタブに書式を当てる(Phase 7).

Looker に載せる前に、スプレッドシートをそのまま読むことがある。既定の書式だと
1行目が流れていき、長文の列が1行に潰れて中身が見えない。ここでその2つを直す。

当てる書式:
  - 1行目を固定(スクロールしても見出しが残る)
  - フィルタ表示ON(列ごとの絞り込みができる)
  - 長文の列は折り返し + 列幅を広げる
  - date を降順に並べる(最新が上)

値の入れ替え(``ws.clear()`` + ``update``)では書式・固定行・フィルタは消えない
ので、タブを作り直したときだけ実行すればよい。何度実行しても同じ状態になる。

使い方(リポジトリ直下から)::

    python scripts/format_looker_sheets.py            # 書式を当てて gid を表示
    python scripts/format_looker_sheets.py --show     # 何もせず gid だけ表示
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import sheets_writer  # noqa: E402
from settings import SHEET_ID, TAB_LK_ANSWERS, TAB_LK_ANSWERS_PIVOT  # noqa: E402

# 列幅(ピクセル)。指定のない列は既定のまま。
MEDIUM, WIDE, VERY_WIDE = 130, 300, 460

# lk_answers。読む順に「いつ・何を」を狭く、長文を広く。
ANSWERS_WIDTHS: Dict[str, int] = {
    "date": 95, "short_label": 200, "prompt_id": 80, "model": 80,
    "service_line": 165, "intent_stage": 80, "funnel": 70,
    "mention": 70, "rank": 60, "competitors": WIDE, "cited_urls": WIDE,
    "prompt_text": WIDE, "answer_head": VERY_WIDE, "answer_text": VERY_WIDE,
}
# 折り返す列。ここ以外は1行に収める(折り返すと行が伸びて一覧性が落ちる)。
ANSWERS_WRAP = ("competitors", "cited_urls", "prompt_text", "answer_head",
                "answer_text")

PIVOT_LABEL_WIDTHS = {"short_label": 200, "model": 90}
PIVOT_CELL_WIDTH = 320


def _sheet_id(ss, title: str) -> Optional[int]:
    try:
        return ss.worksheet(title).id
    except Exception:  # noqa: BLE001 - タブ未作成なら書式も要らない
        return None


def tab_url(gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={gid}"


def _freeze(gid: int, rows: int = 1, cols: int = 0) -> Dict[str, Any]:
    grid: Dict[str, Any] = {"frozenRowCount": rows}
    fields = "gridProperties.frozenRowCount"
    if cols:
        grid["frozenColumnCount"] = cols
        fields += ",gridProperties.frozenColumnCount"
    return {"updateSheetProperties": {
        "properties": {"sheetId": gid, "gridProperties": grid},
        "fields": fields,
    }}


def _width(gid: int, index: int, pixels: int) -> Dict[str, Any]:
    return {"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "COLUMNS",
                  "startIndex": index, "endIndex": index + 1},
        "properties": {"pixelSize": pixels},
        "fields": "pixelSize",
    }}


def _wrap(gid: int, index: int, strategy: str) -> Dict[str, Any]:
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": index, "endColumnIndex": index + 1},
        "cell": {"userEnteredFormat": {"wrapStrategy": strategy,
                                       "verticalAlignment": "TOP"}},
        "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment",
    }}


def _header_style(gid: int, columns: int) -> Dict[str, Any]:
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": columns},
        "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.94, "green": 0.95, "blue": 0.96},
            "verticalAlignment": "MIDDLE",
        }},
        "fields": ("userEnteredFormat.textFormat.bold,"
                   "userEnteredFormat.backgroundColor,"
                   "userEnteredFormat.verticalAlignment"),
    }}


def answers_requests(gid: int, headers: List[str]) -> List[Dict[str, Any]]:
    """lk_answers の書式。date 降順の並び替えはフィルタ側に持たせる。"""
    requests: List[Dict[str, Any]] = [
        _freeze(gid, rows=1),
        _header_style(gid, len(headers)),
        # 既存のフィルタを外してから、date 降順で付け直す。
        {"clearBasicFilter": {"sheetId": gid}},
        {"setBasicFilter": {"filter": {
            "range": {"sheetId": gid, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "sortSpecs": [{"dimensionIndex": headers.index("date"),
                           "sortOrder": "DESCENDING"}],
        }}},
    ]
    for index, name in enumerate(headers):
        requests.append(_width(gid, index, ANSWERS_WIDTHS.get(name, MEDIUM)))
        requests.append(_wrap(gid, index,
                              "WRAP" if name in ANSWERS_WRAP else "CLIP"))
    return requests


def pivot_requests(gid: int, columns: int) -> List[Dict[str, Any]]:
    """lk_answers_pivot の書式。左2列(プロンプト・モデル)を固定する。

    列が日付ぶん横に伸びるので、行の見出しが流れると何の行か分からなくなる。
    """
    requests: List[Dict[str, Any]] = [
        _freeze(gid, rows=1, cols=2),
        _header_style(gid, columns),
        {"clearBasicFilter": {"sheetId": gid}},
        {"setBasicFilter": {"filter": {
            "range": {"sheetId": gid, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": columns},
        }}},
        _width(gid, 0, PIVOT_LABEL_WIDTHS["short_label"]),
        _width(gid, 1, PIVOT_LABEL_WIDTHS["model"]),
    ]
    for index in range(2, columns):
        requests.append(_width(gid, index, PIVOT_CELL_WIDTH))
    for index in range(columns):
        requests.append(_wrap(gid, index, "WRAP" if index >= 2 else "CLIP"))
    return requests


def apply(show_only: bool = False) -> Dict[str, Optional[int]]:
    ss = sheets_writer._open_spreadsheet()
    gids = {title: _sheet_id(ss, title)
            for title in (TAB_LK_ANSWERS, TAB_LK_ANSWERS_PIVOT)}

    if not show_only:
        requests: List[Dict[str, Any]] = []
        if gids[TAB_LK_ANSWERS] is not None:
            requests += answers_requests(gids[TAB_LK_ANSWERS],
                                         sheets_writer.HEADERS_LK_ANSWERS)
        if gids[TAB_LK_ANSWERS_PIVOT] is not None:
            columns = len(ss.worksheet(TAB_LK_ANSWERS_PIVOT).row_values(1)) or 2
            requests += pivot_requests(gids[TAB_LK_ANSWERS_PIVOT], columns)
        if requests:
            ss.batch_update({"requests": requests})
            print(f"[ok] 書式を当てました({len(requests)} requests)")

    for title, gid in gids.items():
        print(f"{title}: gid={gid}  {tab_url(gid) if gid is not None else '(タブなし)'}")
    return gids


def main() -> None:
    ap = argparse.ArgumentParser(description="Looker用タブの書式を当てる")
    ap.add_argument("--show", action="store_true", help="書式を当てず gid だけ表示")
    args = ap.parse_args()
    apply(show_only=args.show)


if __name__ == "__main__":
    main()
