"""介入ログ(output/interventions.csv)のテスト(2026-09-25).

固定したいのは4つ:
1. 日付の読み方。空欄・継続("2026-09-25〜")を取り違えないこと
2. 日付が未確定の介入を、今日や 0 として縦線にしないこと
3. 折れ線(R2)に縦線と凡例が出ること。施策(action_log)の線とは別の線であること
4. 週次レポートにその週の介入が出て、プール46本に触れる週は注意書きが出ること
"""
import datetime as dt

import plotly.graph_objects as go
import pytest

import board
import experiment_weekly as ew
import interventions

CSV = """# 注記行は読み飛ばす
date,intervention_id,description,scope,executor,touches_pool46
2026-09-20,I-01,Wikidata に企業エントリを登録,外部(エンティティ),本田さん(手動),no
,I-05,meta 改修(日付・対象ともに要確認),サイト(メタ),要確認,要確認
2026-09-25〜,I-06,Claudeforce 記事に D-39 等を適用,サイト(記事),要確認,要確認
2026-09-29,I-07,2x2 の処置反映と鮮度更新の訂正,プール46本,seo-agent,yes
"""


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "interventions.csv"
    path.write_text(CSV, encoding="utf-8")
    return interventions.load(path)


def test_dates_are_parsed_including_the_ongoing_form(log):
    by_id = {r["intervention_id"]: r for r in log}
    assert by_id["I-01"]["date"] == dt.date(2026, 9, 20) and not by_id["I-01"]["ongoing"]
    assert by_id["I-06"]["date"] == dt.date(2026, 9, 25) and by_id["I-06"]["ongoing"]
    assert by_id["I-07"]["date"] == dt.date(2026, 9, 29)
    assert by_id["I-05"]["date"] is None, "日付が空の行を日付にしない"


def test_undated_rows_are_kept_but_never_drawn(log):
    assert [r["intervention_id"] for r in interventions.undated(log)] == ["I-05"]
    assert "I-05" not in [r["intervention_id"] for r in interventions.dated(log)]
    assert all(r["date"] for r in interventions.dated(log))


def test_the_window_uses_the_start_date_of_an_ongoing_intervention(log):
    got = interventions.in_window(dt.date(2026, 9, 21), dt.date(2026, 9, 27), log)
    assert [r["intervention_id"] for r in got] == ["I-06"]


def test_the_label_marks_an_ongoing_intervention(log):
    by_id = {r["intervention_id"]: r for r in log}
    assert interventions.label(by_id["I-06"]) == "I-06〜"
    assert interventions.label(by_id["I-01"]) == "I-01"


def test_the_log_is_written_by_the_dashboard_side_only():
    """I-10 は seo-agent 側が足したもの。以後は dashboard 側だけが書く。"""
    text = (interventions.INTERVENTIONS_FILE).read_text(encoding="utf-8")
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert any("dashboard 側だけが書く" in ln for ln in head)
    assert any("I-10" in ln for ln in head)


def test_the_real_log_parses_and_keeps_the_agreed_columns():
    rows = interventions.load()
    assert rows, "output/interventions.csv が読めない"
    assert interventions.FIELDS == ["date", "intervention_id", "description", "scope",
                                    "executor", "touches_pool46"]
    for row in rows:
        assert set(interventions.FIELDS) <= set(row)
    ids = [r["intervention_id"] for r in rows]
    assert len(set(ids)) == len(ids), "intervention_id が重複している"
    pool = [r for r in rows if r["touches_pool46"] == "yes"]
    # ビフォー期間中の編集(9/11 の一括反映・9/11〜14 のリンク増・9/15〜16 の追記)と
    # 9/29 の処置反映がプール46本に触れる
    assert [r["intervention_id"] for r in pool] == ["I-11", "I-12", "I-09", "I-07"]
    by_id = {r["intervention_id"]: r for r in rows}
    # 9/29 に入れる訂正は1本(E37 は 9/22 に実験外で適用済み。
    # agentforce-vibes は 2026-09-26 に訂正見送り —— 戦略管制塔の裁定で凍結明けへ)
    assert "訂正1件" in by_id["I-07"]["description"]
    assert "agentforce-features" in by_id["I-07"]["description"]
    assert "agentforce-vibes" not in by_id["I-07"]["description"]
    e37 = by_id["I-08"]
    assert e37["date"] == dt.date(2026, 9, 22) and e37["touches_pool46"] == "no"
    assert "watch" in e37["scope"], "E37 は実験外(watch)"
    # I-05 は「2026-09-15より前」で1日に定まらない。縦線にはしない
    assert [r["intervention_id"] for r in interventions.undated(rows)] == ["I-05"]
    # 終わりのある範囲("2026-09-20〜22")は開始日で読み、継続(ongoing)にはしない。
    # 継続は末尾が印で終わるもの("2026-09-25〜")だけ
    assert by_id["I-04"]["date"] == dt.date(2026, 9, 20) and not by_id["I-04"]["ongoing"]
    assert by_id["I-09"]["date"] == dt.date(2026, 9, 15) and not by_id["I-09"]["ongoing"]
    assert by_id["I-06"]["ongoing"], "2026-09-25〜 は継続"


# --- 折れ線(R2)の縦線 ---------------------------------------------------------
def test_the_chart_gets_one_dotted_line_per_dated_intervention(log):
    figure = go.Figure()
    legend = board.intervention_annotations(figure, log)
    lines = [s for s in figure.layout.shapes if s.type == "line"]
    assert len(lines) == 3, "日付のある3件だけ線にする"
    assert {s.line.dash for s in lines} == {"dot"}, "施策の破線(dash)と区別する"
    assert "I-06〜" in legend and "I-01" in legend
    assert "プール46本に触れる" in legend, "混ざる介入は凡例で知らせる"
    assert "日付が1日に定まらない(縦線なし): I-05" in legend


def test_a_missing_log_does_not_break_the_chart(monkeypatch):
    monkeypatch.setattr(board.interventions, "load", lambda: [])
    figure = go.Figure()
    assert board.intervention_annotations(figure) == ""
    assert not figure.layout.shapes


# --- 週次レポート -------------------------------------------------------------
MON = dt.date(2026, 10, 5)          # 前の週 = 9/28〜10/4(9/29 の処置反映を含む)


def _weekly(log, tmp_path, report_date=MON):
    return ew.build(report_date, [], pool=[{"id": "E01", "layer": "古",
                                            "url": "https://cross-com.jp/a/"}],
                    raw_dir=tmp_path, experiment_dir=tmp_path, monthly_dir=tmp_path,
                    intervention_rows=log)


def test_the_weekly_report_lists_this_weeks_interventions(log, tmp_path):
    text = _weekly(log, tmp_path)
    section = text.split("## 4. この週の介入")[1].split("## 5.")[0]
    assert "I-07" in section and "2x2 の処置反映" in section
    assert "I-01" not in section, "前の週の介入は出さない"
    assert "プール46本に触れる介入がこの週にある" in section
    assert "日付が1日に定まらない" in section and "I-05" in section


def test_a_week_without_interventions_says_so(log, tmp_path):
    text = _weekly(log, tmp_path, dt.date(2026, 10, 19))      # 10/12〜10/18
    section = text.split("## 4. この週の介入")[1].split("## 5.")[0]
    assert "この週に実施した介入はない" in section
    assert "プール46本に触れる介入がこの週にある" not in section
