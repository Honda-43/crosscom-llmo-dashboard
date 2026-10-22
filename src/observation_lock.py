"""observation_lock.py — 観測の実行と記録を変えない決まりの見張り(2026-10-22・戦略管制塔との決まり).

決まり:ダッシュボードの作り直しは表示の部分のみ。観測の実行と記録は、長期判定(12/28 の週)が
終わるまで変更しない。変更が必要な場合は、事前に効果測定チャットと管制塔へ相談する。

- 見張るファイルと、その中身のハッシュ(SHA-256)は config/observation_lock.yaml に置く。
  tests/test_observation_lock.py がハッシュを計算し直し、違えば失敗する(2027-01-04 以降は飛ばす)。
- 表示の部分と同じファイルに同居しているもの(settings.py・sheets_writer.py・marketing.py・retired_urls.py)は、
  ファイル全体ではなく、観測の実行と記録に使う関数・定数(symbols)だけをハッシュする。
- requirements.txt は、観測に使うライブラリの == で固定した行(packages)だけをハッシュする(2026-10-22)。
  ほかの行の追加・変更では失敗しない。固定した行のコメントの書き換えも失敗しない
  表示の部分の関数を直しても失敗しない。
- 改行コード(CRLF/LF)の違いは同じ中身として扱う(Windows の checkout で CRLF になるため)。

相談して承認された変更をしたとき(ハッシュの更新だけのコミットは作らない):
  python src/observation_lock.py --update --reason "承認の経緯(誰がいつ何を承認したか)"
ハッシュを書き直し、同じ理由を observation_lock.yaml の history と実験日誌に追記する。
変更したファイルと一緒に1つのコミットにする。
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "config" / "observation_lock.yaml"
DIARY_FILE = ROOT / "output" / "reports" / "experiment47_diary.md"
JST = dt.timezone(dt.timedelta(hours=9), name="JST")

# 長期判定(12/28 の週)の後。この日以降はテストを飛ばす
EXPIRES_ON = "2027-01-04"
RULE_MESSAGE = ("観測の実行と記録は長期判定（12/28 の週）まで変更しない決まり。"
                "変更が必要なら効果測定チャットと管制塔へ事前に相談")


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _top_level_names(node: ast.stmt) -> List[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def symbol_sources(text: str, symbols: List[str]) -> Dict[str, str]:
    """モジュールの一番外側の関数・クラス・代入のうち ``symbols`` の名前のソース(デコレータ込み)。
    無い名前は KeyError(消した・名前を変えた、も変更として止める)。"""
    tree = ast.parse(text)
    lines = text.split("\n")
    found: Dict[str, List[str]] = {}
    for node in tree.body:
        for name in _top_level_names(node):
            if name in symbols:
                start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
                found.setdefault(name, []).append("\n".join(lines[start - 1:node.end_lineno]))
    missing = [s for s in symbols if s not in found]
    if missing:
        raise KeyError(f"見つからない名前: {', '.join(missing)}")
    return {s: "\n".join(found[s]) for s in symbols}


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def requirement_lines(text: str, packages: List[str]) -> Dict[str, str]:
    """requirements.txt のうち ``packages`` の行(末尾のコメントを除いた指定)。名前は大文字小文字・-_. を区別しない。
    無いパッケージ・2行あるパッケージは KeyError(消した・書き足した、も変更として止める)。"""
    def norm(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()
    want = {norm(p): p for p in packages}
    found: Dict[str, List[str]] = {}
    for line in text.split("\n"):
        spec = line.split("#", 1)[0].strip()
        m = _REQ_NAME.match(spec)
        if spec and m and norm(m.group(1)) in want:
            found.setdefault(want[norm(m.group(1))], []).append(spec)
    bad = [p for p in packages if len(found.get(p, [])) != 1]
    if bad:
        raise KeyError(f"見つからない・重なっているパッケージ: {', '.join(bad)}")
    return {p: found[p][0] for p in packages}


def digest(entry: Dict[str, Any], root: Path = ROOT) -> str:
    """一覧の1件のハッシュ。symbols があればその名前のソースだけ、packages があれば
    requirements.txt のその行だけ(コメントは除く)、どちらも無ければファイル全体。"""
    text = _text(root / entry["path"])
    symbols = entry.get("symbols")
    packages = entry.get("packages")
    if packages:
        lines = requirement_lines(text, list(packages))
        text = "".join(f"{lines[p]}\n" for p in packages)
    elif symbols:
        src = symbol_sources(text, list(symbols))
        text = "".join(f"# {name}\n{src[name]}\n" for name in symbols)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path: Path = LOCK_FILE) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def changed(lock: Optional[Dict[str, Any]] = None, root: Path = ROOT) -> List[str]:
    """ハッシュが記録と違う(またはファイル・名前が見つからない)一覧の path。"""
    lock = load() if lock is None else lock
    out = []
    for entry in lock["files"]:
        try:
            now = digest(entry, root)
        except (OSError, KeyError, SyntaxError) as exc:
            out.append(f"{entry['path']}（{exc}）")
            continue
        if now != entry["sha256"]:
            label = entry["path"] + (f"（{len(entry['symbols'])}個の関数・定数）" if entry.get("symbols") else
                                     f"（{'・'.join(entry['packages'])} の行）" if entry.get("packages") else "")
            out.append(label)
    return out


def expired(today: Optional[dt.date] = None) -> bool:
    today = today or dt.datetime.now(JST).date()
    return today >= dt.date.fromisoformat(EXPIRES_ON)


def update(reason: str, path: Path = LOCK_FILE, diary: Path = DIARY_FILE,
           today: Optional[str] = None, root: Path = ROOT) -> List[str]:
    """承認された変更の後で、ハッシュを書き直し、理由を history と日誌に追記する。変わった path を返す。"""
    if not reason or not reason.strip():
        raise ValueError("--reason(承認の経緯)が要る")
    today = today or dt.datetime.now(JST).date().isoformat()
    lock = load(path)
    before = changed(lock, root)
    if not before:
        raise ValueError("ハッシュの変わったファイルが無い(更新するものが無い)")
    text = _text(path)
    for entry in lock["files"]:
        old, new = entry["sha256"], digest(entry, root)
        if old != new:
            text = text.replace(old, new, 1)
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)
    entry_line = f"  - {{date: {q(today)}, files: {q('・'.join(before))}, reason: {q(reason.strip())}}}\n"
    text = text.replace("history: []\n", "history:\n") if "history: []\n" in text else text
    text = text.rstrip("\n") + "\n" + entry_line
    path.write_text(text, encoding="utf-8", newline="\n")
    with open(diary, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n### {today} 観測の実行と記録の変更（承認済み・observation_lock.yaml のハッシュを更新）\n"
                f"- 変えたもの：{'・'.join(before)}\n- 承認の経緯：{reason.strip()}\n")
    return before


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="観測の実行と記録の見張り(ハッシュの確認・承認後の更新)")
    ap.add_argument("--update", action="store_true", help="承認された変更の後でハッシュを書き直す")
    ap.add_argument("--reason", help="承認の経緯(--update のとき必須。history と日誌に残す)")
    a = ap.parse_args(argv)
    if a.update:
        done = update(a.reason or "")
        print("ハッシュを更新:" + "・".join(done) + "(日誌に追記した。変更と同じコミットにする)")
        return 0
    bad = changed()
    if bad:
        print(f"{RULE_MESSAGE}\n変わったもの:" + "・".join(bad))
        return 1
    print("観測の実行と記録のファイルは変わっていない")
    return 0


if __name__ == "__main__":
    sys.exit(main())
