"""action_log.py — 施策記録(Phase 5 §4 / §5).

施策の一覧はシートタブ ``action_log`` にあり、**状態列は本田さんがシート上で
直接編集する**。アプリからは書かない。このモジュールが書くのは、週次所見が
出した推奨アクションを「提案中」で追記するところだけ(§5)。

重複防止:同一内容 + 同一 rule_id が未完了状態で既にあれば追記しない。
同じ提案が毎週積み上がると一覧が読めなくなるため。

もう一段の重複防止が §A(Phase 7)。既に着手済みの施策と同じ面・同じ根拠の
提案を、所見文の側で出させない。追記されないだけでは「今週やること」として
本文に毎週書かれ続けてしまい、読み手が着手済みかどうかを判別できない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import insight_style
from verdicts import (
    OPEN_STATUSES,
    SETTLED_STATUSES,
    STATUS_APPROVED,
    STATUS_DONE,
    STATUS_MEASURING,
    STATUS_ON_HOLD,
    STATUS_PROPOSED,
)

ID_PREFIX = "A-"
ID_PATTERN = re.compile(r"^A-(\d+)$")

# §4 の初期データ。既に同じ action_id があれば upsert で上書きされる。
SEED_ROWS: List[Dict[str, Any]] = [
    {"action_id": "A-001", "優先度": "高",
     "内容": "AUBA・イプロスの外部プロフィール更新", "対象": "E-1",
     "根拠rule_id": "R-P7", "状態": STATUS_MEASURING,
     "提案日": "2026-08-08", "実施日": "2026-08-11", "判断期限": "2026-09-07"},
    {"action_id": "A-002", "優先度": "高",
     "内容": "/marketing-automation-btob/ 過去形化改修", "対象": "E-1",
     "根拠rule_id": "R-P7", "状態": STATUS_MEASURING,
     "提案日": "2026-08-17", "実施日": "2026-08-18", "判断期限": "2026-09-07"},
    {"action_id": "A-003", "優先度": "高",
     "内容": "/btob-marketing-strategy/ 過去形化改修", "対象": "E-1",
     "根拠rule_id": "R-P8", "状態": STATUS_MEASURING,
     "提案日": "2026-08-24", "実施日": "2026-08-24", "判断期限": "2026-09-07"},
    {"action_id": "A-004", "優先度": "高",
     "内容": "/about/ Organization構造化データ実装", "対象": "E-1",
     "根拠rule_id": "R-P8", "状態": STATUS_MEASURING,
     "提案日": "2026-08-24", "実施日": "2026-08-24", "判断期限": "—"},
    {"action_id": "A-005", "優先度": "中",
     "内容": "問い合わせフォームに認知経路を追加", "対象": "KGI",
     "根拠rule_id": "—", "状態": STATUS_MEASURING,
     "提案日": "2026-08-24", "実施日": "2026-08-24", "判断期限": "—"},
    {"action_id": "A-006", "優先度": "中",
     "内容": "外部プロフィール第2弾(ランサーズ・innovations-i・PR TIMES)",
     "対象": "E-1", "根拠rule_id": "R-P7", "状態": STATUS_ON_HOLD,
     "提案日": "2026-08-24", "実施日": "—", "判断期限": "2026-09-07"},
    {"action_id": "A-007", "優先度": "中",
     "内容": "B-3対応の一次情報ページ更新", "対象": "B-3",
     "根拠rule_id": "R-P2", "状態": STATUS_ON_HOLD,
     "提案日": "2026-08-24", "実施日": "—", "判断期限": "2026-08-31"},
]


def next_action_id(rows: Sequence[Dict[str, Any]]) -> str:
    numbers = []
    for row in rows:
        match = ID_PATTERN.match(str(row.get("action_id", "")).strip())
        if match:
            numbers.append(int(match.group(1)))
    return f"{ID_PREFIX}{(max(numbers) + 1) if numbers else 1:03d}"


def _normalize(text: Any) -> str:
    """重複判定用のゆるい正規化。空白と記号ゆれを吸収する。"""
    return re.sub(r"[\s　・,、。.／/]+", "", str(text or "")).lower()


def is_duplicate(content: Any, rule_id: Any,
                 rows: Sequence[Dict[str, Any]]) -> bool:
    """同一内容 + 同一rule_id が未完了状態で存在するか(§5)。"""
    target = (_normalize(content), _normalize(rule_id))
    for row in rows:
        if str(row.get("状態", "")).strip() not in OPEN_STATUSES:
            continue
        if (_normalize(row.get("内容")), _normalize(row.get("根拠rule_id"))) == target:
            return True
    return False


def propose(
    proposals: Sequence[Dict[str, Any]],
    existing: Sequence[Dict[str, Any]],
    date: str,
) -> List[Dict[str, Any]]:
    """追記すべき行だけを返す。既存と重複するものは落とす。

    ``proposals`` は {"内容", "対象", "根拠rule_id", "優先度"} を持つ辞書の列。
    """
    rows = list(existing)
    new_rows: List[Dict[str, Any]] = []
    for proposal in proposals:
        content = str(proposal.get("内容", "")).strip()
        if not content:
            continue
        rule_id = str(proposal.get("根拠rule_id", "") or "—").strip()
        if is_duplicate(content, rule_id, rows) or is_duplicate(content, rule_id, new_rows):
            continue
        row = {
            "action_id": next_action_id(rows + new_rows),
            "優先度": str(proposal.get("優先度", "中")).strip() or "中",
            "内容": content,
            "対象": str(proposal.get("対象", "—")).strip() or "—",
            "根拠rule_id": rule_id,
            "状態": STATUS_PROPOSED,
            "提案日": date,
            "実施日": "—",
            "判断期限": str(proposal.get("判断期限", "—")).strip() or "—",
        }
        new_rows.append(row)
    return new_rows


# --------------------------------------------------------------------------
# 所見文からの抽出(§5)
# --------------------------------------------------------------------------
# 見出しは「推奨アクション:」に統一したが、過去の所見は「アクション:」で
# 書かれている。読む側は両方を受ける(書く側だけを揃える)。
_ACTION_LINE = re.compile(
    r"^\s*(?:[-*・]|\d+[.)])?\s*(?:\*\*)?(?:推奨)?アクション(?:\*\*)?\s*[:：]\s*(.+)$"
)
_RULE_IN_HEADING = re.compile(r"(R-[A-Z0-9]+)")


def extract_proposals(report_md: str) -> List[Dict[str, Any]]:
    """週次所見の「アクション:」行を拾う。

    所見文の形式は変更しない(§5)ので、既に出力されている行を読むだけ。
    直近に出てきた rule_id を根拠として紐づける。
    """
    proposals: List[Dict[str, Any]] = []
    current_rule = "—"
    for line in (report_md or "").splitlines():
        found = _RULE_IN_HEADING.search(line)
        if found:
            current_rule = found.group(1)
        match = _ACTION_LINE.match(line)
        if match:
            content = match.group(1).strip().rstrip("。")
            if content:
                proposals.append({
                    "内容": content[:120], "対象": "—",
                    "根拠rule_id": current_rule, "優先度": "中",
                })
    return proposals


# --------------------------------------------------------------------------
# 実施済み施策の再提案の抑止(Phase 7 §A)
# --------------------------------------------------------------------------
def settled_actions(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """状態が決着済み(承認/実施済み・効果測定中/完了)の施策。"""
    return [r for r in rows
            if str(r.get("状態", "")).strip() in SETTLED_STATUSES]


def settled_note(row: Dict[str, Any]) -> str:
    """所見に1行で書く「これは既にやってある」。

    状態をそのまま出す。「実施済み」とだけ書くと、効果測定の途中なのか
    判断期限が過ぎたのかが読み取れない。
    """
    action_id = str(row.get("action_id", "")).strip() or "—"
    status = str(row.get("状態", "")).strip()
    done = str(row.get("実施日", "")).strip() or "—"
    if status == STATUS_APPROVED:
        proposed = str(row.get("提案日", "")).strip() or "—"
        return f"承認済み({action_id}・{proposed})。着手前のため新たな提案はしない"
    tail = "完了" if status == STATUS_DONE else "効果測定中"
    return f"実施済み({action_id}・{done})。{tail}"


def _targets_in(text: str) -> set:
    """本文に出てくる対象(prompt_id と KGI)。action_log の対象列と突き合わせる。"""
    found = set(insight_style.PROMPT_ID_RE.findall(text))
    if "KGI" in text:
        found.add("KGI")
    return found


def suppress_settled(report_md: str,
                     action_rows: Sequence[Dict[str, Any]]
                     ) -> Tuple[str, List[str]]:
    """決着済みの施策と同じ「根拠rule_id + 対象」の推奨アクションを差し替える。

    同じ面に同じ根拠でもう手を打ってあるなら、今週やることではない。
    行を消すのではなく「実施済み(A-00N・実施日)」に置き換えるので、
    その面に対して何をしたかは所見の上で追える。

    返すのは (差し替え後の本文, 差し替えた説明のリスト)。
    """
    settled = settled_actions(action_rows)
    if not settled:
        return report_md, []

    lines = report_md.splitlines()
    notes: List[str] = []
    # 後ろの項目から処理する。行を1本足す場合があり、前から回すと
    # 先に取った行範囲がずれる。
    for start, end in reversed(insight_style._block_spans(lines)):
        block = lines[start:end]
        rule_ids = set(_RULE_IN_HEADING.findall(block[0]))
        targets = _targets_in("\n".join(block))
        if not rule_ids:
            continue

        match = next(
            (r for r in settled
             if str(r.get("根拠rule_id", "")).strip() in rule_ids
             and str(r.get("対象", "")).strip() in targets),
            None,
        )
        if match is None:
            continue

        note = settled_note(match)
        replaced = False
        for offset, line in enumerate(block):
            found = _ACTION_LINE.match(line)
            if not found:
                continue
            indent = line[:len(line) - len(line.lstrip())]
            lines[start + offset] = f"{indent}{insight_style.LABEL_ACTION}: {note}"
            replaced = True
            break
        if not replaced:
            lines.insert(end, f"{insight_style.LABEL_ACTION}: {note}")
        notes.append(f"{'/'.join(sorted(rule_ids))} × {'/'.join(sorted(targets))}: {note}")

    notes.reverse()   # 後ろから回したので、本文と同じ順に戻す
    return "\n".join(lines), notes


def prompt_block(action_rows: Sequence[Dict[str, Any]]) -> str:
    """決着済み施策の一覧。generate_insight のプロンプトに差し込む。

    後処理で消すより先に、そもそもモデルに提案させないほうがよい。
    削られる前提で書かせると、限られた3件の枠を使い切ってしまう。
    """
    settled = settled_actions(action_rows)
    if not settled:
        return "(まだ着手済みの施策はありません)"
    return "\n".join(
        f"- {str(r.get('action_id', '')).strip()} | 対象 {str(r.get('対象', '—')).strip()}"
        f" | 根拠 {str(r.get('根拠rule_id', '—')).strip()}"
        f" | 状態 {str(r.get('状態', '')).strip()}"
        f" | 実施日 {str(r.get('実施日', '—')).strip()}"
        f" | {str(r.get('内容', '')).strip()}"
        for r in settled
    )


def sync_from_report(report_md: str, date: str,
                     existing: Optional[Sequence[Dict[str, Any]]] = None
                     ) -> List[Dict[str, Any]]:
    """所見文から提案を抽出し、追記すべき行を返す(書き込みは呼び出し側)。"""
    if existing is None:
        import sheets_writer

        existing = sheets_writer.read_action_log()
    return propose(extract_proposals(report_md), existing, date)


def main() -> None:
    ap = argparse.ArgumentParser(description="action_log の初期データ投入")
    ap.add_argument("--seed", action="store_true", help="§4の初期データを投入する")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.seed:
        ap.error("--seed を指定してください")

    if args.dry_run:
        for row in SEED_ROWS:
            print(row)
        print(f"[dry-run] {len(SEED_ROWS)} 行(書き込みなし)")
        return

    import sheets_writer

    sheets_writer.write_action_log(SEED_ROWS)
    print(f"[ok] action_log に初期データ {len(SEED_ROWS)} 行を投入しました")


if __name__ == "__main__":
    main()
