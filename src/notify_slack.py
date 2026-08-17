"""notify_slack.py — daily Slack alert (Phase 1 §4).

One post per day via a Slack Incoming Webhook (``SLACK_WEBHOOK_URL``), split
into sections in a fixed priority order:

1. ⚠️ ネガティブ/誤情報検知 — always first
2. 📈 言及獲得 / 📉 言及消失
3. ❌ パイプライン一部失敗

A day with none of the above sends nothing: zero notifications is the healthy
state (§4). A missing webhook logs a warning and returns normally so the
pipeline never fails just because Slack is not configured.

Manual smoke test::

    SLACK_WEBHOOK_URL=... python notify_slack.py --test
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Dict, List, Optional, Sequence

import analyze_diff
from settings import SLACK_WEBHOOK_URL, spreadsheet_url

_MAX_ITEMS_PER_SECTION = 15


def _label(prompt_id: Any, model: Any) -> str:
    return f"{prompt_id or '?'} / {model or '?'}"


def _section(title: str, items: Sequence[str]) -> List[str]:
    """A bold heading plus bulleted items, truncated so one incident cannot
    blow past Slack's message limit."""
    if not items:
        return []
    lines = [f"*{title}({len(items)}件)*"]
    lines += [f"• {item}" for item in items[:_MAX_ITEMS_PER_SECTION]]
    if len(items) > _MAX_ITEMS_PER_SECTION:
        lines.append(f"… ほか {len(items) - _MAX_ITEMS_PER_SECTION} 件")
    return lines + [""]


def _negative_items(
    extractions: Sequence[Dict[str, Any]],
    changes: Sequence[Dict[str, Any]],
) -> List[str]:
    """Observations flagged negative/outdated today, plus negative_flag_on
    changes — de-duplicated per prompt_id × model."""
    details: Dict[tuple, str] = {}
    for record in extractions:
        if record.get("error") or record.get("negative_or_outdated") is not True:
            continue
        key = (record.get("prompt_id"), record.get("model"))
        details[key] = str(record.get("negative_detail") or "").strip()
    for change in changes:
        if change.get("change_type") != analyze_diff.NEGATIVE_ON:
            continue
        key = (change.get("prompt_id"), change.get("model"))
        details.setdefault(key, str(change.get("detail") or "").strip())

    items = []
    for (prompt_id, model), detail in sorted(details.items(), key=lambda kv: str(kv[0])):
        suffix = f" — {detail}" if detail else ""
        items.append(f"{_label(prompt_id, model)}{suffix}")
    return items


def _changed_items(changes: Sequence[Dict[str, Any]], change_type: str) -> List[str]:
    return [
        _label(c.get("prompt_id"), c.get("model"))
        for c in changes
        if c.get("change_type") == change_type
    ]


def build_message(
    date: str,
    extractions: Sequence[Dict[str, Any]] = (),
    changes: Sequence[Dict[str, Any]] = (),
    failures: Sequence[str] = (),
) -> Optional[str]:
    """Compose the daily message, or ``None`` when there is nothing to report."""
    negatives = _negative_items(extractions, changes)
    gained = _changed_items(changes, analyze_diff.MENTION_GAINED)
    lost = _changed_items(changes, analyze_diff.MENTION_LOST)
    failed = list(failures)

    if not (negatives or gained or lost or failed):
        return None

    lines: List[str] = [f"*LLMO日次アラート — {date}*", ""]
    lines += _section("⚠️ ネガティブ/誤情報検知", negatives)
    lines += _section("📈 言及獲得", gained)
    lines += _section("📉 言及消失", lost)
    lines += _section("❌ パイプライン一部失敗", failed)

    url = spreadsheet_url()
    if url:
        lines.append(f"<{url}|スプレッドシートを開く>")
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
    webhook: Optional[str] = None,
) -> bool:
    """Send the daily alert. Returns True when a message was actually posted."""
    text = build_message(date, extractions, changes, failures)
    if text is None:
        print(f"[ok] notify_slack {date}: no alert conditions — nothing sent")
        return False

    webhook = webhook if webhook is not None else SLACK_WEBHOOK_URL
    if not webhook:
        print("[warn] SLACK_WEBHOOK_URL is not set — alert skipped:")
        print(text)
        return False

    _post(text, webhook)
    print(f"[ok] notify_slack {date}: alert sent")
    return True


# --------------------------------------------------------------------------
# Weekly report (Phase 2 §4)
# --------------------------------------------------------------------------
# Slack mrkdwn is not Markdown: headings do not exist and bold is single-star.
_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# Slack rejects a message body over 40,000 characters.
_SLACK_TEXT_LIMIT = 38_000


def to_slack_mrkdwn(markdown: str) -> str:
    """Convert the report Markdown to Slack mrkdwn."""
    text = _BOLD_RE.sub(r"*\1*", markdown)
    text = _HEADING_RE.sub(r"*\1*", text)
    return text.strip()


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


def _test_message(date: str) -> str:
    """A synthetic alert exercising every section (--test)."""
    return build_message(
        date,
        extractions=[{
            "prompt_id": "A-1",
            "model": "claude",
            "negative_or_outdated": True,
            "negative_detail": "【テスト送信】旧MA/メール配信事業の記述あり",
        }],
        changes=[
            {"prompt_id": "B-2", "model": "gemini", "change_type": analyze_diff.MENTION_GAINED},
            {"prompt_id": "A-3", "model": "claude", "change_type": analyze_diff.MENTION_LOST},
        ],
        failures=["collect_ga4: 【テスト送信】ダミーエラー"],
    ) or ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Slack alert for the LLMO pipeline")
    ap.add_argument("--test", action="store_true", help="send one synthetic alert")
    ap.add_argument("--test-weekly", action="store_true",
                    help="send one synthetic weekly report")
    ap.add_argument("--date", default="TEST", help="date label used in the message")
    args = ap.parse_args()

    if not (args.test or args.test_weekly):
        ap.error("nothing to do — pass --test / --test-weekly, or call notify() from run_daily.py")

    if args.test_weekly:
        report = (
            "# LLMO週次所見 " + args.date + "\n\n"
            "## 1. 今週のサマリ\n\n【テスト送信】週次レポートの配信テストです。\n\n"
            "## 2. 数値ハイライト\n\n- mention_rate (all): 0.42 (前週比 +0.08)\n\n"
            "## 3. 発火パターンと推奨アクション\n\n- **R-P7**: 【テスト送信】ダミー\n"
        )
        text = build_weekly_message(args.date, report)
        if not SLACK_WEBHOOK_URL:
            print("[warn] SLACK_WEBHOOK_URL is not set — message not sent. Preview:")
            print(text)
            return
        _post(text, SLACK_WEBHOOK_URL)
        print("[ok] test weekly report sent")
        return

    text = _test_message(args.date)
    if not SLACK_WEBHOOK_URL:
        print("[warn] SLACK_WEBHOOK_URL is not set — message not sent. Preview:")
        print(text)
        return
    _post(text, SLACK_WEBHOOK_URL)
    print("[ok] test alert sent")


if __name__ == "__main__":
    main()
