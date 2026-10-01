"""後から書き足された列・行を、書くスクリプトの再実行で消さない(2026-10-01).

seo-agent で判定スクリプトが CSV の note 列を空で上書きし、手書きの記録が
消えていた。dashboard 側の同じ型を点検し、直したものをここで固定する。
どのテストも「書き足した内容を入れてから同じ書き込みを流し直し、消えないこと」を見る。
"""
import re

import pytest

import sheets_writer


class FakeWorksheet:
    """gspread の Worksheet のうち、_upsert / _ensure_worksheet が使う分だけ。"""

    def __init__(self, values):
        self.values = [list(r) for r in values]
        self.col_count = max(len(r) for r in values) + 5
        self.row_count = len(values) + 100

    def get_all_values(self):
        return [list(r) for r in self.values]

    def row_values(self, n):
        return list(self.values[n - 1]) if n <= len(self.values) else []

    def _put(self, rnum, col, row):
        while len(self.values) < rnum:
            self.values.append([])
        current = self.values[rnum - 1] + [""] * max(0, col + len(row) - len(self.values[rnum - 1]))
        # 書いた範囲だけを置き換える。左右の列は残る(本物と同じ)
        self.values[rnum - 1] = current[:col] + list(row) + current[col + len(row):]

    def update(self, values, range_name="A1", **kw):
        letters, start = re.match(r"([A-Z]+)(\d+)", range_name).groups()
        col = 0
        for ch in letters:
            col = col * 26 + (ord(ch) - 64)
        for offset, row in enumerate(values):
            self._put(int(start) + offset, col - 1, row)

    def batch_update(self, updates, **kw):
        for u in updates:
            self.update(u["values"], u["range"])

    def append_rows(self, rows, **kw):
        for row in rows:
            self.values.append(list(row))


class FakeSpreadsheet:
    def __init__(self, tabs):
        self.tabs = tabs

    def worksheet(self, title):
        return self.tabs[title]


@pytest.fixture
def sheet(monkeypatch):
    tabs = {}
    monkeypatch.setattr(sheets_writer, "_open_spreadsheet", lambda: FakeSpreadsheet(tabs))
    return tabs


def _as_dicts(ws):
    header = ws.values[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in ws.values[1:]]


# --------------------------------------------------------------------------
# action_log:状態・実施日・判断期限・備考は人がシートで進める
# --------------------------------------------------------------------------
def test_reseeding_the_action_log_keeps_what_people_wrote(sheet):
    import action_log

    h = sheets_writer.HEADERS_ACTION_LOG
    seed = action_log.SEED_ROWS[0]
    edited = dict(seed, 状態="完了", 実施日="2026-08-11", 判断期限="2026-09-07",
                  備考="AUBAは8/14に反映を確認(手書き)")
    sheet["action_log"] = FakeWorksheet([h, [edited.get(c, "") for c in h]])

    sheets_writer.write_action_log(action_log.SEED_ROWS)   # 初期データを流し直す

    rows = {r["action_id"]: r for r in _as_dicts(sheet["action_log"])}
    assert rows[seed["action_id"]]["状態"] == "完了"
    assert rows[seed["action_id"]]["備考"] == "AUBAは8/14に反映を確認(手書き)"
    # 無かった行は足される
    assert set(rows) == {r["action_id"] for r in action_log.SEED_ROWS}


def test_rows_people_added_by_hand_survive_a_weekly_proposal(sheet):
    h = sheets_writer.HEADERS_ACTION_LOG
    manual = {"action_id": "A-090", "内容": "手で足した施策", "状態": "承認", "備考": "電話で合意"}
    sheet["action_log"] = FakeWorksheet([h, [manual.get(c, "") for c in h]])

    sheets_writer.write_action_log([{"action_id": "A-091", "内容": "週次の提案", "状態": "提案中"}])

    rows = {r["action_id"]: r for r in _as_dicts(sheet["action_log"])}
    assert rows["A-090"]["備考"] == "電話で合意"
    assert rows["A-091"]["状態"] == "提案中"


def test_the_one_column_writer_touches_only_that_column(sheet):
    h = sheets_writer.HEADERS_ACTION_LOG
    row = {"action_id": "A-003", "状態": "実施済み・効果測定中", "備考": "手書きの備考"}
    sheet["action_log"] = FakeWorksheet([h, [row.get(c, "") for c in h]])

    class Ws(FakeWorksheet):
        def col_values(self, n):
            return [r[n - 1] if len(r) >= n else "" for r in self.values]

    sheet["action_log"].__class__ = Ws
    sheets_writer.write_action_log_column({"A-003": "手書きの備考。同日実施"}, "備考")

    got = _as_dicts(sheet["action_log"])[0]
    assert got["状態"] == "実施済み・効果測定中"
    assert got["備考"] == "手書きの備考。同日実施"


# --------------------------------------------------------------------------
# monthly_observations:notes は観測からは埋まらない(人が書く)
# --------------------------------------------------------------------------
def test_rerunning_a_month_keeps_the_notes(sheet):
    h = sheets_writer.HEADERS_MONTHLY
    old = {"date": "2026-10-01", "prompt_id": "M-1", "model": "claude", "mention": "1",
           "notes": "回答が英語で返った(手書き)"}
    sheet["monthly_observations"] = FakeWorksheet([h, [old.get(c, "") for c in h]])

    sheets_writer.write_monthly_observations([{
        "date": "2026-10-01", "prompt_id": "M-1", "model": "claude", "answer": "再観測",
        "mention": True,
    }])

    got = _as_dicts(sheet["monthly_observations"])
    assert len(got) == 1
    assert got[0]["notes"] == "回答が英語で返った(手書き)"


def test_a_note_written_by_the_script_still_wins():
    h = ["date", "x", "notes"]
    out = sheets_writer._carry_forward(["d", "1", "新しい注記"], ["d", "0", "古い注記"], h, ["notes"])
    assert out == ["d", "1", "新しい注記"]


def test_columns_to_the_right_of_the_schema_are_not_touched(sheet):
    """スキーマの右に人が足した列(見出しも値も)は、行の上書きでも残る。"""
    h = sheets_writer.HEADERS_SUMMARY
    sheet["daily_summary"] = FakeWorksheet([h + ["メモ"], ["2026-10-01"] + [""] * (len(h) - 1) + ["手書き"]])

    sheets_writer.write_daily_summary({"date": "2026-10-01", "mention_rate_all": 0.5})

    assert sheet["daily_summary"].values[0][-1] == "メモ"
    assert sheet["daily_summary"].values[1][-1] == "手書き"


# --------------------------------------------------------------------------
# 実験の週次集計(output/reports/experiment47_weekN_*.md)
# --------------------------------------------------------------------------
HAND = "- **確定: 2026-09-22**(Gemini の cited_article 率 17.8%・13/73。E37 を含む47本での集計)"
GENERATED = "# 1週目の集計\n\n- 集計日: 2026-09-22\n- 率の分母は観測できた回数\n"


def test_rerunning_a_finished_week_keeps_the_report(tmp_path):
    import experiment_weekly

    path = tmp_path / "experiment47_week1_20260922.md"
    path.write_text(GENERATED.replace("- 集計日: 2026-09-22\n", f"- 集計日: 2026-09-22\n{HAND}\n"),
                    encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    assert experiment_weekly.write_report(path, "# 作り直した本文\n") is False
    assert path.read_text(encoding="utf-8") == before


def test_force_rebuild_carries_the_hand_written_line(tmp_path):
    import experiment_weekly

    path = tmp_path / "experiment47_week1_20260922.md"
    path.write_text(GENERATED.replace("- 集計日: 2026-09-22\n", f"- 集計日: 2026-09-22\n{HAND}\n"),
                    encoding="utf-8")

    assert experiment_weekly.write_report(path, GENERATED + "- 新しい節\n", force=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines.count(HAND) == 1
    assert lines.index(HAND) == lines.index("- 集計日: 2026-09-22") + 1
    assert "- 新しい節" in lines


def test_a_new_week_is_written(tmp_path):
    import experiment_weekly

    path = tmp_path / "reports" / "experiment47_week2_20260929.md"
    assert experiment_weekly.write_report(path, GENERATED)
    assert path.read_text(encoding="utf-8") == GENERATED
