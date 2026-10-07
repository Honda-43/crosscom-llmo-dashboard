"""早期解放ルール(2026-10-01 事前登録・2026-10-07 実装)のテスト.

短期判定(2026-11-02 の週・アフター 10/06〜11/01)でのみ、施策ごとに3条件で判定する。
(1) Gemini の差の差 +20ポイント以上 (2) 再ランダム化の片側 p<0.005(プール2,000件未満は判定不能)
(3) 感度分析の全通りで向きが同じ。Claude は対象外。
"""
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiment_2x2"))
import summarize  # noqa: E402

ALL = [("両方込み", set())]


def _data(lead_hits=2):
    """各組5本。③④(リードあり)のうち lead_hits 本だけアフターで引用が増える。差の差 = lead_hits/10。"""
    after, before = {}, {}
    n = 0
    for g in ("①対照", "②FAQのみ", "③リードのみ", "④両方"):
        for i in range(5):
            slug = f"{g}-{i}"
            before[slug] = (g, 0)
            gain = g in ("③リードのみ", "④両方") and n < lead_hits
            if gain:
                n += 1
            after[slug] = (g, 1 if gain else 0)
    return after, before


def _lead(rows):
    return next(r for r in rows if r["name"].startswith("リード"))


def test_exactly_plus_20_points_passes_and_p_0005_fails():
    after, before = _data(lead_hits=2)                     # ③④10本中2本 → 差の差 +20.0
    lead = _lead(summarize.early_release(after, before, {"n": 2500, "lead_p": 0.0049, "faq_p": 0.5}, ALL))
    assert lead["did"] == 20.0 and lead["did_ok"], "ちょうど +20ポイントは合格(以上)"
    assert lead["p_ok"] and lead["signs_ok"] and lead["verdict"] == "解放可"
    assert lead["text"] == summarize.EARLY_RELEASE_YES
    lead = _lead(summarize.early_release(after, before, {"n": 2500, "lead_p": 0.005, "faq_p": 0.5}, ALL))
    assert not lead["p_ok"] and lead["verdict"] == "解放不可", "ちょうど 0.005 は不合格(未満)"
    assert lead["text"].startswith("12/28 の週の長期判定まで継続")


def test_below_20_points_is_not_released():
    after, before = _data(lead_hits=1)                     # 差の差 +10.0
    lead = _lead(summarize.early_release(after, before, {"n": 2500, "lead_p": 0.001, "faq_p": 0.5}, ALL))
    assert lead["did"] == 10.0 and not lead["did_ok"] and lead["verdict"] == "解放不可"


def test_a_pool_under_2000_is_not_judged():
    after, before = _data(lead_hits=4)
    for rr in ({"n": 1999, "short": True}, None):
        rows = summarize.early_release(after, before, rr, ALL)
        assert all(r["verdict"] == "プール不足のため判定不能" for r in rows)
        assert all(not r["p_ok"] for r in rows), "プール不足では解放可にならない"


def test_one_sensitivity_variant_in_the_other_direction_blocks_release():
    after, before = _data(lead_hits=2)
    gainers = [s for s, (g, v) in after.items() if v == 1]
    variants = ALL + [("増えた記事抜き", set(gainers))]     # 抜くと差の差が0(向きがそろわない)
    lead = _lead(summarize.early_release(after, before, {"n": 2500, "lead_p": 0.001, "faq_p": 0.5}, variants))
    assert lead["did_ok"] and lead["p_ok"] and not lead["signs_ok"] and lead["verdict"] == "解放不可"


EXP_HEAD = ["date", "experiment_id", "model", "target_url", "cited_article", "error", "experiment_flag"]


def _run(monkeypatch, tmp_path, capsys, after, *extra):
    monkeypatch.setattr(summarize, "load_allocation", lambda: {"agentforce-rag": "③リードのみ",
                                                               "agentforce-features": "①対照"})
    monkeypatch.setattr(summarize.rerandomize, "load", lambda path=None: [])
    rag, feat = "https://cross-com.jp/agentforce-rag/", "https://cross-com.jp/agentforce-features/"
    path = tmp_path / "e.csv"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([EXP_HEAD,
                                 ["2026-09-18", "E06", "gemini", rag, "0", "", "pool"],
                                 ["2026-10-10", "E06", "gemini", rag, "1", "", "pool"],
                                 ["2026-09-18", "E12", "gemini", feat, "0", "", "pool"],
                                 ["2026-10-10", "E12", "gemini", feat, "0", "", "pool"],
                                 ["2026-09-21", "E06", "claude", rag, "0", "", "pool"],
                                 ["2026-10-12", "E06", "claude", rag, "1", "", "pool"]])
    summarize.main(["--before", "2026-09-15:2026-09-28", "--after", after, "--csv", str(path), *extra])
    return capsys.readouterr().out


def test_the_section_is_only_in_the_short_judgement_and_only_for_gemini(monkeypatch, tmp_path, capsys):
    short = _run(monkeypatch, tmp_path, capsys, "2026-10-06:2026-11-01")
    assert short.count("## 早期解放の判定（短期判定のみ・Gemini・2026-10-01 事前登録）") == 1
    assert "プール不足のため判定不能" in short and "### リード（③＋④ 対 ①＋②）" in short
    section = short.split("## 早期解放の判定")[1]
    assert "##### claude" not in section.split("※ Claude は")[0], "Gemini の節の中にだけ出る"
    long_ = _run(monkeypatch, tmp_path, capsys, "2026-10-06:2026-12-28")
    assert "早期解放の判定" not in long_, "長期判定には出さない"
    claude_only = _run(monkeypatch, tmp_path, capsys, "2026-10-06:2026-11-01", "--model", "claude")
    assert "早期解放の判定" not in claude_only, "Claude は対象外"


def test_the_weekly_report_has_no_early_release_section():
    weekly = (ROOT / "src" / "experiment_weekly.py").read_text(encoding="utf-8")
    assert "早期解放" not in weekly


def test_the_rule_is_recorded_before_the_short_judgement():
    import yaml
    freeze = yaml.safe_load(open(ROOT / "config" / "experiment_freeze.yaml", encoding="utf-8"))
    rule = freeze["early_release_rule"]
    assert rule["implemented_on"] == "2026-10-07" < "2026-11-02"
    assert "2026-10-01 の事前登録どおり" in rule["note"]
