"""insight_style.py — 週次所見の記述ルール(Phase 7 §B).

所見は毎週同じ読み方をされる。同じ状態なら同じ言い回しで出ることが前提で、
週ごとに表記が揺れると「変わったのは状態か、文章か」が判別できなくなる。
判定欄(verdicts.py)をテンプレートで固定したのと同じ理由で、所見文についても
決められる部分は決めてしまう。

このモジュールが持つのは5つ:

1. 数値の表記     — 率は%、差分は「ポイント」。小数の生値は出さない。
2. 横ばいの定義   — 前週比が閾値以内なら「横ばい」と書く(閾値はYAML)。
3. パターンの説明 — rule_id の初出に日本語の定義を併記する。
4. 禁止語         — 比喩を使わない(押し出す・定着・供給・型 など)。
5. 同時発火の統合 — 同一プロンプトの R-P2 と R-P15 を1項目にまとめる。

LLMに書かせる部分はプロンプトで指示し、確定的に直せる部分はここで後処理する。
プロンプトだけでは守られない週があり、後処理だけでは文章が不自然になるので、
両方を使う。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 3行の箇条書きのラベル。この3つ以外を項目内に増やさない。
LABEL_STATE = "状態"
LABEL_CAUSE = "原因仮説"
LABEL_ACTION = "推奨アクション"
PATTERN_LABELS = (LABEL_STATE, LABEL_CAUSE, LABEL_ACTION)

# 前週比が±この値(ポイント)以内なら「横ばい」。YAMLに無いときの既定値。
DEFAULT_FLAT_DELTA_POINTS = 5


# --------------------------------------------------------------------------
# 1-2. 数値の表記
# --------------------------------------------------------------------------
def flat_delta_points(thresholds: Optional[Dict[str, Any]] = None) -> int:
    """「横ばい」と書く前週比の幅(ポイント)。config/rules_thresholds.yaml。"""
    insight = ((thresholds or {}).get("insight") or {})
    return int(insight.get("flat_delta_points", DEFAULT_FLAT_DELTA_POINTS))


def rate_text(value: Optional[float]) -> str:
    """率は整数%で書く。0.4818 → 「48%」。"""
    if value is None:
        return "データなし"
    return f"{round(float(value) * 100):d}%"


def points(value: Optional[float]) -> Optional[int]:
    """率の差分をポイントに直す。0.0182 → 2。"""
    if value is None:
        return None
    return int(round(float(value) * 100))


def points_text(delta: Optional[float], flat: int = DEFAULT_FLAT_DELTA_POINTS) -> str:
    """率の前週比。±flat ポイント以内は「横ばい」と書く。

    「横ばい」に畳んでも実数は括弧で残す。丸めた言葉だけにすると、
    翌週に閾値をまたいだとき何ポイント動いたのかが遡れなくなる。
    """
    value = points(delta)
    if value is None:
        return "前週比 データなし"
    if value == 0:
        return "前週比 横ばい(±0ポイント)"
    if abs(value) <= flat:
        return f"前週比 横ばい({value:+d}ポイント)"
    return f"前週比 {value:+d}ポイント"


def count_text(value: Optional[float], unit: str = "件") -> str:
    """実数(件数・セッション数)。率ではないので%にもポイントにもしない。"""
    if value is None:
        return "データなし"
    return f"{round(float(value)):d}{unit}"


def count_delta_text(delta: Optional[float], unit: str = "件") -> str:
    if delta is None:
        return "前週比 データなし"
    value = int(round(float(delta)))
    if value == 0:
        return f"前週比 ±0{unit}"
    return f"前週比 {value:+d}{unit}"


# stats.json に載っている小数を、そのまま本文に書かせないための置換表。
# 「本文に出てきた 0.4818 を 48% に直す」ではなく
# 「stats.json の 0.4818 という値の表示形は 48% である」という対応にしてある。
# 出所の分かっている値だけを置換するので、順位中央値(4.5)のような
# 率でない小数を巻き込まない。
_NUMBER_GUARD = r"(?<![\d.\-])"


# 率が入っている系列。mention_rate には days_observed のような
# 率でない入れ子もあるので、キーを名指しする。観測日数の 7 を率とみなして
# 「700%」に書き換えるような事故を防ぐ。
_RATE_SERIES = ("all", "pillar_a", "pillar_b")


def _is_rate(value: Any) -> bool:
    """率として書き換えてよい値か。小数で、0〜1に収まっているもの限定。"""
    return isinstance(value, float) and 0.0 <= value <= 1.0


def number_replacements(stats: Dict[str, Any],
                        flat: int = DEFAULT_FLAT_DELTA_POINTS) -> Dict[str, str]:
    """stats.json の率・差分について {生値の文字列: 表示形} を返す。"""
    out: Dict[str, str] = {}

    def add_rate(value: Any) -> None:
        if _is_rate(value):
            out.setdefault(json.dumps(value), rate_text(value))

    def add_delta(value: Any) -> None:
        if not isinstance(value, float) or not -1.0 <= value <= 1.0:
            return
        size = points(value)
        if size is None:
            return
        # 符号つきの表記(-0.0182)と、符号を本文側が持つ表記(+ 0.0182)の両方。
        out.setdefault(json.dumps(value), f"{size:+d}ポイント")
        out.setdefault(json.dumps(abs(value)), f"{abs(size):d}ポイント")

    rates = stats.get("mention_rate") or {}
    for key in _RATE_SERIES:
        series = rates.get(key)
        if not isinstance(series, dict):
            continue
        add_rate(series.get("this_week"))
        add_rate(series.get("prev_week"))
        add_delta(series.get("delta"))

    for pillar in (stats.get("sov") or {}).values():
        if not isinstance(pillar, dict):
            continue
        for entity in pillar.get("entities") or []:
            add_rate(entity.get("share"))

    # 小数だけを対象にする。整数を残すと、rule_id の「R-P7」の 7 のような
    # 数字に当たってしまう。
    out = {raw: shown for raw, shown in out.items() if "." in raw}
    # 0.5 が 0.58 の一部として置換されないよう、長い順に当てる。
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def apply_number_format(text: str, replacements: Dict[str, str]) -> str:
    """本文に残った小数の生値を表示形に置き換える。"""
    for raw, shown in replacements.items():
        text = re.sub(_NUMBER_GUARD + re.escape(raw) + r"(?![\d%])", shown, text)
    return text


_BARE_DECIMAL_RE = re.compile(r"(?<![\d.\-])0\.\d+(?![\d%])")


def bare_decimals(text: str) -> List[Tuple[int, str]]:
    """置換しきれなかった 0.xx を (行番号, 値) で返す。テストと警告用。"""
    out: List[Tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _BARE_DECIMAL_RE.finditer(line):
            out.append((number, match.group(0)))
    return out


# --------------------------------------------------------------------------
# 3. 発火パターンの日本語説明
# --------------------------------------------------------------------------
# 説明文の数値は config/rules_thresholds.yaml から組み立てる。
# ここに数を書き写すと、閾値を変えたときに説明だけが古くなる。
def pattern_gloss(thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """rule_id → 初出時に併記する日本語の定義。"""
    rules = ((thresholds or {}).get("rules") or {})

    def cfg(rule_id: str, key: str, default: Any) -> Any:
        return (rules.get(rule_id) or {}).get(key, default)

    return {
        "R-P2": f"言及消失:同一プロンプトで{cfg('R-P2', 'consecutive_absent_observations', 3)}観測日以上言及がない",
        "R-P4": f"言及率の改善:区分別の7日平均が前週比で{points(cfg('R-P4', 'mention_rate_delta', 0.10))}ポイント以上上がった",
        "R-P5": f"順位が下位のまま:順位中央値が{cfg('R-P5', 'rank_threshold', 6):g}位以下の週が{cfg('R-P5', 'consecutive_weeks', 4)}週続いている",
        "R-P7": "ネガティブ・古い情報:直近7日の回答に終了事業または誤った記述がある",
        "R-P8": "旧事業URLの引用:E-1の回答が終了事業のページを引用している",
        "R-P15": f"競合の継続出現:自社の言及がないプロンプトで同じ競合が{cfg('R-P15', 'consecutive_weeks', 4)}週連続で出ている",
        "R-DROP": f"競合構造の変化:言及シェア上位{cfg('R-DROP', 'top_n', 5)}社に半減または新規参入がある",
    }


_RULE_ID_RE = re.compile(r"R-(?:P\d+|DROP)")


_OPEN_PARENS = ("(", "（")
_CLOSE_PARENS = (")", "）")


def _already_annotated(text: str, match: "re.Match[str]") -> bool:
    """その rule_id には既に日本語の説明が付いているか。

    2つの形を認める:
      「R-P7(ネガティブ/古い情報の検知)」 … 直後に括弧が開いている
      「ネガティブ/古い情報の検知(R-P7)」 … 括弧に囲まれ、直前がラベル
    後者に説明を足すと「検知(R-P7(ネガティブ…))」と二重括弧になり、
    説明を足したせいで読めなくなる。
    """
    head = text[match.start() - 1:match.start()]
    tail = text[match.end():match.end() + 1]
    if tail in _OPEN_PARENS:
        return True
    return head in _OPEN_PARENS and tail in _CLOSE_PARENS


def gloss_first_mentions(text: str, gloss: Dict[str, str]) -> str:
    """各 rule_id の初出に「(日本語の定義)」を1度だけ足す。

    2回目以降には付けない。同じ括弧が何度も出ると本文が読めなくなる。
    モデルが自分で説明を書いている場合も足さない(初出の説明はあればよく、
    出どころがモデルか後処理かは読み手に関係がない)。
    """
    seen: set = set()
    out: List[str] = []
    cursor = 0
    for match in _RULE_ID_RE.finditer(text):
        rule_id = match.group(0)
        if rule_id in seen or rule_id not in gloss:
            continue
        seen.add(rule_id)
        out.append(text[cursor:match.end()])
        if not _already_annotated(text, match):
            out.append(f"({gloss[rule_id]})")
        cursor = match.end()
    out.append(text[cursor:])
    return "".join(out)


# --------------------------------------------------------------------------
# 4. 禁止語
# --------------------------------------------------------------------------
# 比喩。何が起きたのかを名指ししないまま雰囲気だけが伝わるので使わない。
#   押し出す → 何位から何位に落ちたのか、言及が消えたのかが分からない
#   定着     → 何週続いたのかが分からない
#   供給     → 誰が何を公開したのかが分からない
#   型       → 見出し・数値・比較表のどれを指すのかが分からない
BANNED_WORDS: Tuple[str, ...] = (
    "押し出", "定着", "供給", "型", "浮上", "急落", "様子見",
)

# 自社サービスの正式名。「Agentforce導入・定着支援」は事業名であって比喩ではない。
# この複合語の中の「定着」だけは許可する。
ALLOWED_COMPOUNDS: Tuple[str, ...] = ("定着支援",)


def _mask_allowed(text: str) -> str:
    for compound in ALLOWED_COMPOUNDS:
        text = text.replace(compound, "　" * len(compound))
    return text


def banned_words(text: str) -> List[Tuple[int, str, str]]:
    """禁止語を (行番号, 語, その行) で返す。

    tests/display_text.py の英字検査と同じ形。許可語を先に落としてから
    走査するので、判定と許可の置き場所が1か所にまとまる。
    """
    out: List[Tuple[int, str, str]] = []
    for number, line in enumerate((text or "").splitlines(), start=1):
        masked = _mask_allowed(line)
        for word in BANNED_WORDS:
            if word in masked:
                out.append((number, word, line.strip()))
    return out


# --------------------------------------------------------------------------
# 3行の箇条書き / 矢印記法
# --------------------------------------------------------------------------
_ARROW = "[→⇒]"
# 「状態→」「アクション →」を「状態:」「推奨アクション:」に直す。
_LABEL_ARROW_RE = re.compile(
    rf"^(\s*(?:[-*・]\s*)?(?:\*\*)?)(状態|原因仮説|推奨アクション|アクション)(?:\*\*)?\s*(?:{_ARROW}|[:：])\s*",
)
_ARROW_RE = re.compile(_ARROW)


def normalize_labels(text: str) -> str:
    """3行の見出しを「状態:」「原因仮説:」「推奨アクション:」に揃える。"""
    lines = []
    for line in text.splitlines():
        match = _LABEL_ARROW_RE.match(line)
        if match:
            label = LABEL_ACTION if match.group(2) in ("アクション", LABEL_ACTION) \
                else match.group(2)
            line = f"{match.group(1)}{label}: {line[match.end():].lstrip()}"
        lines.append(line)
    return "\n".join(lines)


def arrows(text: str) -> List[Tuple[int, str]]:
    """本文に残った矢印記法を (行番号, その行) で返す。"""
    return [
        (number, line.strip())
        for number, line in enumerate((text or "").splitlines(), start=1)
        if _ARROW_RE.search(line)
    ]


# --------------------------------------------------------------------------
# 5. R-P2 と R-P15 の同時発火
# --------------------------------------------------------------------------
def _evidence_prompts(stats: Dict[str, Any], rule_id: str) -> set:
    for rule in stats.get("rules") or []:
        if rule.get("rule_id") != rule_id or not rule.get("fired"):
            continue
        return {
            str(e.get("prompt_id") or "").strip()
            for e in (rule.get("evidence") or [])
            if str(e.get("prompt_id") or "").strip()
        }
    return set()


def co_fired_prompts(stats: Dict[str, Any]) -> List[str]:
    """R-P2 と R-P15 が同時に発火しているプロンプト。

    「自社が消えた」と「競合が出続けている」は同じ1つの出来事の裏表なので、
    別々の項目にすると読み手が2件の問題として数えてしまう。
    """
    return sorted(_evidence_prompts(stats, "R-P2") & _evidence_prompts(stats, "R-P15"))


_BLOCK_HEAD_RE = re.compile(r"^\*\*.*R-(?:P\d+|DROP).*\*\*\s*$")
# prompt_id は日本語に直付けされる(「E-1で旧パスが…」)。Python の \w は
# 日本語も語の文字として数えるので、\b では「1」と「で」の間に境界が立たない。
# ASCII の英数字だけを隣接禁止にする。
PROMPT_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-E]-\d(?![0-9])")


def _block_spans(lines: Sequence[str]) -> List[Tuple[int, int]]:
    """発火パターン1項目の行範囲。見出し行から次の見出し/セクションまで。"""
    spans: List[Tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not _BLOCK_HEAD_RE.match(line.strip()):
            continue
        end = len(lines)
        for later in range(index + 1, len(lines)):
            stripped = lines[later].lstrip()
            if _BLOCK_HEAD_RE.match(lines[later].strip()) or stripped.startswith("#"):
                end = later
                break
        spans.append((index, end))
    return spans


def _label_line(block: Sequence[str], label: str) -> str:
    """項目内の「状態:」などの1行から、ラベルを外した本文を返す。

    末尾の句点は落とす。統合するときに「。。」になるため。
    """
    prefix = f"{label}:"
    for line in block:
        stripped = line.strip().lstrip("-*・ ").replace("**", "")
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().rstrip("。")
    return ""


def merge_co_fired(text: str, prompt_ids: Iterable[str]) -> str:
    """同一プロンプトの R-P2 / R-P15 の項目を1つにまとめる。

    推奨アクションの順序は「競合の引用ページ調査(R-P15)のあと自社ページ更新(R-P2)」
    に固定する。自社のページを直す前に、競合が何を書いているかを見ないと
    何を足せばよいのかが決まらないため。

    日本語の定義の併記は文書全体に対して後から当てる(gloss_first_mentions)。
    ここで行ごとに当てると、統合した見出しにだけ二重に付く。
    """
    for prompt_id in prompt_ids:
        lines = text.splitlines()
        spans = _block_spans(lines)
        p2 = p15 = None
        for start, end in spans:
            block = lines[start:end]
            body = "\n".join(block)
            if prompt_id not in body:
                continue
            if "R-P2" in block[0] and p2 is None:
                p2 = (start, end)
            elif "R-P15" in block[0] and p15 is None:
                p15 = (start, end)
        if not p2 or not p15:
            continue  # 既に1項目にまとまっている

        p2_block, p15_block = lines[p2[0]:p2[1]], lines[p15[0]:p15[1]]
        merged = [
            f"**R-P2・R-P15 — {prompt_id}(自社の言及が消えた面に、同じ競合が出続けている)**",
            f"{LABEL_STATE}: " + "".join(
                f"{part}。" for part in (_label_line(p2_block, LABEL_STATE),
                                        _label_line(p15_block, LABEL_STATE)) if part
            ),
            f"{LABEL_CAUSE}: " + "".join(
                f"{part}。" for part in (_label_line(p15_block, LABEL_CAUSE),
                                        _label_line(p2_block, LABEL_CAUSE)) if part
            ),
            f"{LABEL_ACTION}: " + " ".join(
                f"{mark}{part}。" for mark, part in (
                    ("①", _label_line(p15_block, LABEL_ACTION)),
                    ("②", _label_line(p2_block, LABEL_ACTION)),
                ) if part
            ),
            "",
        ]

        first, second = sorted([p2, p15])
        rebuilt = lines[:first[0]] + merged + lines[first[1]:second[0]] + lines[second[1]:]
        text = "\n".join(rebuilt)
    return text
