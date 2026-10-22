"""experiment_freeze.py — 実験期間中の編集凍結を週次所見に反映する(2026-09-28)。

実験(〜2026-12-31)の記事は本文を変えない。週次所見の推奨アクションが
「自社ページ更新」を出すと、その対象が実験の記事だった場合に処置と区別できない
変更を促すことになる。

- 凍結対象の一覧は seo-agent と同じファイル(experiment_2x2/targets.csv・
  link_ban.csv)を読む。一覧を書き写すと、効果測定チャット側の変更と同期が切れる。
- 生成前にプロンプトで伝え(提案させない)、生成後に推奨アクション行を検査する
  (残ったものを差し替える)。実施済み施策の除外(action_log.suppress_settled)と同じ2段構え。
- 2026-10-02 に凍結を統計46本だけに縮小した(ピラー2本 agentforce-guide／agentic-crm と
  agentforce-pricing は編集可)。違反として差し替えるのは targets.csv(46本)に触れる提案だけ。
  ピラーは、提案に「46本へのリンクを足す・外す」が含まれるときだけ注意を出す(違反ではない。
  46本へのリンクの増減は seo-agent の apply_gate が書き込み時に止める)。2026-10-22 にコードを追いつかせた。
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlparse

import insight_style
from settings import EXPERIMENT_FREEZE_FILE, PROMPT_PAGE_MAP_FILE, ROOT_DIR, load_yaml

_EDIT_WORDS = re.compile(r"更新|追記|編集|書き換|書換|修正|改訂|差し替|差替|加筆|リライト")
# パスを書かない提案のうち「自社ページの更新」とみなすもの。編集の動詞に加えて
# 自社のページを指す語があり、外部への依頼・掲載の話ではないこと。
_OWN_PAGE_WORDS = re.compile(r"自社|ページ|記事|本文|FAQ|見出し|タイトル|コンテンツ|サイト")
_EXTERNAL_WORDS = re.compile(r"外部|第三者|他社|依頼|メディア|ディレクトリ|プレスリリース")
# 行に書かれたパス(/xxx/ または https://…/xxx/)。書かれていればパスで判定する。
# 日付(2026/10/05)をパスと取り違えないよう、英字を含む区切りだけを見る。
_PATH = re.compile(r"(?:https?://[^\s/]+)?(/(?=[\w-]*[A-Za-z])[\w-]+(?:/[\w-]+)*/)", re.ASCII)
# リンクを足す・外す(ピラーの注意に使う)
_LINK_CHANGE = re.compile(r"(?:リンク|導線).{0,12}?(?:追加|足|張|貼|設置|外|削除|はず|増|減|差し替|差替)"
                          r"|(?:追加|足|張|貼|設置|外|削除|はず).{0,6}?(?:リンク|導線)")
# 46本へのリンクを指す語(パスを書かない提案用)
_POOL_WORDS = re.compile(r"46本|統計|実験の記事|子記事|個別記事|関連記事|各記事|クラスター|配下の記事")
_ACTION_LINE = re.compile(
    r"^\s*(?:[-*・]|\d+[.)])?\s*(?:\*\*)?(?:推奨)?アクション(?:\*\*)?\s*[:：]\s*(.+)$"
)


@dataclass(frozen=True)
class Freeze:
    experiment_start: str
    experiment_end: str
    edit_ban: FrozenSet[str]    # 本文を変えない(2026-10-02 から統計46本)
    link_ban: FrozenSet[str]    # 新しいリンクを張らない・外さない(2026-10-02 から統計46本)
    # プロンプトID -> 対応する自社ページ(先頭が主)。config/prompt_page_map.yaml
    prompt_pages: Dict[str, Tuple[str, ...]] = None  # type: ignore[assignment]
    # ピラー(2026-10-02 に凍結を解いた。編集可・46本へのリンクの増減だけ不可)。config の pillars
    pillars: FrozenSet[str] = frozenset()
    # 2026-10-02 に凍結を解いたページ(ピラー2本・agentforce-pricing)。config の unfrozen_pages
    unfrozen: FrozenSet[str] = frozenset()

    def frozen_pages(self, prompt_id: str) -> List[str]:
        """そのプロンプトの対応ページのうち、凍結対象のもの。"""
        return [p for p in (self.prompt_pages or {}).get(prompt_id, ())
                if p.strip("/") in self.edit_ban - self.unfrozen]

    @property
    def note(self) -> str:
        """推奨アクションの代わりに書く1文。文面は本田さんの指定どおり。"""
        return (f"実験期間中(〜{self.experiment_end})のため、ページ更新を伴う施策は"
                "提案対象外。凍結対象外の施策のみ提案する")


def _slug(url: str) -> str:
    path = urlparse(url.strip()).path if "://" in url else url.strip()
    return path.strip("/").split("/")[-1] if path.strip("/") else ""


def _read_slugs(path) -> FrozenSet[str]:
    """seo-agent の CSV を読む。# で始まる注記行は飛ばす(publish_followup と同じ読み方)。"""
    with open(path, "r", encoding="utf-8-sig") as fh:
        body = "".join(line for line in fh if not line.lstrip().startswith("#"))
    slugs = {_slug(row.get("url", "")) for row in csv.DictReader(io.StringIO(body))}
    slugs.discard("")
    if not slugs:
        raise RuntimeError(f"凍結対象が1本も読めません: {path}")
    return frozenset(slugs)


def load_prompt_pages(path=PROMPT_PAGE_MAP_FILE) -> Dict[str, Tuple[str, ...]]:
    pages = (load_yaml(path) or {}).get("pages") or {}
    return {str(pid): tuple(str(p) for p in paths) for pid, paths in pages.items()}


def load(date: str, config_path=EXPERIMENT_FREEZE_FILE,
         page_map_path=PROMPT_PAGE_MAP_FILE) -> Optional[Freeze]:
    """``date``(所見の週末日)が凍結期間内なら Freeze、期間外なら None。

    期間内なのに一覧が読めない場合は例外にする。黙って制約なしで書かせると、
    凍結対象の更新を提案した所見が配信される。generate() はこれを受けて
    数値だけの所見に落とし、run は失敗として見える。
    """
    cfg = load_yaml(config_path) or {}
    start, end = str(cfg["freeze_start"]), str(cfg["experiment_end"])
    if not (start <= date <= end):
        return None
    return Freeze(
        experiment_start=str(cfg["experiment_start"]),
        experiment_end=end,
        edit_ban=_read_slugs(ROOT_DIR / cfg["edit_ban_file"]),
        link_ban=_read_slugs(ROOT_DIR / cfg["link_ban_file"]),
        prompt_pages=load_prompt_pages(page_map_path),
        pillars=frozenset(str(s).strip("/") for s in cfg.get("pillars") or ()),
        unfrozen=frozenset(str(s).strip("/") for s in cfg.get("unfrozen_pages") or ()),
    )


def prompt_block(freeze: Optional[Freeze]) -> str:
    """generate_insight のユーザープロンプトに差し込む制約。期間外は空文字。"""
    if freeze is None:
        return ""
    pages = "\n".join(f"- /{slug}/" for slug in sorted(freeze.edit_ban))
    open_pages = sorted(freeze.unfrozen - freeze.edit_ban)
    open_block = (
        "- 次のページは 2026-10-02 に凍結を解いた(編集してよい)。ただし凍結対象へのリンクを足す・外すことはしない:"
        + "、".join(f"/{s}/" for s in open_pages) + "\n"
    ) if open_pages else ""
    mapped = [f"- {pid}: " + "、".join(freeze.frozen_pages(pid))
              for pid in sorted(freeze.prompt_pages or {}) if freeze.frozen_pages(pid)]
    mapped_block = (
        "\n次のプロンプトは、対応する自社ページが凍結対象です。"
        "このプロンプトに対する「自社ページ更新」は、パスを書かなくても凍結対象の更新として扱います。\n"
        + "\n".join(mapped) + "\n"
    ) if mapped else ""
    return f"""
# 実験期間の制約(実験期間 {freeze.experiment_start}〜{freeze.experiment_end})
次のページは実験の対象のため、{freeze.experiment_end} まで本文を変えません(編集凍結)。
- 本文・タイトル・meta・スキーマの変更、追記(逆リンクの追記を含む)をする施策は提案しない。
- 新しいリンクの張り先にする施策、リンクを外す施策も提案しない。
{open_block}- 統合項目の「②自社ページ更新」の対象が凍結対象にあたる場合も同じ扱いにする。
凍結対象にあたる施策が本来の打ち手になる項目では、推奨アクションの行を次の1文で始め、
続けて凍結対象外で打てる施策を1つだけ書く(外部掲載の獲得、第三者メディアへの情報提供、
凍結対象外のページの更新など。プレイブックに沿うものに限る)。代わりが無ければこの1文だけにする。
「{freeze.note}」
推奨アクションで対象ページを書くときは、パス(例: /{sorted(freeze.link_ban)[0]}/)で書く。
{mapped_block}
凍結対象({len(freeze.edit_ban)}本):
{pages}
"""


def _mentions(line: str, slug: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(slug)}(?![A-Za-z0-9_-])", line) is not None


def _pillars_in(line: str, freeze: Freeze) -> List[str]:
    """行に出てくるピラー(パス)。パスが無く「ピラー」とだけ書かれていれば ["ピラー"]。"""
    named = [s for s in sorted(freeze.pillars) if _mentions(line, s)]
    return named or (["ピラー"] if "ピラー" in line else [])


def _is_pillar_link_change(line: str, freeze: Freeze) -> bool:
    """ピラーのリンクを足す・外す提案か(46本へのリンクを指しうるもの)。"""
    return bool(_pillars_in(line, freeze)) and _LINK_CHANGE.search(line) is not None


def _edits_the_article(line: str, slug: str) -> bool:
    """その記事の後ろ(次のパスか文の終わりまで)に、リンク以外の編集の動詞があるか。名前が何度出ても全部見る。"""
    for m in re.finditer(rf"(?<![A-Za-z0-9_-]){re.escape(slug)}(?![A-Za-z0-9_-])", line):
        rest = re.split(r"[。、]|https?://|/(?=[\w-]*[A-Za-z])[\w-]+/", line[m.end():], maxsplit=1)[0]
        if _EDIT_WORDS.search(rest) is not None and "リンク" not in rest:
            return True
    return False


def violations(line: str, freeze: Freeze) -> List[str]:
    """推奨アクション1行が触れている凍結対象(統計46本・targets.csv)。

    46本は、更新でもリンクでも名前が出た時点で違反(これまでどおり)。
    例外：ピラーのリンクを足す・外す提案の中で、46本がリンク先として出てくるだけなら違反にせず
    注意にする(pillar_cautions)。その行でも、46本そのものを編集する書き方なら違反。
    ピラー2本・agentforce-pricing への編集の提案は違反にしない(2026-10-02 に凍結を解いた)。
    """
    pillar_link = _is_pillar_link_change(line, freeze)
    found = []
    for slug in sorted(freeze.edit_ban - freeze.unfrozen):
        if not _mentions(line, slug):
            continue
        if pillar_link and not _edits_the_article(line, slug):
            continue
        found.append(slug)
    return found


def pillar_cautions(report_md: str, freeze: Optional[Freeze]) -> List[str]:
    """ピラーの推奨アクションに「46本へのリンクを足す・外す」が含まれる行の注意(違反ではない)。

    46本の記事名(パス)があるか、パスが無くても 46本・子記事・関連記事などの語があるときに出す。
    期間外(freeze=None)は出さない。"""
    if freeze is None:
        return []
    out = []
    for line in report_md.splitlines():
        if not _ACTION_LINE.match(line) or freeze.note in line or not _is_pillar_link_change(line, freeze):
            continue
        pool = [s for s in sorted(freeze.link_ban) if _mentions(line, s)]
        if not (pool or _POOL_WORDS.search(line)):
            continue
        where = "・".join(p if p == "ピラー" else f"/{p}/" for p in _pillars_in(line, freeze))
        target = "・".join(f"/{s}/" for s in pool) or "46本"
        out.append(f"注意(違反ではない): ピラー({where})の推奨アクションに、46本({target})へのリンクを足す・外す内容がある。"
                   f"ピラーの編集は可だが、46本へのリンクの増減は実験期間中(〜{freeze.experiment_end})不可で、"
                   f"seo-agent の apply_gate が書き込み時に止める: {line.strip()[:80]}")
    return out


def _is_own_page_update(line: str) -> bool:
    return (_EDIT_WORDS.search(line) is not None
            and _OWN_PAGE_WORDS.search(line) is not None
            and _EXTERNAL_WORDS.search(line) is None)


def mapped_violations(line: str, prompt_ids: List[str], freeze: Freeze) -> List[str]:
    """パスを書かない「自社ページ更新」が、対応表で凍結対象に当たるか。

    行にパスが書かれていればパスの判定(violations)に任せる。
    「A-3 の /service/agentforce-support/ を更新」は凍結対象外の副ページなので通す。
    """
    if _PATH.search(line) or not _is_own_page_update(line):
        return []
    return [p.strip("/") for pid in prompt_ids for p in freeze.frozen_pages(pid)]


def suppress_frozen(report_md: str, freeze: Optional[Freeze]
                    ) -> Tuple[str, List[str], List[str]]:
    """凍結対象に触れる推奨アクションを、凍結の注記に差し替える。

    返すのは (差し替え後の本文, 差し替えた説明のリスト, 書き込んだ本文のリスト)。
    3つめは action_log に提案として登録しないために使う(suppress_settled と同じ)。
    モデルが自分で書いた注記だけの行も登録しないよう、注記そのものも3つめに入れる。
    """
    if freeze is None:
        return report_md, [], []
    lines = report_md.splitlines()
    notes: List[str] = []
    # 行に prompt_id が無ければ、その行が属する項目(見出し)の prompt_id を使う
    block_prompts: Dict[int, List[str]] = {}
    for start, end in insight_style._block_spans(lines):
        ids = sorted(set(insight_style.PROMPT_ID_RE.findall("\n".join(lines[start:end]))))
        for i in range(start, end):
            block_prompts[i] = ids
    for i, line in enumerate(lines):
        if not _ACTION_LINE.match(line):
            continue
        # モデルが自分で書いた注記(と、続けて書いた代替施策)は判定しない。
        # 注記の文面に「ページ更新」が含まれるため、見ると代替施策ごと消してしまう。
        if freeze.note in line:
            continue
        prompt_ids = (sorted(set(insight_style.PROMPT_ID_RE.findall(line)))
                      or block_prompts.get(i, []))
        hit = violations(line, freeze) or mapped_violations(line, prompt_ids, freeze)
        if not hit:
            continue
        indent = line[:len(line) - len(line.lstrip())]
        lines[i] = f"{indent}{insight_style.LABEL_ACTION}: {freeze.note}"
        notes.append(f"{', '.join('/' + s + '/' for s in hit)}: {line.strip()[:80]}")
    return "\n".join(lines), notes, [freeze.note]
