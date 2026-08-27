"""display_text.py — 「画面に出る文字列」だけを取り出して英字を検出する共通処理.

app/ の表示文言と config/verdict_templates.yaml の判定文は、どちらも同じ画面に
並んで出る。同じ語彙で判定しないと片方だけ英語が残るため、許可語リストと
正規化はここ1か所に置いて両方のテストから使う。

走査対象は「表示位置にある文字列リテラル」だけ。シートのカラム名・タブ名や
書式指定の文字列は画面に出ないので、意図的に見ない(下の SINKS を参照)。
"""
from __future__ import annotations

import ast
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

# --------------------------------------------------------------------------
# 英字のまま残してよい語(指示の5種)
# --------------------------------------------------------------------------
# ① 製品・サービス名
PRODUCT_NAMES = {
    "Gemini", "Claude", "Slack", "Looker", "Studio", "Salesforce",
    "Agentforce", "Agentic", "CRM", "GA4", "GSC", "AUBA", "PR", "TIMES",
    "Google", "Sheets", "GitHub", "Actions", "Streamlit", "Ahrefs",
    "Organization", "MA",
    # LLMO: このシステムの固有名。画面タイトル「LLMO レポート」がそれで、
    #   訳すと別のシステムを指してしまうため固有名詞として残す。
    "LLMO",
    # API: 技術用語であり、かつ製品名の一部(「Google Sheets API」)。
    #   単独で訳すと何を指すか分からなくなるため残す。
    "API",
}
# ③ 定着済み略語
ABBREVIATIONS = {"AI", "KBF", "CEP", "URL"}

# 「成果指標(KGI)」の初出併記でのみ使う。2回目以降は使わない
# (1画面に1回までであることは tests/test_app_labels.py で固定している)。
KGI = "KGI"

ALLOWED_WORDS = PRODUCT_NAMES | ABBREVIATIONS | {KGI}

# ② 識別コードの値。ラベルや見出しは日本語にするが、値そのものは英字で出す。
ID_PATTERNS = (
    r"\bR[1-8]\b",              # 面コード
    r"\bP[1-5]\b",              # 詳細画面コード
    r"\bR-(?:P\d+|DROP)\b",     # rule_id
    r"\bA-\d{3}\b",             # action_id
    r"\b[A-E]-\d\b",            # prompt_id
)


def visible_text(text: str) -> str:
    """表示文字列から、日本語化の対象にならない部分を落とす。"""
    text = re.sub(r"`[^`]*`", " ", text)            # ⑤ コード表記のファイル名・タブ名
    text = re.sub(r"<[^>]*>", " ", text)            # HTMLタグとその中のCSS
    text = re.sub(r"%\{[^{}]*\}", " ", text)        # グラフの書式指定
    text = re.sub(r"\{[^{}]*\}", " ", text)         # 変数の差し込み位置
    text = re.sub(r"https?://\S+", " ", text)       # ④ URL
    text = re.sub(r"\b[\w-]+\.(?:jp|com|net|org|io)\b", " ", text)   # ④ ドメイン
    for pattern in ID_PATTERNS:
        text = re.sub(pattern, " ", text)
    return text


def english_words(text: str) -> List[str]:
    """表示に残る英単語(2文字以上)。許可語の判定はこの結果に対して行う。"""
    return re.findall(r"[A-Za-z]{2,}", visible_text(text))


# --------------------------------------------------------------------------
# 表示位置の文字列リテラルを集める
# --------------------------------------------------------------------------
# 呼び出し名 -> (位置引数をどこまで見るか, 追加で見るキーワード)
#   "all"   … 位置引数すべて   "first" … 第1引数のみ   "none" … 位置引数は見ない
SINKS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    # Streamlit の表示API(オブジェクト経由の col.metric(...) も名前で拾う)
    "title": ("all", ()),
    "header": ("all", ()),
    "subheader": ("all", ()),
    "caption": ("all", ()),
    "markdown": ("all", ()),
    "write": ("all", ()),
    "info": ("all", ()),
    "warning": ("all", ()),
    "error": ("all", ()),
    "success": ("all", ()),
    "metric": ("all", ("label", "value", "delta", "help")),
    "button": ("first", ("help",)),
    "selectbox": ("all", ("help", "placeholder")),
    "multiselect": ("all", ("help", "placeholder")),
    "radio": ("all", ("help",)),
    "checkbox": ("first", ("help",)),
    "toggle": ("first", ("help",)),
    "date_input": ("first", ("help",)),
    "text_input": ("first", ("help", "placeholder")),
    "number_input": ("first", ("help",)),
    "slider": ("first", ("help",)),
    "tabs": ("all", ()),
    "expander": ("first", ()),
    "Page": ("none", ("title",)),
    # アプリ側の表示ヘルパ
    "page_header": ("all", ()),
    "face_header": ("all", ()),
    "metric_card": ("all", ("note", "help_text")),
    "empty_state": ("all", ()),
}

# 表の見出しになる文字列。辞書のキーと columns= だけを見る(値はデータ)。
FRAME_BUILDERS = {"DataFrame"}

# グラフの表示文言を載せるキーワード。どの呼び出しでも見る。
PLOT_TEXT_KWARGS = {
    "hovertemplate", "annotation_text", "texttemplate", "hovertext",
    "xaxis_title", "yaxis_title", "title_text",
}
# ``name=`` は凡例名にもデータ構造の名前にもなる。グラフの呼び出しだけで見る
# (``pd.Index(..., name="date")`` は画面に出ないため対象外)。
PLOT_CALLS = {
    "Scatter", "Scattergl", "Bar", "Heatmap", "Box", "Histogram", "Pie",
    "Figure", "add_trace", "update_layout", "update_traces",
}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _joined(node: ast.JoinedStr) -> str:
    """f文字列を1本に戻す。差し込み部分は `{}` に潰す。

    こうしないと ``f"<div style='...{色}...'>"`` が細切れになり、HTMLタグを
    まとめて落とせなくなる。
    """
    out = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            out.append(part.value)
        else:
            out.append("{}")
    return "".join(out)


def _strings(node: Optional[ast.AST]) -> Iterator[str]:
    """ノード配下の文字列リテラル(f文字列は1本に戻して返す)。

    表示呼び出しの中にあっても、辞書の引き方(``record.get("model")``、
    ``position["rank"]``)は画面に出ないので降りない。カラム名は変更禁止で、
    ここで拾うと日本語化を強いてしまう。
    """
    if node is None:
        return
    if isinstance(node, ast.JoinedStr):
        yield _joined(node)
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node.value
        return
    if isinstance(node, ast.Call) and _call_name(node) in ("get", "getattr"):
        return
    if isinstance(node, ast.Subscript):
        yield from _strings(node.value)   # 添字(キー)は見ない
        return
    for child in ast.iter_child_nodes(node):
        yield from _strings(child)


def _dict_keys(node: ast.AST) -> Iterator[str]:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Dict):
            for key in inner.keys:
                yield from _strings(key)


def _plot_strings(call: ast.Call) -> Iterator[str]:
    for kw in call.keywords:
        if kw.arg in PLOT_TEXT_KWARGS:
            yield from _strings(kw.value)
        elif kw.arg == "name" and _call_name(call) in PLOT_CALLS:
            yield from _strings(kw.value)
        elif kw.arg in ("title", "text"):
            # title= は生の文字列か dict(text=...) のどちらか。
            # dict の他のキー(side= など)まで拾うと誤検出になるので絞る。
            if isinstance(kw.value, (ast.Constant, ast.JoinedStr)):
                yield from _strings(kw.value)
            elif isinstance(kw.value, ast.Call) and _call_name(kw.value) == "dict":
                for inner in kw.value.keywords:
                    if inner.arg == "text":
                        yield from _strings(inner.value)


def display_strings(source: str) -> List[Tuple[int, str]]:
    """ソース中の表示文字列を (行番号, 文字列) で返す。"""
    tree = ast.parse(source)
    found: List[Tuple[int, str]] = []

    def add(line: int, values: Iterator[str]) -> None:
        for value in values:
            if value.strip():
                found.append((line, value))

    for node in ast.walk(tree):
        # 表示ラベルの辞書(``*_LABELS``)は値だけが画面に出る。キーは内部名。
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and \
                isinstance(node.value, ast.Dict):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if any(name.endswith("_LABELS") for name in names):
                for value in node.value.values:
                    add(node.lineno, _strings(value))
            continue

        if not isinstance(node, ast.Call):
            continue

        add(node.lineno, _plot_strings(node))
        name = _call_name(node)

        if name in FRAME_BUILDERS:
            for arg in node.args:
                add(node.lineno, _dict_keys(arg))
            for kw in node.keywords:
                if kw.arg == "columns":
                    add(node.lineno, _strings(kw.value))
            continue

        if name not in SINKS:
            continue
        positional, kwargs = SINKS[name]
        args = node.args if positional == "all" else (
            node.args[:1] if positional == "first" else [])
        for arg in args:
            add(node.lineno, _strings(arg))
        for kw in node.keywords:
            if kw.arg in kwargs:
                add(node.lineno, _strings(kw.value))

    return found


def offending_words(source: str) -> List[Tuple[int, str, str]]:
    """許可語に無い英単語を (行番号, 単語, 元の文字列) で返す。"""
    out: List[Tuple[int, str, str]] = []
    for line, text in display_strings(source):
        for word in english_words(text):
            if word not in ALLOWED_WORDS:
                out.append((line, word, text))
    return out
