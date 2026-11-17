"""marketing_by_what.py — 第3観測層(prompt_marketing)の月次報告(2026-11-17 確定・戦略管制塔の採否).

使い方:  python src/marketing_by_what.py 2026-12            (月を省くと前月。標準出力に出す)
         python src/marketing_by_what.py 2026-12 --write    (output/reports/marketing_monthly_2026-12.md にも書く)

報告の順番(毎月同じ形):
(1) 会社名を含まない MOFU のうち What が「Agentforce導入支援」「Agentforce活用定着支援」の質問で、クロスコムの名前が
    出た本数(件数。率は出さない)と何番目の一覧。注記「2か月続けて変わったときだけ変化と読む」。
    その下に「ChatGPT（B-2・手作業）」(output/b2_chatgpt_monthly.csv。本田さんが毎月入力)
(2) What が「Agentic CRM設計支援」の質問の同じ表
(3) 外部サイトの言及による推薦:名前が出た MOFU の回答のうち、cross-com.jp を引用元にしていない回答の本数と、
    名前が出た MOFU の回答の引用元のうち cross-com.jp 以外のドメインの一覧(人が中身を確かめるため)
(4) BOFU(質問文に社名が入るもの)の名前が出た本数
(5) 層ごとに多く挙げられた会社の上位5社(その会社が出た回答の本数。5位と同数は全部出す)
最後に、MOFU の What ごとの観測本数と、会社の一覧(config/marketing_companies.yaml)に無い会社名の候補。

- 対象は Gemini の観測で、答えが返った行だけ(同じ月に2回あれば後の日。marketing.latest_observations と同じ)
- What は config/marketing_what.yaml(出典は output/reports/prompt_overlap_2026-10-10.md の4軸の表)。
  config/prompts_marketing.csv は observation_lock の対象のため列を足していない
- 何番目:回答の本文で、クロスコムの初出より前に初出する会社(config/marketing_companies.yaml の一覧)の数 + 1。
  marketing.mention_rank と同じ決め方で、会社の一覧だけを Haiku ではなく config にしている(Haiku の順位の抽出は 2026-10-03 から停止中)
- 数字の解釈は出さない。raw(data/raw/marketing)を読むだけで、シートには書かない
"""
from __future__ import annotations

import argparse
import ast
import collections
import csv
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
from settings import CONFIG_DIR, DATA_RAW_MARKETING_DIR, ROOT_DIR, load_marketing_prompts  # noqa: E402

OUTPUT_DIR = ROOT_DIR / "output"

COMPANIES_FILE = CONFIG_DIR / "marketing_companies.yaml"
WHAT_FILE = CONFIG_DIR / "marketing_what.yaml"
B2_FILE = OUTPUT_DIR / "b2_chatgpt_monthly.csv"
REPORTS_DIR = OUTPUT_DIR / "reports"

MOFU_LAYERS = ("MOFU_L0", "MOFU_L1", "MOFU_L2")
BOFU_LAYERS = ("BOFU_single", "BOFU_compare")
LAYER_ORDER = MOFU_LAYERS + BOFU_LAYERS
SECTION1 = ("Agentforce導入支援", "Agentforce活用定着支援")
SECTION2 = ("Agentic CRM設計支援",)
B2_PROMPTS = ("②導入支援のおすすめ", "P2-1 定着", "P2-2 スモールスタート")
B2_HEADERS = ["month", "prompt", "mentioned", "rank", "cited_crosscom", "note"]
CHANGE_NOTE = "2か月続けて変わったときだけ変化と読む"
UNIT_NOTE = "件数で出す（率は出さない）"
SELF_NAMES = ("クロスコム", "cross-com", "crosscom")
TOP = 5


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


# --------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------
def load_what(path: Path = WHAT_FILE) -> Dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (data.get("what") or {}).items()}


def load_companies(path: Path = COMPANIES_FILE) -> Dict[str, "re.Pattern[str]"]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(name): re.compile(str(pattern)) for name, pattern in (data.get("companies") or {}).items()}


def load_b2(month: str, path: Path = B2_FILE) -> Dict[str, Dict[str, str]]:
    """ChatGPT(B-2・手作業)のその月の行 {プロンプト: 行}。ファイルが無ければ空。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["prompt"].strip(): r for r in csv.DictReader(fh) if r.get("month", "").strip() == month}


def is_target(prompt: Dict[str, Any]) -> bool:
    """会社名を含まない MOFU の質問か。"""
    return prompt.get("layer") in MOFU_LAYERS and not experiment.is_mentioned_v2(prompt.get("prompt", ""))


# --------------------------------------------------------------------------
# 1本ごとの判定
# --------------------------------------------------------------------------
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


def cited_domains(row: Dict[str, Any]) -> List[str]:
    value = row.get("cited_domains") or []
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value) if value.strip() else []
        except (ValueError, SyntaxError):
            value = [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


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


# --------------------------------------------------------------------------
# 集計
# --------------------------------------------------------------------------
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


def observations(rows: Iterable[Dict[str, Any]], prompts: List[Dict[str, Any]], what: Dict[str, str],
                 companies: Dict[str, "re.Pattern[str]"]) -> List[Dict[str, Any]]:
    """観測できた行を1本ずつ判定した一覧(id 順)。"""
    by_id = {p["id"]: p for p in prompts}
    out = []
    for r in sorted(marketing.latest_observations(rows), key=lambda x: x.get("prompt_id", "")):
        p = by_id.get(r.get("prompt_id"))
        if p is None:
            continue
        answer = r.get("answer_text") or r.get("answer") or ""
        pos = company_positions(answer, companies)
        mentioned = flag(r, "mentioned")
        out.append({"id": p["id"], "layer": p["layer"], "prompt": p["prompt"], "what": what.get(p["id"], ""),
                    "target": is_target(p), "date": r.get("date", ""), "mentioned": mentioned,
                    "cited": flag(r, "cited_domain"), "rank": rank_of(answer, pos) if mentioned else None,
                    "companies": list(pos), "domains": cited_domains(r),
                    "unknown": unknown_candidates(answer, companies)})
    return out


def top_companies(counter: collections.Counter, top: int = TOP) -> List[Tuple[str, int]]:
    """上位 top 社。top 番目と同数の会社も含める。"""
    ranked = counter.most_common()
    if len(ranked) <= top:
        return ranked
    edge = ranked[top - 1][1]
    return [(n, c) for n, c in ranked if c >= edge]


def _is_self_domain(domain: str) -> bool:
    return bool(experiment.is_self_domain(domain))


def build(obs: List[Dict[str, Any]], b2: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    mofu = [o for o in obs if o["target"]]
    named = [o for o in mofu if o["mentioned"]]
    external = collections.Counter(d for o in named for d in dict.fromkeys(o["domains"]) if not _is_self_domain(d))
    layers = {layer: [o for o in obs if o["layer"] == layer] for layer in LAYER_ORDER}
    return {
        "section1": [o for o in mofu if o["what"] in SECTION1],
        "section2": [o for o in mofu if o["what"] in SECTION2],
        "b2": b2,
        "named_mofu": named,
        "named_without_self_citation": [o for o in named if not any(_is_self_domain(d) for d in o["domains"])],
        "external_domains": external,
        "bofu": {layer: layers[layer] for layer in BOFU_LAYERS},
        "tops": {layer: (len(rows), top_companies(collections.Counter(c for o in rows for c in o["companies"])))
                 for layer, rows in layers.items()},
        "what_counts": collections.Counter(o["what"] for o in mofu),
        "unknown": collections.Counter(n for o in obs for n in o["unknown"]),
    }


# --------------------------------------------------------------------------
# 表示
# --------------------------------------------------------------------------
def _what_table(rows: List[Dict[str, Any]], whats: Tuple[str, ...]) -> List[str]:
    lines = ["| What | 観測した本数 | 名前が出た本数 |", "|---|---|---|"]
    for w in whats:
        sub = [o for o in rows if o["what"] == w]
        lines.append(f"| {w} | {len(sub)} | {sum(o['mentioned'] for o in sub)} |")
    lines += ["", "| What | ID | 質問 | 観測日 | 名前 | 何番目 |", "|---|---|---|---|---|---|"]
    for o in rows:
        lines.append(f"| {o['what']} | {o['id']} | {o['prompt']} | {o['date']} | "
                     f"{'出た' if o['mentioned'] else '出ない'} | {o['rank'] or '–'} |")
    return lines


def _b2_table(b2: Dict[str, Dict[str, str]]) -> List[str]:
    lines = ["| プロンプト | 名前が出たか | 何番目 | 引用元に cross-com.jp |", "|---|---|---|---|"]
    for p in B2_PROMPTS:
        r = b2.get(p)
        if r is None:
            lines.append(f"| {p} | 未入力 | 未入力 | 未入力 |")
        else:
            lines.append(f"| {p} | {r.get('mentioned', '')} | {r.get('rank', '') or '–'} | {r.get('cited_crosscom', '')} |")
    return lines


def render(month: str, rep: Dict[str, Any]) -> str:
    out = [f"# 第3観測層の月次報告 {month}（Gemini）", "",
           f"会社名を含まない MOFU の質問の What ごとの本数。{UNIT_NOTE}。",
           f"What は config/marketing_what.yaml（2026-10-10 の重複調査の4軸の表）。", "",
           "## (1) Agentforce導入支援・Agentforce活用定着支援", "", f"※ {CHANGE_NOTE}", ""]
    out += _what_table(rep["section1"], SECTION1)
    out += ["", "### ChatGPT（B-2・手作業）", "",
            "本田さんが毎月手作業で行う B-2 観測の ChatGPT 欄（output/b2_chatgpt_monthly.csv）。新しい観測は作っていない", ""]
    out += _b2_table(rep["b2"])
    out += ["", "## (2) Agentic CRM設計支援", "", f"※ {CHANGE_NOTE}", ""]
    out += _what_table(rep["section2"], SECTION2)
    out += ["", "## (3) 外部サイトの言及による推薦", "",
            "名前が出た MOFU（会社名を含まない質問）の回答のうち、cross-com.jp を引用元にしていない回答", "",
            "| 名前が出た回答 | うち cross-com.jp を引用元にしていない |", "|---|---|",
            f"| {len(rep['named_mofu'])} | {len(rep['named_without_self_citation'])} |", ""]
    if rep["named_without_self_citation"]:
        out += [f"- {o['id']}（{o['what']}）" for o in rep["named_without_self_citation"]] + [""]
    out += ["名前が出た回答の引用元のうち、cross-com.jp 以外のドメイン（その回答の本数）", ""]
    out += [f"- {d}（{c}）" for d, c in rep["external_domains"].most_common()] or ["- なし"]
    out += ["", "## (4) BOFU（質問文に社名が入るもの）", "",
            "| 層 | 観測した本数 | 名前が出た本数 |", "|---|---|---|"]
    for layer, rows in rep["bofu"].items():
        out.append(f"| {layer} | {len(rows)} | {sum(o['mentioned'] for o in rows)} |")
    out += ["", f"## (5) 層ごとに多く挙げられた会社（上位{TOP}社・その会社が出た回答の本数。{TOP}位と同数は全部）", "",
            "| 層 | 回答数 | 会社（本数） |", "|---|---|---|"]
    for layer, (n, tops) in rep["tops"].items():
        out.append(f"| {layer} | {n} | {'・'.join(f'{c} {k}' for c, k in tops) or 'なし'} |")
    out += ["", "## 参考：MOFU（会社名を含まない質問）の What ごとの観測本数", "", "| What | 観測した本数 |", "|---|---|"]
    out += [f"| {w} | {c} |" for w, c in sorted(rep["what_counts"].items(), key=lambda x: (-x[1], x[0]))]
    out += ["", "## 参考：会社の一覧（config/marketing_companies.yaml）に無い会社名の候補", ""]
    out += [f"- {n}（{c}本）" for n, c in rep["unknown"].most_common()] or ["- なし"]
    return "\n".join(out) + "\n"


def report(month: str) -> str:
    obs = observations(load_rows(month), load_marketing_prompts(), load_what(), load_companies())
    return render(month, build(obs, load_b2(month)))


def previous_month(today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="第3観測層の月次報告")
    ap.add_argument("month", nargs="?", help="YYYY-MM(省くと前月)")
    ap.add_argument("--write", action="store_true", help="output/reports/marketing_monthly_<月>.md にも書く")
    a = ap.parse_args(argv)
    month = a.month or previous_month()
    text = report(month)
    sys.stdout.write(text)
    if a.write:
        path = REPORTS_DIR / f"marketing_monthly_{month}.md"
        path.write_text(text, encoding="utf-8")
        print(f"[ok] {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
