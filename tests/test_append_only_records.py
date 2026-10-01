"""実験日誌と介入ログは「追記のみ」(2026-10-01).

seo-agent で判定スクリプトが CSV の note 列を空で上書きし、手書きの記録が消えた。
dashboard の記録2つは、一度書いた行を消さない。訂正は行を消さず、
追記(行の末尾に訂正を足す・新しい行を足す)か取り消し線(~~…~~)で行う。

このテストは git の履歴と作業中の変更の両方を見る。
- 作業中の変更(HEAD との差)に、既存の行が減る変更があれば落ちる(コミット前に止める)
- 履歴の各コミットでも同じことを確かめる。ルールより前の訂正(取り消し線を使わずに
  書き換えたもの。いずれも明示の訂正か、待ち項目の確定で、記録の消失ではない)は
  KNOWN_REWRITES に理由つきで載せて除く
"""
import csv
import io
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIARY = "output/reports/experiment47_diary.md"
INTERVENTIONS = "output/interventions.csv"

# ルール(2026-10-01)より前の、取り消し線を使わない書き換え。2026-10-01 の点検で
# git の全履歴を見て、すべて意図した訂正・確定だったことを確かめた(日誌に記録)。
KNOWN_REWRITES = {
    DIARY: {
        "24ca4f5": "ビフォー基準値の提案を決定(9/17 以降のみ)に置き換え",
        "22deab6": "ビフォー基準値の見出しに「確定」を付けて箇条を展開",
        "843cc6b": "待ち項目の「全追記の表」をファイル名に具体化",
        "c2f84b9": "待ち項目を取り込み仕様(確定)に置き換え",
        "aeafbd5": "「（9/28 記入）」の欄を割付の結果で埋めた",
    },
    INTERVENTIONS: {
        "fb7ad4c": "I-07 の訂正件数 3件→2件(コミットで明示の訂正)",
        "bdbcc47": "I-04・I-05 の要確認を回答で埋めた(注記で説明)",
        "abe861a": "I-07 の訂正件数 2件→1件(vibes の訂正見送り)",
        "b9e9264": "I-07 の note 6本→7本(コミットで明示の修正)",
    },
}


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True,
                          ).stdout.decode("utf-8")


def _has_git():
    try:
        _git("rev-parse", "--is-inside-work-tree")
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git の履歴が無い環境")


def _plain(text):
    """取り消し線の記号を外す。~~旧~~ 新 は「旧 新」になり、旧の文字は残っている。"""
    return text.replace("~~", "")


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------
def _meaningful(line):
    s = line.strip()
    return bool(s) and set(s) - set("-|: ")      # 空行・区切り線(--- や |---|)は数えない


def lost_text_lines(old, new):
    """old にあって new で消えた行。行がそのまま残るか、取り消し線・追記を足して残れば消えていない。"""
    new_lines = [_plain(l).strip() for l in new.splitlines()]
    exact = set(new_lines)
    lost = []
    for line in old.splitlines():
        if not _meaningful(line):
            continue
        core = _plain(line).strip()
        if core in exact or any(core in n for n in new_lines):
            continue
        lost.append(line.strip())
    return lost


def _csv_rows(text):
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(body))))


def lost_csv_rows(old, new, key="intervention_id"):
    """介入ログ。行は id で突き合わせ、旧い値が新しいセルに残っているかを見る。

    列を足すのは可(既存の列は残すこと)。セルの訂正は、旧い値を取り消し線で残すか、
    後ろに追記する。コメント行(#)は日誌と同じく行単位で見る。
    """
    lost = []
    comments = lambda t: "\n".join(l for l in t.splitlines() if l.lstrip().startswith("#"))
    lost += lost_text_lines(comments(old), comments(new))
    old_rows, new_rows = _csv_rows(old), {r[key]: r for r in _csv_rows(new)}
    if old_rows:
        missing_cols = [c for c in old_rows[0] if c not in next(iter(new_rows.values()), {})]
        lost += [f"列 {c}" for c in missing_cols]
    for row in old_rows:
        cur = new_rows.get(row[key])
        if cur is None:
            lost.append(f"行 {row[key]}")
            continue
        for col, value in row.items():
            if value and col in cur and _plain(value).strip() not in _plain(cur[col] or ""):
                lost.append(f"{row[key]}.{col}: {value}")
    return lost


CHECKS = {DIARY: lost_text_lines, INTERVENTIONS: lost_csv_rows}


# --------------------------------------------------------------------------
# テスト
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", sorted(CHECKS))
def test_uncommitted_changes_do_not_remove_lines(path):
    """作業中の変更で既存の行を消していない(コミットの前に止める)。"""
    committed = _git("show", f"HEAD:{path}")
    current = (ROOT / path).read_text(encoding="utf-8")
    assert CHECKS[path](committed, current) == []


@pytest.mark.parametrize("path", sorted(CHECKS))
def test_no_commit_in_history_removed_lines(path):
    commits = _git("log", "--format=%h", "--reverse", "--", path).split()
    problems = []
    for prev, cur in zip(commits, commits[1:]):
        if cur in KNOWN_REWRITES[path]:
            continue
        lost = CHECKS[path](_git("show", f"{prev}:{path}"), _git("show", f"{cur}:{path}"))
        if lost:
            problems.append(f"{cur}: {lost[:3]}")
    assert problems == [], problems


# 判定そのもののテスト(履歴が無くても意味がある)
def test_strikethrough_and_appended_corrections_are_not_losses():
    old = "- I-07:訂正3件\n- 待ち:全追記の表\n"
    new = "- I-07:~~訂正3件~~ 訂正2件(9/26 訂正)\n- 待ち:全追記の表(9/25 取り込み済み)\n- 新しい行\n"
    assert lost_text_lines(old, new) == []


def test_a_rewritten_or_deleted_line_is_a_loss():
    old = "- I-07:訂正3件\n- 9/16 以降を使う\n"
    new = "- I-07:訂正2件\n"
    assert lost_text_lines(old, new) == ["- I-07:訂正3件", "- 9/16 以降を使う"]


def test_csv_cells_must_keep_their_old_values():
    head = "date,intervention_id,description,note\n"
    old = head + "2026-09-25,I-07,訂正3件,\n2026-09-26,I-08,止め,\n"
    blanked = head + "2026-09-25,I-07,訂正3件,\n"                       # 行が消えた
    rewritten = head + "2026-09-25,I-07,訂正2件,\n2026-09-26,I-08,止め,\n"   # 値の書き換え
    corrected = head + "2026-09-25,I-07,~~訂正3件~~ 訂正2件,9/26 訂正\n2026-09-26,I-08,止め,済\n"
    assert lost_csv_rows(old, blanked) == ["行 I-08"]
    assert lost_csv_rows(old, rewritten) == ["I-07.description: 訂正3件"]
    assert lost_csv_rows(old, corrected) == []


def test_a_note_column_cannot_be_blanked():
    """seo-agent で起きた型そのもの。"""
    head = "date,intervention_id,note\n"
    assert lost_csv_rows(head + "2026-09-25,I-07,手書きの記録\n",
                         head + "2026-09-25,I-07,\n") == ["I-07.note: 手書きの記録"]
