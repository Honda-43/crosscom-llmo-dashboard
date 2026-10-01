"""表示用タブ(lk_*)の失敗は警告にとどめる(2026-10-01).

10/1 の日次は write_answer_pivot(lk_answers_pivot)が Sheets API の
1分あたり読み取り上限(429)で落ち、観測もシート本体も書けていたのに
ワークフローが赤になり、失敗通知は「Python到達前の失敗の可能性あり」と出た。

- 表示用タブの失敗は exit 0。日次アラートに警告として載せる
- 観測・抽出・シート本体の書き込みの失敗は exit 1。失敗通知に落ちたフェーズ名を渡す
- 429 は待って再送する(sheets_writer の HTTP クライアント)
"""
import pytest

import collect_ga4
import collect_gsc
import collect_llm
import extract
import looker_tabs
import notify_slack
import run_daily
import sheets_writer

QUIET_DAY = "2026-09-23"            # 水(観測しない日。LLM を呼ばない)
SHEET_CALLS = (
    "read_llm_observations", "read_daily_summary", "read_ga4", "read_gsc",
    "read_action_log", "read_monthly_observations",
    "write_llm_observations", "write_sov_daily", "write_changes", "write_ga4",
    "write_gsc", "write_gsc_pages", "write_daily_summary", "write_board_daily",
    "write_looker_tabs", "write_answer_pivot",
)


def _boom(message):
    def fn(*args, **kwargs):
        raise RuntimeError(message)
    return fn


@pytest.fixture
def wired(monkeypatch, tmp_path):
    posted = {}

    def fake_notify(date, extractions=(), changes=(), failures=(), **kwargs):
        posted.update(failures=list(failures), warnings=list(kwargs.get("warnings", ())))
        return True

    monkeypatch.setattr(notify_slack, "notify", fake_notify)
    monkeypatch.setattr(extract, "extract_record", lambda record: dict(record))
    monkeypatch.setattr(collect_llm, "collect", lambda d: [])
    monkeypatch.setattr(collect_ga4, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect", lambda: [])
    monkeypatch.setattr(collect_gsc, "collect_pages", lambda: [])
    for name in SHEET_CALLS:
        monkeypatch.setattr(sheets_writer, name, lambda *a, **k: [])
    # 前日の実行漏れの警告を出さない
    monkeypatch.setattr(sheets_writer, "read_daily_summary", lambda: [{"date": "2026-09-22"}])
    monkeypatch.setattr(looker_tabs, "build_all", lambda *a, **k: {"lk_answers": []})
    monkeypatch.setattr(run_daily, "_job_summary", lambda lines: posted.update(summary=lines))
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    posted["out"] = out
    return posted


def _run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", QUIET_DAY])
    with pytest.raises(SystemExit) as exited:
        run_daily.main()
    return exited.value.code


def _outputs(path):
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_a_display_tab_failure_is_a_warning_not_a_failure(wired, monkeypatch):
    """10/1 の再現。lk_answers_pivot が 429 で落ちても run は落とさない。"""
    monkeypatch.setattr(sheets_writer, "write_answer_pivot", _boom(
        "APIError: [429]: Quota exceeded for quota metric 'Read requests'"))

    assert _run(monkeypatch) == 0
    assert wired["failures"] == []
    assert any("表示用タブ" in w and "write_answer_pivot" in w for w in wired["warnings"])
    assert any("表示用タブの失敗" in line for line in wired["summary"])
    assert _outputs(wired["out"]) == {"delivered": "true", "failed_phases": ""}


@pytest.mark.parametrize("phase", ["write_llm_observations", "write_daily_summary",
                                   "write_gsc_pages", "read_llm_observations"])
def test_a_main_sheet_failure_still_fails_the_run(wired, monkeypatch, phase):
    monkeypatch.setattr(sheets_writer, phase, _boom("APIError: [500]"))

    assert _run(monkeypatch) == 1
    assert any(f.startswith(phase) for f in wired["failures"])
    assert _outputs(wired["out"])["failed_phases"] == phase


def test_both_kinds_are_reported_separately(wired, monkeypatch):
    monkeypatch.setattr(sheets_writer, "write_changes", _boom("boom"))
    monkeypatch.setattr(sheets_writer, "write_looker_tabs", _boom("boom"))

    assert _run(monkeypatch) == 1
    assert [f.split(":")[0] for f in wired["failures"]] == ["write_changes"]
    assert any("write_looker_tabs" in w for w in wired["warnings"])
    # 失敗通知に出すのは run を落としたフェーズだけ
    assert _outputs(wired["out"])["failed_phases"] == "write_changes"


def test_phase_names_drop_the_detail():
    assert run_daily._phase_name("collect_llm(欠測 3件): A-1/gemini") == "collect_llm"
    assert run_daily._phase_name("write_answer_pivot: APIError: [429]") == "write_answer_pivot"


# --------------------------------------------------------------------------
# 429 の再送(sheets_writer._retrying_http_client)
# --------------------------------------------------------------------------
class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.ok = code < 400
        self.text = "{}"

    def json(self):
        return {"error": {"code": self.status_code, "message": "x", "status": "x"}}


def _client(monkeypatch, codes):
    from gspread.http_client import HTTPClient

    sleeps, calls = [], []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    def fake_request(self, *args, **kwargs):
        from gspread.exceptions import APIError
        code = codes[len(calls)]
        calls.append(code)
        if code >= 400:
            raise APIError(_Resp(code))
        return _Resp(code)

    monkeypatch.setattr(HTTPClient, "request", fake_request)
    cls = sheets_writer._retrying_http_client()
    client = cls.__new__(cls)
    return client, sleeps, calls


def test_a_429_is_retried_after_waiting(monkeypatch):
    client, sleeps, calls = _client(monkeypatch, [429, 429, 200])
    assert client.request("get", "https://example").ok
    assert calls == [429, 429, 200]
    assert sleeps == [2, 4]


def test_other_errors_are_not_retried(monkeypatch):
    """5xx は処理が済んでいることがあり、append を再送すると行が二重になる。"""
    from gspread.exceptions import APIError

    client, sleeps, calls = _client(monkeypatch, [500, 200])
    with pytest.raises(APIError):
        client.request("post", "https://example")
    assert calls == [500] and sleeps == []


def test_retries_give_up_after_about_a_minute(monkeypatch):
    from gspread.exceptions import APIError

    client, sleeps, calls = _client(monkeypatch, [429] * 7)
    with pytest.raises(APIError):
        client.request("get", "https://example")
    assert sum(sleeps) > 60 and len(calls) == 6
