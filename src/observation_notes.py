"""observation_notes.py — 観測の変更に伴う誤読防止の注記(2026-10-06).

週次所見(§5)・アプリ(R2 言及率推移・R3 ネガ検知)・Looker(lk_events と「使い方」ページ)で同じ文言を使う。
文言を変えるときはここだけを変える(README にも同じ文を記録している)。

1. R-P7(ネガティブ/古い情報)の誤読防止:Claude を計画的に停止している間(settings.claude_stopped)
   9/22〜10/03 の否定の検知はすべて Claude の E-1 回答だった。Claude を止めたので、R-P7 が発火しなくなっても
   古い情報が解消したとは限らない(アラートは「発火が止まったこと」を見る設計のため、とくに誤読しやすい)
2. 言及率の母数の変更:2026-10-06 から日次の観測は Gemini の7本だけ(それまで Claude と合わせて14本)
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from settings import claude_stopped

R_P7_NOTE = ("R-P7(ネガティブ/古い情報)はGeminiの観測のみで判定している。"
             "2026-10-06以前の検知はすべてClaudeのE-1回答であり、"
             "Geminiでの最後の検知は2026-09-19。発火しないことを解消と読まないこと")

DENOMINATOR_CHANGE_DATE = "2026-10-06"
DENOMINATOR_SHORT = "母数14→7本"
DENOMINATOR_NOTE = ("2026-10-06 を境に言及率の母数が14本→7本に変わった"
                    "(Claude の観測を停止し Gemini のみ)。前後の水準を単純比較しないこと")


def r_p7_note_active(date: Optional[str] = None) -> bool:
    """R-P7 の注記を出すか(Claude を計画的に止めている間)。"""
    return claude_stopped(date)


def straddles_denominator_change(start: str, end: str) -> bool:
    """期間(start〜end)が母数の変わった日をまたぐか(前日以前と当日以後の両方を含む)。"""
    return str(start)[:10] < DENOMINATOR_CHANGE_DATE <= str(end)[:10]


def weekly_section5_lines(report_date: str) -> List[str]:
    """週次所見の §5 に固定で入れる行(箇条書きの「- 」付き)。"""
    lines = []
    if r_p7_note_active(report_date):
        lines.append(f"- {R_P7_NOTE}")
    end = dt.date.fromisoformat(str(report_date)[:10])
    prev_start = (end - dt.timedelta(days=13)).isoformat()      # 前週の初日(前週比の比較範囲の始まり)
    if straddles_denominator_change(prev_start, end.isoformat()):
        lines.append(f"- {DENOMINATOR_NOTE}")
    return lines


def ensure_section5(report_md: str, lines: List[str], heading: str = "## 5.") -> str:
    """§5 の末尾に ``lines`` を入れる(既にある行は足さない)。§5 が無ければ末尾に足す。"""
    missing = [l for l in lines if l.lstrip("- ").strip() not in report_md]
    if not missing:
        return report_md
    rows = report_md.rstrip("\n").split("\n")
    start = next((i for i, l in enumerate(rows) if l.startswith(heading)), None)
    if start is None:
        return "\n".join(rows + [""] + missing) + "\n"
    end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")), len(rows))
    while end > start + 1 and not rows[end - 1].strip():
        end -= 1
    return "\n".join(rows[:end] + missing + rows[end:]) + "\n"
