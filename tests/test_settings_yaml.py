"""Duplicate-key detection in config YAML loading.

Plain ``yaml.safe_load`` keeps the *last* value when a key is repeated, so a
duplicated ``ゼロワングロース:`` in the alias file would silently undo an edit.
These files are hand-maintained during operation — the failure must be loud.
"""
import pytest

from settings import DuplicateKeyError, load_yaml


def write(tmp_path, text):
    path = tmp_path / "conf.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_duplicate_top_level_key_raises(tmp_path):
    path = write(tmp_path, "aliases:\n  A: [x]\nbliases:\n  B: [y]\naliases:\n  C: [z]\n")
    with pytest.raises(DuplicateKeyError) as exc:
        load_yaml(path)
    assert "aliases" in str(exc.value)


def test_duplicate_nested_key_raises_with_line_number(tmp_path):
    path = write(
        tmp_path,
        "aliases:\n"
        "  ゼロワングロース: [01GROWTH]\n"
        "  ハンドレッド: [100inc]\n"
        "  ゼロワングロース: [01GROWTH, 100inc]\n",
    )
    with pytest.raises(DuplicateKeyError) as exc:
        load_yaml(path)
    message = str(exc.value)
    assert "ゼロワングロース" in message
    assert "line 4" in message


def test_valid_file_loads(tmp_path):
    path = write(tmp_path, "aliases:\n  ゼロワングロース: [01GROWTH]\n  ハンドレッド: [100inc]\n")
    assert load_yaml(path) == {
        "aliases": {"ゼロワングロース": ["01GROWTH"], "ハンドレッド": ["100inc"]}
    }


def test_duplicate_values_in_a_list_are_fine(tmp_path):
    """重複を禁止するのはキーだけ。リストの重複は無害。"""
    path = write(tmp_path, "aliases:\n  ハンドレッド: [100inc, 100inc]\n")
    assert load_yaml(path)["aliases"]["ハンドレッド"] == ["100inc", "100inc"]


def test_shipped_config_files_load(tmp_path):
    from settings import ENTITY_ALIASES_FILE, ENTITY_STOPLIST_FILE, PROMPTS_FILE

    for path in (PROMPTS_FILE, ENTITY_ALIASES_FILE, ENTITY_STOPLIST_FILE):
        assert load_yaml(path), path
