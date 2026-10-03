"""claude_budget.py — Claude API の1日の呼び出し上限と、クレジット不足での即停止(2026-10-03).

本田さんは自動チャージを使わない。請求の暴走を防ぐため、Claude API を呼ぶすべての処理
(実験・日次・月次の観測、Haiku の抽出、週次所見、prompt_marketing)が呼び出しの直前に
``guard()`` を通る(``create()`` は guard してから ``client.messages.create`` を呼ぶ)。

- **1日の上限**(config/claude_budget.yaml。その日の予定回数 + 再試行の余裕)に達したら、
  その日の残りは投げずに ``ClaudeStopped("daily_cap: …")`` を上げる。観測の記録側はこれを
  欠測(error=daily_cap…)として残す
- **クレジット不足(400 "credit balance is too low")**が1回でも返ったら、再試行せず、
  その日の Claude 呼び出しをすべて止める(``credit_exhausted``)
- 止めたことは data/claude_usage/<日付>/<ジョブ>.json に残り、ワークフローの最後の
  ``python claude_budget.py --check --job <ジョブ>`` が実行を失敗にして Slack に知らせる

回数の数え方:Claude API へのリクエスト1回を1回(再試行も1回)。1日は JST。
ジョブごとにファイルを分け(同じファイルを2つのワークフローが書いてぶつからないように)、
後から走るジョブは origin/main にある先のジョブの回数を足す。同時に走るジョブ(月曜の
実験 08:00 と週次 08:30)は互いの途中の回数が見えないので、上限には余裕を持たせてある。

``start()`` を呼ばない実行(テスト・手元での単発)は、ファイルに書かずにその実行の中だけで数える。
Gemini の呼び出しはここを通らない(Gemini の観測には影響しない)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # tzdata missing — JST has no DST, so a fixed offset is exact.
    JST = dt.timezone(dt.timedelta(hours=9), name="JST")

import yaml

from settings import (CONFIG_DIR, MARKETING_CLAUDE_ENABLED, MARKETING_RANK_ENABLED, ROOT_DIR,
                      experiment_claude_on, in_marketing_window, monthly_batch_on)

CONFIG_FILE = CONFIG_DIR / "claude_budget.yaml"
USAGE_DIR = ROOT_DIR / "data" / "claude_usage"
USAGE_REL = "data/claude_usage"

DAILY_CAP = "daily_cap"
CREDIT_EXHAUSTED = "credit_exhausted"
# Anthropic がクレジット切れのときに返す 400 の文面(2026-10-01 の実例:
# "Your credit balance is too low to access the Anthropic API.")
CREDIT_MARKERS = ("credit balance is too low",)


class ClaudeStopped(RuntimeError):
    """その日の Claude 呼び出しを止めている。文面は daily_cap / credit_exhausted で始まる。"""


_STATE: Dict[str, Any] = {}


def reset() -> None:
    """数え直す(テスト用・新しい実行の始まり)。"""
    _STATE.clear()
    _STATE.update(job=None, date=None, calls=0, prior=0, cap=None, stopped="", detail="",
                  usage_dir=None)


reset()


def today() -> str:
    return dt.datetime.now(JST).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# 上限
# --------------------------------------------------------------------------
def load_config(path: Path = CONFIG_FILE) -> Dict[str, int]:
    with open(path, encoding="utf-8") as fh:
        return {k: int(v) for k, v in (yaml.safe_load(fh) or {}).items()}


def cap_for(date: str, config: Optional[Dict[str, int]] = None) -> int:
    """その日の上限。環境変数 CLAUDE_DAILY_CAP があればそれ(その実行だけの一時的な上書き)。"""
    override = os.getenv("CLAUDE_DAILY_CAP")
    if override:
        return int(override)
    cfg = config if config is not None else load_config()
    cap = cfg["experiment_day"] if experiment_claude_on(date) else cfg["other_day"]
    if monthly_batch_on(date):
        cap += cfg["monthly_batch_extra"]
    if (MARKETING_CLAUDE_ENABLED or MARKETING_RANK_ENABLED) and in_marketing_window(date):
        cap += cfg["marketing_extra"]
    return cap


# --------------------------------------------------------------------------
# その日の回数(ジョブごとのファイル)
# --------------------------------------------------------------------------
def _read_local(folder: Path) -> Dict[str, Dict[str, Any]]:
    out = {}
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return out


def _read_origin(date: str) -> Dict[str, Dict[str, Any]]:
    """origin/main にある、その日のほかのジョブの回数。読めなければ空(手元だけで数える)。"""
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT_DIR, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
    try:
        git("fetch", "--quiet", "origin", "main")
        listed = git("ls-tree", "--name-only", "origin/main", f"{USAGE_REL}/{date}/")
        if listed.returncode != 0:
            return {}
        out = {}
        for name in listed.stdout.split():
            if name.endswith(".json"):
                shown = git("show", f"origin/main:{name}")
                if shown.returncode == 0:
                    out[Path(name).stem] = json.loads(shown.stdout)
        return out
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def usage_of(date: str, usage_dir: Path,
             read_origin: bool = False) -> Dict[str, Dict[str, Any]]:
    """{ジョブ: そのジョブのファイル}。手元と origin で回数の多いほう。"""
    files = _read_local(usage_dir / date)
    for job, rec in (_read_origin(date) if read_origin else {}).items():
        if int(rec.get("calls") or 0) > int(files.get(job, {}).get("calls") or 0):
            files[job] = rec
    return files


def start(job: str, date: Optional[str] = None, usage_dir: Optional[Path] = None,
          read_origin: Optional[bool] = None) -> None:
    """この実行のジョブ名を決め、その日のほかのジョブの回数を読む。以後の回数をファイルに残す。

    origin を読むのは GitHub Actions の中だけ(手元の実行では手元のファイルだけで数える)。
    """
    reset()
    date = date or today()
    usage_dir = Path(usage_dir if usage_dir is not None else USAGE_DIR)
    if read_origin is None:
        read_origin = os.getenv("GITHUB_ACTIONS") == "true"
    files = usage_of(date, usage_dir, read_origin)
    own = files.pop(job, {})
    _STATE.update(job=job, date=date, usage_dir=usage_dir, cap=cap_for(date),
                  calls=int(own.get("calls") or 0),
                  prior=sum(int(r.get("calls") or 0) for r in files.values()))
    stopped = [r for r in [own, *files.values()] if r.get("stopped") == CREDIT_EXHAUSTED]
    if stopped:
        # ほかのジョブがクレジット不足を見ていれば、この実行も最初から止める
        _STATE.update(stopped=CREDIT_EXHAUSTED, detail=stopped[0].get("detail", ""))
    print(f"[info] claude_budget: {date} job={job} 上限 {_STATE['cap']}回"
          f"(ほかのジョブ {_STATE['prior']}回・このジョブ {_STATE['calls']}回)"
          + (f" — 停止中({_STATE['stopped']})" if _STATE["stopped"] else ""))


def _save() -> None:
    if not _STATE["job"]:
        return
    folder = Path(_STATE["usage_dir"]) / _STATE["date"]
    folder.mkdir(parents=True, exist_ok=True)
    rec = {"date": _STATE["date"], "job": _STATE["job"], "calls": _STATE["calls"],
           "others": _STATE["prior"], "cap": _STATE["cap"], "stopped": _STATE["stopped"],
           "detail": _STATE["detail"],
           "updated_at": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")}
    (folder / f"{_STATE['job']}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stop(reason: str, detail: str) -> None:
    if not _STATE["stopped"]:
        _STATE.update(stopped=reason, detail=detail)
        print(f"[error] claude_budget: その日の Claude 呼び出しを止める({reason}) — {detail}")
        _save()


# --------------------------------------------------------------------------
# 呼び出しの前後
# --------------------------------------------------------------------------
def is_credit_error(exc: BaseException) -> bool:
    text = str(exc)
    return any(marker in text for marker in CREDIT_MARKERS)


def guard(label: str = "") -> None:
    """Claude を1回呼ぶ直前に通る。止めている・上限に達していれば ClaudeStopped を上げる(投げない)。"""
    if _STATE["date"] is None:                 # start() を呼ばない実行(テスト・手元の単発)
        _STATE.update(date=today())
    if _STATE["cap"] is None:
        _STATE["cap"] = cap_for(_STATE["date"])
    if _STATE["stopped"]:
        raise ClaudeStopped(f"{_STATE['stopped']}: その日の Claude 呼び出しは止めている"
                            f"({_STATE['detail']})")
    used = _STATE["prior"] + _STATE["calls"]
    if used >= _STATE["cap"]:
        _stop(DAILY_CAP, f"{_STATE['date']} の上限 {_STATE['cap']}回に達した"
                         f"(ほかのジョブ {_STATE['prior']}回・このジョブ {_STATE['calls']}回)")
        raise ClaudeStopped(f"{DAILY_CAP}: {_STATE['detail']}" + (f"。{label} は投げていない" if label else ""))
    _STATE["calls"] += 1
    _save()


def failed(exc: BaseException) -> None:
    """Claude の呼び出しが例外で終わったとき。クレジット不足なら、その日の残りを止める。"""
    if is_credit_error(exc):
        _stop(CREDIT_EXHAUSTED, "Anthropic のクレジット残高が不足(400)。残高を確認・チャージするまで止める")


def create(client: Any, label: str = "", **kwargs: Any) -> Any:
    """guard → ``client.messages.create(**kwargs)``。クレジット不足の 400 は記録してそのまま上げる。"""
    guard(label)
    try:
        return client.messages.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 - 種類は呼び出し側が判断する
        failed(exc)
        raise


def status() -> Dict[str, Any]:
    return dict(_STATE)


# --------------------------------------------------------------------------
# ワークフローの最後の確認
# --------------------------------------------------------------------------
def check(jobs: List[str], date: Optional[str] = None,
          usage_dir: Optional[Path] = None) -> Tuple[bool, List[str]]:
    """(問題なし, 説明の行)。指定したジョブのどれかが止まっていれば False。"""
    date = date or today()
    files = _read_local(Path(usage_dir if usage_dir is not None else USAGE_DIR) / date)
    lines, ok = [], True
    for job in jobs:
        rec = files.get(job)
        if not rec:
            lines.append(f"- {job}: {date} は Claude を呼んでいない")
            continue
        line = f"- {job}: {rec.get('calls', 0)}回(ほかのジョブ {rec.get('others', 0)}回・上限 {rec.get('cap')}回)"
        if rec.get("stopped"):
            ok = False
            line += f" — **停止: {rec['stopped']}**({rec.get('detail', '')})"
        lines.append(line)
    return ok, lines


def _notify(text: str) -> None:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        return
    try:
        import notify_slack
        notify_slack._post(text, webhook)
    except Exception as exc:  # noqa: BLE001 - 通知の失敗で確認そのものを落とさない(exit 1 は別に返す)
        print(f"[warn] Slack 通知に失敗: {exc}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Claude API の1日の呼び出し上限の確認")
    ap.add_argument("--check", action="store_true", required=True)
    ap.add_argument("--job", action="append", required=True, help="確かめるジョブ(複数可)")
    ap.add_argument("--date", help="YYYY-MM-DD(既定: 当日JST)")
    a = ap.parse_args(argv)
    ok, lines = check(a.job, a.date)
    head = f"## Claude API の呼び出し({a.date or today()})"
    print("\n".join([head, *lines]))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join([head, *lines]) + "\n")
    if ok:
        return 0
    run = (f"{os.getenv('GITHUB_SERVER_URL', '')}/{os.getenv('GITHUB_REPOSITORY', '')}"
           f"/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}")
    _notify("*LLMO Claude API アラート*\n*⛔ その日の Claude 呼び出しを止めました*\n"
            + "\n".join(lines) + "\n• daily_cap = 1日の上限に到達 / credit_exhausted = クレジット残高不足"
            "(自動チャージなし。残高を確認してチャージ)\n"
            f"<{run}|実行ログを開く>")
    print("::error::Claude API の呼び出しを止めました(上の行を参照)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
