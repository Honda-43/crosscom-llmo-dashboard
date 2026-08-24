"""notify_slack.py — daily Slack alert (Phase 1 §4) and weekly report (Phase 2 §4).

The daily post shows **state, not detail** — detail lives behind the links at
the bottom. Three tiers:

1. ``📊 LLMO日次 | 日付``
2. one status line: 言及率（前日比の矢印付き） / SoV首位 / ネガ検知件数
3. change events, one line each — nothing else. A negative detection shows the
   *kind* of problem and how many days it has run, never the ``negative_detail``
   body: that text is long, repeats almost verbatim every day, and drowns the
   line that matters.

A day with no change events still posts, with 「変化なし」 on the third tier.
The status line is the point: a silent day is indistinguishable from a broken
pipeline, and the thing worth watching is the day a detection *stops*.

The weekly report keeps its own long format (``notify_weekly``) — it is read
once a week for depth, while this is read daily for state.

A missing webhook logs a warning and returns normally so the pipeline never
fails just because Slack is not configured.

Manual smoke test::

    SLACK_WEBHOOK_URL=... python notify_slack.py --test
    SLACK_WEBHOOK_URL=... python notify_slack.py --test-weekly
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

import analyze_diff
from settings import LOOKER_STUDIO_URL, SLACK_WEBHOOK_URL, spreadsheet_url

_MAX_ITEMS_PER_LINE = 12
ENTITY_PROMPT_ID = "E-1"


def _label(prompt_id: Any, model: Any) -> str:
    return f"{prompt_id or '?'}({model or '?'})"


# --------------------------------------------------------------------------
# 2行目 — サマリ
# --------------------------------------------------------------------------
def _rate_of(rows: Iterable[Dict[str, Any]]) -> Optional[float]:
    """E-1とエラー行を除いた言及率。build_summary と同じ定義に揃えている。"""
    valid = [
        r for r in rows
        if not r.get("error")
        and str(r.get("prompt_id") or "") != ENTITY_PROMPT_ID
        and analyze_diff.parse_bool(r.get("mention")) is not None
    ]
    if not valid:
        return None
    hits = sum(1 for r in valid if analyze_diff.parse_bool(r.get("mention")))
    return hits / len(valid)


def _arrow(delta: Optional[float]) -> str:
    if delta is None:
        return ""
    if delta > 0.005:
        return f" ↑(+{delta:.0%})"
    if delta < -0.005:
        return f" ↓({delta:.0%})"
    return " →(±0)"


def _top_entity(sov_rows: Sequence[Dict[str, Any]], date: str) -> Optional[str]:
    """当日・pillar=all で出現数が最大のエンティティ(自社を含む)。"""
    same_day = [
        r for r in sov_rows
        if str(r.get("date") or "") == date and str(r.get("pillar") or "") == "all"
    ]
    if not same_day:
        return None
    best = max(same_day, key=lambda r: float(r.get("mention_count") or 0))
    if float(best.get("mention_count") or 0) <= 0:
        return None
    return str(best.get("entity") or "") or None


def _negative_count(extractions: Sequence[Dict[str, Any]]) -> int:
    return sum(
        1 for r in extractions
        if not r.get("error") and r.get("negative_or_outdated") is True
    )


def build_summary_line(
    date: str,
    extractions: Sequence[Dict[str, Any]] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    observations: Sequence[Dict[str, Any]] = (),
) -> str:
    """2行目。1画面に収まる長さで当日の状態だけを示す。"""
    today_rate = _rate_of(extractions)

    delta = None
    previous = analyze_diff.previous_date(observations, date) if observations else None
    if previous and today_rate is not None:
        prev_rate = _rate_of(
            [r for r in observations if str(r.get("date") or "") == previous]
        )
        if prev_rate is not None:
            delta = today_rate - prev_rate

    rate_text = "—" if today_rate is None else f"{today_rate:.0%}"
    return (f"言及率 *{rate_text}*{_arrow(delta)}  |  "
            f"SoV首位 *{_top_entity(sov_rows, date) or '—'}*  |  "
            f"ネガ検知 *{_negative_count(extractions)}件*")


# --------------------------------------------------------------------------
# 3行目以降 — 変化イベント
# --------------------------------------------------------------------------
# negative_detail の本文は載せない。毎日ほぼ同じ長文になり通知が読まれなくなる。
# 代わりに種別だけを短く示し、詳細はスプレッドシートで確認してもらう。
_KIND_RULES = [
    (("旧事業", "旧MA", "MA/", "メールマーケティング", "メール配信",
      "マーケティングオートメーション"), "旧事業(MA/メール配信)の記述"),
    (("誤情報", "誤り", "事実と異なる", "正しくない", "不正確"), "誤情報の記述"),
    (("古い", "outdated", "過去の情報"), "古い情報の記述"),
]
_KIND_FALLBACK = "ネガティブな記述"
KIND_MAX_CHARS = 20


def negative_kind(detail: Any) -> str:
    """negative_detail を種別に畳む(20字以内)。本文そのものは返さない。"""
    text = str(detail or "")
    for keywords, label in _KIND_RULES:
        if any(k in text for k in keywords):
            return label[:KIND_MAX_CHARS]
    return _KIND_FALLBACK


def negative_streak(observations: Sequence[Dict[str, Any]], prompt_id: str,
                    date: str) -> int:
    """同一 prompt_id が何観測日連続で negative かを数える(当日を1日目)。

    モデル単位ではなく prompt_id 単位。片方のモデルで出ていればその日は
    「検知あり」として扱う。0 は当日に検知がないことを意味する。
    """
    by_date: Dict[str, bool] = {}
    for row in observations:
        if str(row.get("prompt_id") or "") != prompt_id:
            continue
        day = str(row.get("date") or "").strip()
        if not day or day > date:
            continue
        flag = bool(analyze_diff.parse_bool(row.get("negative_or_outdated")))
        by_date[day] = by_date.get(day, False) or flag

    streak = 0
    for day in sorted(by_date, reverse=True):
        if not by_date[day]:
            break
        streak += 1
    return streak


def _negative_lines(
    date: str,
    extractions: Sequence[Dict[str, Any]],
    changes: Sequence[Dict[str, Any]],
    observations: Sequence[Dict[str, Any]],
) -> List[str]:
    detected: Dict[tuple, str] = {}
    for record in extractions:
        if record.get("error") or record.get("negative_or_outdated") is not True:
            continue
        detected[(record.get("prompt_id"), record.get("model"))] = \
            str(record.get("negative_detail") or "")
    for change in changes:
        if change.get("change_type") == analyze_diff.NEGATIVE_ON:
            detected.setdefault(
                (change.get("prompt_id"), change.get("model")),
                str(change.get("detail") or ""),
            )
    if not detected:
        return []

    # 当日分はまだシートに無いので履歴に足してから連続日数を数える。
    history = list(observations) + [
        {"prompt_id": r.get("prompt_id"), "date": date,
         "negative_or_outdated": r.get("negative_or_outdated")}
        for r in extractions if not r.get("error")
    ]

    lines = []
    for (prompt_id, model), detail in sorted(detected.items(),
                                             key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        streak = negative_streak(history, str(prompt_id or ""), date)
        suffix = f"（継続{streak}日目）" if streak > 1 else "（本日から）"
        lines.append(f"⚠️ {prompt_id} × {model} — {negative_kind(detail)}{suffix}")
    return lines


def _enumerate(changes: Sequence[Dict[str, Any]], change_type: str) -> List[str]:
    return [
        _label(c.get("prompt_id"), c.get("model"))
        for c in changes if c.get("change_type") == change_type
    ]


def _join(items: Sequence[str]) -> str:
    if len(items) <= _MAX_ITEMS_PER_LINE:
        return ", ".join(items)
    return (", ".join(items[:_MAX_ITEMS_PER_LINE])
            + f" ほか{len(items) - _MAX_ITEMS_PER_LINE}件")


def _links() -> str:
    parts = []
    sheet = spreadsheet_url()
    if sheet:
        parts.append(f"<{sheet}|スプレッドシート>")
    if LOOKER_STUDIO_URL:
        parts.append(f"<{LOOKER_STUDIO_URL}|Looker Studio>")
    return "  |  ".join(parts)


def build_message(
    date: str,
    extractions: Sequence[Dict[str, Any]] = (),
    changes: Sequence[Dict[str, Any]] = (),
    failures: Sequence[str] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    observations: Sequence[Dict[str, Any]] = (),
) -> str:
    """日次メッセージ。変化がない日も状態を示すため必ず本文を返す。"""
    lines = [
        f"📊 *LLMO日次* | {date}",
        build_summary_line(date, extractions, sov_rows, observations),
        "",
    ]

    events: List[str] = _negative_lines(date, extractions, changes, observations)
    gained = _enumerate(changes, analyze_diff.MENTION_GAINED)
    if gained:
        events.append(f"📈 言及獲得: {_join(gained)}")
    lost = _enumerate(changes, analyze_diff.MENTION_LOST)
    if lost:
        events.append(f"📉 言及消失: {_join(lost)}")
    if failures:
        # 変化イベントではないが、落ちたことは当日中に知る必要がある。
        events.append(f"❌ パイプライン一部失敗: "
                      f"{_join([str(f).split(':', 1)[0] for f in failures])}")

    lines += events if events else ["変化なし"]

    links = _links()
    if links:
        lines += ["", links]
    return "\n".join(lines).strip()


def _post(text: str, webhook: str) -> None:
    import requests

    response = requests.post(webhook, json={"text": text}, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(
            f"Slack webhook returned {response.status_code}: {response.text[:200]}"
        )


def notify(
    date: str,
    extractions: Sequence[Dict[str, Any]] = (),
    changes: Sequence[Dict[str, Any]] = (),
    failures: Sequence[str] = (),
    sov_rows: Sequence[Dict[str, Any]] = (),
    observations: Sequence[Dict[str, Any]] = (),
    webhook: Optional[str] = None,
) -> bool:
    """Send the daily alert. Returns True when a message was actually posted."""
    text = build_message(date, extractions, changes, failures, sov_rows, observations)

    webhook = webhook if webhook is not None else SLACK_WEBHOOK_URL
    if not webhook:
        print("[warn] SLACK_WEBHOOK_URL is not set — alert skipped:")
        print(text)
        return False

    _post(text, webhook)
    print(f"[ok] notify_slack {date}: alert sent")
    return True


# --------------------------------------------------------------------------
# Weekly report (Phase 2 §4) — 役割が違うため現行フォーマットを維持する
# --------------------------------------------------------------------------
# Slack mrkdwn is not Markdown: headings do not exist and bold is single-star.
_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# Slack rejects a message body over 40,000 characters.
_SLACK_TEXT_LIMIT = 38_000


# 所見文はLLMが書くため、URLが日本語に直付けされ、スキームも落ちることがある。
# 例: 「E-1でcross-com.jp/service/...」
# これをSlackに素で渡すと「E-1でcross-com.jp」までをホスト名と解釈し、
# 「で」が非ASCIIなのでIDN変換されて xn--e-1cross-com-6e4k.jp という壊れたリンクになる。
# 明示リンク <url|label> に変換しておけば、直前の文字を巻き込まれない。
_LINKABLE_TLDS = "jp|com|net|org|io|ai|dev|app|co"
_BARE_URL_RE = re.compile(
    r"(?<![A-Za-z0-9.\-_/@<|])"          # 直前がURLの一部でなければよい(日本語直後も可)
    r"((?:https?://)?"                    # スキームは省略されることがある
    r"(?:[A-Za-z0-9-]+\.)+"               # ドメインラベル
    rf"(?:{_LINKABLE_TLDS})"              # TLDは限定する(Node.js等を誤検出しない)
    # パスはASCIIのURL安全文字のみ。日本語や閉じ括弧で必ず止まるようにして、
    # 「cross-com.jp/btob-crm/の2件が…」のように後続の本文を飲み込ませない。
    r"(?:/[A-Za-z0-9\-._~/%+#?&=]*)?)"
)
_EXISTING_LINK_RE = re.compile(r"<[^<>]+>")


def _linkify_bare_urls(segment: str) -> str:
    def repl(match: "re.Match[str]") -> str:
        label = match.group(1).rstrip(".、。")
        url = label if label.startswith(("http://", "https://")) else f"https://{label}"
        return f"<{url}|{label}>" + match.group(1)[len(label):]

    return _BARE_URL_RE.sub(repl, segment)


def to_slack_mrkdwn(markdown: str) -> str:
    """Convert the report Markdown to Slack mrkdwn."""
    text = _BOLD_RE.sub(r"*\1*", markdown)
    text = _HEADING_RE.sub(r"*\1*", text)

    # 既に <...> になっている箇所は触らず、その外側だけをリンク化する。
    parts, cursor = [], 0
    for link in _EXISTING_LINK_RE.finditer(text):
        parts.append(_linkify_bare_urls(text[cursor:link.start()]))
        parts.append(link.group(0))
        cursor = link.end()
    parts.append(_linkify_bare_urls(text[cursor:]))
    return "".join(parts).strip()


def build_weekly_message(date: str, report_md: str) -> str:
    """The weekly post: fixed header, converted body, spreadsheet link."""
    body = to_slack_mrkdwn(report_md)
    header = f"*LLMO週次所見 {date}*"
    # The report may carry its own title line; do not print it twice.
    if body.startswith("*LLMO週次所見"):
        body = body.split("\n", 1)[1].lstrip() if "\n" in body else ""

    lines = [header, "", body]
    url = spreadsheet_url()
    if url:
        lines += ["", f"<{url}|スプレッドシートを開く>"]
    text = "\n".join(lines).strip()
    if len(text) > _SLACK_TEXT_LIMIT:
        text = text[:_SLACK_TEXT_LIMIT] + "\n…(以下略。全文はスプレッドシートのweekly_reportsタブ)"
    return text


def notify_weekly(date: str, report_md: str, webhook: Optional[str] = None) -> bool:
    """Post the weekly report. Returns True when a message was posted."""
    if not report_md or not report_md.strip():
        print(f"[warn] notify_slack weekly {date}: empty report — nothing sent")
        return False

    text = build_weekly_message(date, report_md)
    webhook = webhook if webhook is not None else SLACK_WEBHOOK_URL
    if not webhook:
        print("[warn] SLACK_WEBHOOK_URL is not set — weekly report not sent:")
        print(text)
        return False

    _post(text, webhook)
    print(f"[ok] notify_slack weekly {date}: report sent ({len(text)} chars)")
    return True


# --------------------------------------------------------------------------
# --test
# --------------------------------------------------------------------------
def _test_message(date: str) -> str:
    """新フォーマットのサンプル。サマリ行・ネガ継続・獲得/消失・失敗を1通で示す。"""
    observations = [
        # 過去4日分。E-1 が連続で negative になっている履歴を作る。
        {"date": f"2026-08-{day:02d}", "prompt_id": "E-1", "model": "claude",
         "mention": "TRUE", "negative_or_outdated": "TRUE"}
        for day in (14, 15, 16, 17)
    ] + [
        {"date": "2026-08-17", "prompt_id": pid, "model": "claude",
         "mention": "TRUE" if pid in ("A-1", "A-2") else "FALSE",
         "negative_or_outdated": "FALSE"}
        for pid in ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3")
    ]
    extractions = [
        {"prompt_id": "E-1", "model": "claude", "mention": True, "error": None,
         "negative_or_outdated": True,
         "negative_detail": "【テスト送信】旧MA/メール配信事業を現在の主要事業として記述している"},
        {"prompt_id": "A-1", "model": "claude", "mention": True,
         "negative_or_outdated": False, "error": None},
        {"prompt_id": "A-2", "model": "claude", "mention": True,
         "negative_or_outdated": False, "error": None},
        {"prompt_id": "A-3", "model": "claude", "mention": False,
         "negative_or_outdated": False, "error": None},
        {"prompt_id": "B-1", "model": "gemini", "mention": True,
         "negative_or_outdated": False, "error": None},
        {"prompt_id": "B-2", "model": "gemini", "mention": False,
         "negative_or_outdated": False, "error": None},
        {"prompt_id": "B-3", "model": "gemini", "mention": False,
         "negative_or_outdated": False, "error": None},
    ]
    sov_rows = [
        {"date": date, "pillar": "all", "entity": "クロスコム", "mention_count": "5"},
        {"date": date, "pillar": "all", "entity": "メンバーズ", "mention_count": "3"},
    ]
    changes = [
        {"prompt_id": "B-1", "model": "gemini",
         "change_type": analyze_diff.MENTION_GAINED},
        {"prompt_id": "A-3", "model": "claude",
         "change_type": analyze_diff.MENTION_LOST},
    ]
    return build_message(
        date, extractions=extractions, changes=changes,
        failures=["collect_ga4: 【テスト送信】ダミーエラー"],
        sov_rows=sov_rows, observations=observations,
    )


def _test_quiet_message(date: str) -> str:
    """変化がゼロの日のサンプル(サマリ行 + 「変化なし」)。"""
    extractions = [
        {"prompt_id": pid, "model": "claude", "mention": pid in ("A-1", "A-2"),
         "negative_or_outdated": False, "error": None}
        for pid in ("A-1", "A-2", "A-3", "B-1", "B-2", "B-3")
    ]
    sov_rows = [{"date": date, "pillar": "all", "entity": "クロスコム",
                 "mention_count": "2"}]
    return build_message(date, extractions=extractions, sov_rows=sov_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Slack alert for the LLMO pipeline")
    ap.add_argument("--test", action="store_true",
                    help="send one synthetic daily alert (new format)")
    ap.add_argument("--test-quiet", action="store_true",
                    help="send the 'no changes' variant of the daily alert")
    ap.add_argument("--test-weekly", action="store_true",
                    help="send one synthetic weekly report")
    ap.add_argument("--date", default="2026-08-18", help="date label used in the message")
    args = ap.parse_args()

    if not (args.test or args.test_quiet or args.test_weekly):
        ap.error("nothing to do — pass --test / --test-quiet / --test-weekly, "
                 "or call notify() from run_daily.py")

    if args.test_weekly:
        report = (
            "# LLMO週次所見 " + args.date + "\n\n"
            "## 1. 今週のサマリ\n\n【テスト送信】週次レポートの配信テストです。\n\n"
            "## 2. 数値ハイライト\n\n- mention_rate (all): 0.42 (前週比 +0.08)\n\n"
            "## 3. 発火パターンと推奨アクション\n\n- **R-P7**: 【テスト送信】ダミー\n"
        )
        text = build_weekly_message(args.date, report)
        label = "test weekly report"
    else:
        text = _test_quiet_message(args.date) if args.test_quiet else _test_message(args.date)
        label = "test daily alert"

    if not SLACK_WEBHOOK_URL:
        print("[warn] SLACK_WEBHOOK_URL is not set — message not sent. Preview:")
        print(text)
        return
    _post(text, SLACK_WEBHOOK_URL)
    print(f"[ok] {label} sent")


if __name__ == "__main__":
    main()
