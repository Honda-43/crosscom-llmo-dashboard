"""観測の実行と記録を変えない決まりの見張り(2026-10-22・戦略管制塔との決まり)。

ダッシュボードの作り直しは表示の部分のみ。観測の実行と記録は、長期判定(12/28 の週)が終わるまで変更しない。
config/observation_lock.yaml の一覧の中身(SHA-256)が変わったら失敗する。2027-01-04 以降は飛ばす。
"""
import datetime as dt
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import observation_lock  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
RULE = "観測の実行と記録は長期判定（12/28 の週）まで変更しない決まり。変更が必要なら効果測定チャットと管制塔へ事前に相談"


@pytest.mark.skipif(observation_lock.expired(), reason="長期判定(12/28 の週)の後。2027-01-04 以降は見張らない")
def test_observation_files_are_unchanged():
    bad = observation_lock.changed()
    assert not bad, (f"{RULE}\n変わったもの：{'・'.join(bad)}\n"
                     "承認された変更なら python src/observation_lock.py --update --reason \"承認の経緯\" で"
                     "ハッシュを更新し、変更と同じコミットにする（ハッシュの更新だけのコミットは作らない）")


def test_the_message_and_the_deadline():
    assert observation_lock.RULE_MESSAGE == RULE
    assert observation_lock.EXPIRES_ON == "2027-01-04" == observation_lock.load()["expires_on"]
    assert not observation_lock.expired(dt.date(2027, 1, 3))
    assert observation_lock.expired(dt.date(2027, 1, 4))


def test_the_list_covers_the_observation():
    lock = observation_lock.load()
    paths = [e["path"] for e in lock["files"]]
    assert len(paths) == len(set(paths))
    for p in (".github/workflows/experiment.yml", "src/run_experiment.py", "src/collect_llm.py",
              "src/experiment.py", "config/prompts_experiment.csv", "experiment_2x2/allocation_v1.csv",
              "config/experiment_job.yaml", "src/sheets_writer.py", "src/settings.py"):
        assert p in paths, p
    symbols = {e["path"]: e.get("symbols") or [] for e in lock["files"]}
    # llm_experiment への書き込み
    assert {"HEADERS_EXPERIMENT", "KEYS_EXPERIMENT", "_experiment_row", "write_experiment", "_upsert"} <= set(
        symbols["src/sheets_writer.py"])
    # Gemini の呼び出しの設定(枠・間隔・再試行・時間の予算・観測順の輪)
    assert {"GEMINI_DAILY_REQUEST_LIMIT", "GEMINI_MIN_INTERVAL_SECONDS", "GEMINI_CALL_TIMEOUT_SECONDS", "MAX_RETRIES",
            "EXPERIMENT_TIME_BUDGET_MINUTES", "experiment_cursor", "experiment_plan"} <= set(symbols["src/settings.py"])
    # 表示の部分は見張らない
    assert "src/run_daily.py" not in paths and "experiment_2x2/summarize.py" not in paths
    assert "write_looker_tabs" not in symbols["src/sheets_writer.py"]


def test_history_is_written_in_the_diary():
    """承認された更新は、同じ経緯が実験日誌にもある(--update が両方に書く)。"""
    diary = (ROOT / "output" / "reports" / "experiment47_diary.md").read_text(encoding="utf-8")
    for h in observation_lock.load().get("history") or []:
        assert h["reason"] in diary, h


MODULE = '''"""m"""
LIMIT = 20


def watched(x):
    return x + LIMIT


def display(x):
    return f"{x}"
'''


def _setup(tmp_path):
    (tmp_path / "m.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "c.csv").write_text("id,prompt\nE01,a\n", encoding="utf-8")
    lock = {"files": [{"path": "m.py", "symbols": ["LIMIT", "watched"]}, {"path": "c.csv"}]}
    for e in lock["files"]:
        e["sha256"] = observation_lock.digest(e, tmp_path)
    return lock


def test_only_the_listed_functions_are_watched(tmp_path):
    lock = _setup(tmp_path)
    assert observation_lock.changed(lock, tmp_path) == []
    (tmp_path / "m.py").write_text(MODULE.replace('f"{x}"', 'f"[{x}]"'), encoding="utf-8")
    assert observation_lock.changed(lock, tmp_path) == [], "表示の関数を直しても止めない"
    (tmp_path / "m.py").write_bytes(MODULE.replace("\n", "\r\n").encode("utf-8"))
    assert observation_lock.changed(lock, tmp_path) == [], "改行コードの違いは同じ中身"
    (tmp_path / "m.py").write_text(MODULE.replace("LIMIT = 20", "LIMIT = 19"), encoding="utf-8")
    assert observation_lock.changed(lock, tmp_path) == ["m.py（2個の関数・定数）"]
    (tmp_path / "m.py").write_text(MODULE.replace("def watched", "def renamed"), encoding="utf-8")
    bad = observation_lock.changed(lock, tmp_path)
    assert len(bad) == 1 and bad[0].startswith("m.py（") and "watched" in bad[0], "名前を消す・変えるのも変更"


def test_whole_files_are_watched(tmp_path):
    lock = _setup(tmp_path)
    (tmp_path / "c.csv").write_text("id,prompt\nE01,b\n", encoding="utf-8")
    assert observation_lock.changed(lock, tmp_path) == ["c.csv"]
    (tmp_path / "c.csv").unlink()
    assert observation_lock.changed(lock, tmp_path)[0].startswith("c.csv（")


def test_update_after_approval_writes_the_hash_history_and_diary(tmp_path):
    lock = _setup(tmp_path)
    path, diary = tmp_path / "lock.yaml", tmp_path / "diary.md"
    path.write_text("# 見張り\nexpires_on: \"2027-01-04\"\nfiles:\n"
                    + "".join(f"  - {{path: {e['path']}, sha256: {e['sha256']}}}\n" for e in lock["files"][1:])
                    + "history: []\n", encoding="utf-8")
    diary.write_text("# 日誌\n", encoding="utf-8")
    with pytest.raises(ValueError):
        observation_lock.update("x", path, diary, root=tmp_path)            # 何も変わっていない
    (tmp_path / "c.csv").write_text("id,prompt\nE01,b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        observation_lock.update("  ", path, diary, root=tmp_path)           # 経緯が無い
    reason = '2026-11-05 管制塔が承認（"E01" の質問文の誤字）'
    assert observation_lock.update(reason, path, diary, today="2026-11-05", root=tmp_path) == ["c.csv"]
    new = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert observation_lock.changed(new, tmp_path) == []
    assert new["history"] == [{"date": "2026-11-05", "files": "c.csv", "reason": reason}]
    assert path.read_text(encoding="utf-8").startswith("# 見張り\n"), "コメントは残す"
    text = diary.read_text(encoding="utf-8")
    assert text.startswith("# 日誌\n") and "観測の実行と記録の変更（承認済み" in text and reason in text
