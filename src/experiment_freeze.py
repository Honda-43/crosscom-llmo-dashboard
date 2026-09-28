"""experiment_freeze.py — 実験期間中の編集凍結を週次所見に反映する(2026-09-28)。

実験(〜2026-12-31)の記事は本文を変えない。週次所見の推奨アクションが
「自社ページ更新」を出すと、その対象が実験の記事だった場合に処置と区別できない
変更を促すことになる。

- 凍結対象の一覧は seo-agent と同じファイル(experiment_2x2/targets.csv・
  link_ban.csv)を読む。一覧を書き写すと、効果測定チャット側の変更と同期が切れる。
- 生成前にプロンプトで伝え(提案させない)、生成後に推奨アクション行を検査する
  (残ったものを差し替える)。実施済み施策の除外(action_log.suppress_settled)と同じ2段構え。
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Tuple
from urllib.parse import urlparse

import insight_style
from settings import EXPERIMENT_FREEZE_FILE, ROOT_DIR, load_yaml

# ピラーの「張り先にする」は可、「本文を触る」は不可。ピラーだけは行の動詞で分ける。
_EDIT_WORDS = re.compile(r"更新|追記|編集|書き換|書換|修正|改訂|差し替|差替|加筆|リライト")
_ACTION_LINE = re.compile(
    r"^\s*(?:[-*・]|\d+[.)])?\s*(?:\*\*)?(?:推奨)?アクション(?:\*\*)?\s*[:：]\s*(.+)$"
)


@dataclass(frozen=True)
class Freeze:
    experiment_start: str
    experiment_end: str
    edit_ban: FrozenSet[str]    # 本文を変えない(49本)
    link_ban: FrozenSet[str]    # 新しいリンクの張り先にしない(47本)

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


def load(date: str, config_path=EXPERIMENT_FREEZE_FILE) -> Optional[Freeze]:
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
    )


def prompt_block(freeze: Optional[Freeze]) -> str:
    """generate_insight のユーザープロンプトに差し込む制約。期間外は空文字。"""
    if freeze is None:
        return ""
    pages = "\n".join(
        f"- /{slug}/" + ("" if slug in freeze.link_ban else "(ピラー:張り先にするのは可)")
        for slug in sorted(freeze.edit_ban)
    )
    return f"""
# 実験期間の制約(実験期間 {freeze.experiment_start}〜{freeze.experiment_end})
次のページは実験の対象のため、{freeze.experiment_end} まで本文を変えません(編集凍結)。
- 本文・タイトル・meta・スキーマの変更、追記(逆リンクの追記を含む)をする施策は提案しない。
- 新しいリンクの張り先にする施策も提案しない(「ピラー」と書いたページだけは張り先にしてよい)。
- 統合項目の「②自社ページ更新」の対象が凍結対象にあたる場合も同じ扱いにする。
凍結対象にあたる施策が本来の打ち手になる項目では、推奨アクションの行を次の1文で始め、
続けて凍結対象外で打てる施策を1つだけ書く(外部掲載の獲得、第三者メディアへの情報提供、
凍結対象外のページの更新など。プレイブックに沿うものに限る)。代わりが無ければこの1文だけにする。
「{freeze.note}」
推奨アクションで対象ページを書くときは、パス(例: /{sorted(freeze.link_ban)[0]}/)で書く。

凍結対象({len(freeze.edit_ban)}本):
{pages}
"""


def _mentions(line: str, slug: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(slug)}(?![A-Za-z0-9_-])", line) is not None


def violations(line: str, freeze: Freeze) -> List[str]:
    """推奨アクション1行が触れている凍結対象。

    張り先禁止(47本)は、更新でもリンクでも名前が出た時点で違反。
    ピラーは編集の動詞があるときだけ違反(張り先にするのは可)。
    """
    found = []
    for slug in sorted(freeze.edit_ban):
        if not _mentions(line, slug):
            continue
        if slug in freeze.link_ban or _EDIT_WORDS.search(line):
            found.append(slug)
    return found


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
    for i, line in enumerate(lines):
        if not _ACTION_LINE.match(line):
            continue
        hit = violations(line, freeze)
        if not hit:
            continue
        indent = line[:len(line) - len(line.lstrip())]
        lines[i] = f"{indent}{insight_style.LABEL_ACTION}: {freeze.note}"
        notes.append(f"{', '.join('/' + s + '/' for s in hit)}: {line.strip()[:80]}")
    return "\n".join(lines), notes, [freeze.note]
