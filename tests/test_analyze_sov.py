"""Unit tests for analyze_sov (Phase 1 §2)."""
import analyze_sov


def obs(prompt_id, pillar, model, mention, competitors, **extra):
    record = {
        "date": "2026-08-17",
        "prompt_id": prompt_id,
        "pillar": pillar,
        "model": model,
        "mention": mention,
        "competitors_mentioned": competitors,
        "error": None,
    }
    record.update(extra)
    return record


def rows_by(rows, pillar):
    return {r["entity"]: r for r in rows if r["pillar"] == pillar}


def test_counts_entities_per_pillar_and_all():
    extractions = [
        obs("A-1", "A", "claude", True, ["株式会社メンバーズ サースプラスカンパニー", "DCS"]),
        obs("A-2", "A", "gemini", False, ["船井総研"]),
        obs("B-1", "B", "claude", True, ["三菱総研ＤＣＳ"]),
    ]
    rows = analyze_sov.analyze(extractions, "2026-08-17")

    pillar_a = rows_by(rows, "A")
    assert pillar_a["メンバーズ"]["mention_count"] == 1
    assert pillar_a["三菱総研DCS"]["mention_count"] == 1
    assert pillar_a["船井総合研究所"]["mention_count"] == 1
    assert pillar_a["クロスコム"]["mention_count"] == 1
    assert all(r["observed_total"] == 2 for r in pillar_a.values())

    pillar_b = rows_by(rows, "B")
    assert pillar_b["三菱総研DCS"]["mention_count"] == 1
    assert pillar_b["クロスコム"]["mention_count"] == 1
    assert all(r["observed_total"] == 1 for r in pillar_b.values())

    everything = rows_by(rows, "all")
    assert everything["三菱総研DCS"]["mention_count"] == 2
    assert everything["クロスコム"]["mention_count"] == 2
    assert everything["クロスコム"]["observed_total"] == 3


def test_entity_prompt_and_error_rows_are_excluded():
    extractions = [
        obs("A-1", "A", "claude", True, ["DCS"]),
        obs("E-1", "entity", "claude", True, ["DCS"]),
        {"prompt_id": "A-2", "pillar": "A", "model": "gemini", "error": "timeout"},
    ]
    rows = analyze_sov.analyze(extractions, "2026-08-17")

    everything = rows_by(rows, "all")
    assert everything["三菱総研DCS"]["mention_count"] == 1
    assert everything["クロスコム"]["observed_total"] == 1
    assert not [r for r in rows if r["pillar"] == "entity"]


def test_spelling_variants_inside_one_answer_count_once():
    extractions = [obs("A-1", "A", "claude", False, ["DCS", "三菱総研ＤＣＳ", "株式会社三菱総研DCS"])]
    rows = analyze_sov.analyze(extractions, "2026-08-17")
    assert rows_by(rows, "all")["三菱総研DCS"]["mention_count"] == 1


def test_self_row_is_emitted_at_zero():
    extractions = [obs("A-1", "A", "claude", False, ["船井総研"])]
    rows = analyze_sov.analyze(extractions, "2026-08-17")
    assert rows_by(rows, "all")["クロスコム"]["mention_count"] == 0


def test_no_observations_produces_no_rows():
    assert analyze_sov.analyze([], "2026-08-17") == []


def test_row_schema_is_exactly_the_approved_columns():
    rows = analyze_sov.analyze([obs("A-1", "A", "claude", True, [])], "2026-08-17")
    assert rows
    for row in rows:
        assert set(row) == {"date", "pillar", "entity", "mention_count", "observed_total"}
        assert row["date"] == "2026-08-17"
