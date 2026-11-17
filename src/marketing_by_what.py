"""marketing_by_what.py — 第3観測層の MOFU を「何の支援を聞いているか」で分けた月次の表(2026-11-17).

使い方:  python src/marketing_by_what.py 2026-11      (月を省くと前月)

対象:会社名を含まない MOFU(MOFU_L0・L1・L2)の質問の、その月の Gemini の観測(観測できた行だけ。
同じ月に2回あれば後の日。marketing.latest_observations と同じ)。

支援の種類(WHAT):prompts_marketing.csv には支援の種類の列が無いので、質問文に含まれる語で決める。
  「Agentforce導入支援」→ Agentforce導入支援 /「Agentforce活用定着支援」→ Agentforce活用定着支援 /
  「Agentic CRM設計支援」→ Agentic CRM設計支援 / それ以外 → その他

出すもの
1. 支援の種類ごとの 観測本数・名前が出た本数(mentioned=1)・引用された本数(cited_domain=1)
2. 名前が出た質問の一覧(ID・質問・何番目)
3. 支援の種類ごとに多く挙げられた会社の上位5社(その会社が出た回答の本数。5位が同数なら全部出す)
4. 一覧(config/marketing_companies.yaml)に無い会社名の候補(一覧に足すかの確認用)

何番目:回答の本文で、クロスコムの初出より前に初出する会社(一覧の会社)の数 + 1。
marketing.mention_rank と同じ決め方で、会社の一覧だけを Haiku ではなく config の一覧にしている
(Haiku の順位の抽出は 2026-10-03 から停止中)。

数字の解釈は出さない。raw(data/raw/marketing)を読むだけで、シートにもファイルにも書かない。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import experiment  # noqa: E402
import marketing  # noqa: E402
from settings import CONFIG_DIR, DATA_RAW_MARKETING_DIR, load_marketing_prompts  # noqa: E402

COMPANIES_FILE = CONFIG_DIR / "marketing_companies.yaml"
MOFU_LAYERS = ("MOFU_L0", "MOFU_L1", "MOFU_L2")
WHATS = (("Agentforce導入支援", "Agentforce導入支援"),
         ("Agentforce活用定着支援", "Agentforce活用定着支援"),
         ("Agentic CRM設計支援", "Agentic CRM設計支援"))
OTHER = "その他"
WHAT_ORDER = tuple(w for _, w in WHATS) + (OTHER,)
SELF_NAMES = ("クロスコム", "cross-com", "crosscom")
TOP = 5


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def what_of(prompt: str) -> str:
    """質問文から支援の種類を決める。"""
    for key, what in WHATS:
        if key in str(prompt):
            return what
    return OTHER


def is_target(prompt: Dict[str, Any]) -> bool:
    """会社名を含まない MOFU の質問か。"""
    return prompt.get("layer") in MOFU_LAYERS and not experiment.is_mentioned_v2(prompt.get("prompt", ""))


def load_companies(path: Path = COMPANIES_FILE) -> Dict[str, "re.Pattern[str]"]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(name): re.compile(str(pattern)) for name, pattern in (data.get("companies") or {}).items()}


def company_positions(answer: str, companies: Dict[str, "re.Pattern[str]"]) -> Dict[str, int]:
    """{会社: 本文(NFKC・小文字)での初出の位置}。"""
    folded = fold(answer)
    out = {}
    for name, rx in companies.items():
        m = rx.search(folded)
        if m:
            out[name] = m.start()
    return out


def rank_of(answer: str, positions: Dict[str, int]) -> Optional[int]:
    """クロスコムが何番目に出たか。出なければ None。"""
    hits = experiment.mention_hits_v2(answer)
    if not hits:
        return None
    ours = hits[0][0]
    return sum(1 for p in positions.values() if p < ours) + 1


_BOLD = re.compile(r"\*\*([^*\n]{2,40}?)\*\*")
_CORP = re.compile(r"(?:株式会社|合同会社)[^\s、。,（(：:*「」]{1,15}|[^\s、。,（(：:*「」]{1,15}(?:株式会社|合同会社)")


def unknown_candidates(answer: str, companies: Dict[str, "re.Pattern[str]"]) -> List[str]:
    """一覧に無い会社名の候補(株式会社・合同会社を含む語)。一覧に足すかを人が決めるための材料。

    一覧の会社に当たった箇所と重なる語は出さない。法人格の無い名前(太字の見出しだけの社名など)は拾えないので、
    毎月の表を出したときに回答の本文も目で確かめる。
    """
    folded = fold(answer)
    known = [m.span() for rx in companies.values() for m in rx.finditer(folded)]
    out = []
    for m in _CORP.finditer(folded):
        name = m.group(0).strip()
        s, e = m.span()
        if any(x in name for x in SELF_NAMES) or any(a < e and s < b for a, b in known):
            continue
        if name not in out:
            out.append(name)
    return out


def load_rows(month: str, root: Path = DATA_RAW_MARKETING_DIR) -> List[Dict[str, Any]]:
    rows = []
    for f in sorted(root.glob(f"{month}-*/*_gemini.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if str(r.get("error") or "").strip() == "None":     # 古い raw は error に文字列の None が入っている
            r["error"] = ""
        rows.append(r)
    return rows


def flag(row: Dict[str, Any], col: str) -> bool:
    return str(row.get(col, "")).strip() in ("1", "True")


def summarize(rows: Iterable[Dict[str, Any]], prompts: List[Dict[str, Any]],
              companies: Dict[str, "re.Pattern[str]"]) -> Dict[str, Any]:
    by_id = {p["id"]: p for p in prompts}
    cells = {w: {"n": 0, "mentioned": 0, "cited": 0, "hits": [], "companies": collections.Counter(),
                 "ids": []} for w in WHAT_ORDER}
    unknown = collections.Counter()
    for r in sorted(marketing.latest_observations(rows), key=lambda x: x.get("prompt_id", "")):
        p = by_id.get(r.get("prompt_id"))
        if p is None or not is_target(p):
            continue
        c = cells[what_of(p["prompt"])]
        answer = r.get("answer_text") or r.get("answer") or ""
        pos = company_positions(answer, companies)
        c["n"] += 1
        c["ids"].append(p["id"])
        c["mentioned"] += flag(r, "mentioned")
        c["cited"] += flag(r, "cited_domain")
        c["companies"].update(pos.keys())
        if flag(r, "mentioned"):
            c["hits"].append({"id": p["id"], "layer": p["layer"], "prompt": p["prompt"],
                              "date": r.get("date", ""), "rank": rank_of(answer, pos),
                              "cited": flag(r, "cited_domain")})
        unknown.update(unknown_candidates(answer, companies))
    return {"cells": cells, "unknown": unknown}


def top_companies(counter: collections.Counter, top: int = TOP) -> List[Tuple[str, int]]:
    """上位 top 社。top 番目と同数の会社も含める。"""
    ranked = counter.most_common()
    if len(ranked) <= top:
        return ranked
    edge = ranked[top - 1][1]
    return [(n, c) for n, c in ranked if c >= edge]


def render(month: str, result: Dict[str, Any]) -> str:
    cells = result["cells"]
    lines = [f"# 第3観測層 MOFU（会社名を含まない質問）の支援の種類ごとの集計 {month}（Gemini）", "",
             "## 1. 観測本数・名前が出た本数", "",
             "| 支援の種類 | 観測本数 | 名前が出た | 引用された |", "|---|---|---|---|"]
    tot = [0, 0, 0]
    for w in WHAT_ORDER:
        c = cells[w]
        lines.append(f"| {w} | {c['n']} | {c['mentioned']} | {c['cited']} |")
        tot = [tot[0] + c["n"], tot[1] + c["mentioned"], tot[2] + c["cited"]]
    lines += [f"| 計 | {tot[0]} | {tot[1]} | {tot[2]} |", "", "## 2. 名前が出た質問と何番目か", "",
              "| 支援の種類 | ID | 質問 | 観測日 | 何番目 |", "|---|---|---|---|---|"]
    for w in WHAT_ORDER:
        for h in cells[w]["hits"]:
            lines.append(f"| {w} | {h['id']} | {h['prompt']} | {h['date']} | {h['rank'] or '–'} |")
    lines += ["", "名前が出なかった質問:"]
    for w in WHAT_ORDER:
        hit = {h["id"] for h in cells[w]["hits"]}
        rest = [i for i in cells[w]["ids"] if i not in hit]
        lines.append(f"- {w}：{'・'.join(rest) if rest else 'なし'}")
    lines += ["", f"## 3. 多く挙げられた会社（上位{TOP}社・その会社が出た回答の本数）", "",
              "| 支援の種類 | 回答数 | 会社（本数） |", "|---|---|---|"]
    for w in WHAT_ORDER:
        tops = top_companies(cells[w]["companies"])
        lines.append(f"| {w} | {cells[w]['n']} | {'・'.join(f'{n} {c}' for n, c in tops) or 'なし'} |")
    lines += ["", "## 4. 一覧（config/marketing_companies.yaml）に無い会社名の候補", ""]
    unknown = result["unknown"].most_common()
    lines += [f"- {n}（{c}本）" for n, c in unknown] or ["- なし"]
    return "\n".join(lines) + "\n"


def previous_month(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    first = today.replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("month", nargs="?", help="YYYY-MM(省くと前月)")
    a = ap.parse_args(argv)
    month = a.month or previous_month()
    result = summarize(load_rows(month), load_marketing_prompts(), load_companies())
    sys.stdout.write(render(month, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
