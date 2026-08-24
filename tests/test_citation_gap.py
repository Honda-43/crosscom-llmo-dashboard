"""引用元ドメインの3分類のテスト(Phase 5 §3-2 / DoD 6)."""
import citation_gap


def raw(date, prompt_id, model, urls):
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "cited_urls": urls, "answer": "x"}


def obs(date, prompt_id, model, mention):
    return {"date": date, "prompt_id": prompt_id, "model": model,
            "mention": "TRUE" if mention else "FALSE"}


def classify(raw_records, observations):
    return citation_gap.classify(raw_records, citation_gap.mention_map(observations))


def by_domain(result):
    return {r["domain"]: r for r in result["rows"]}


# --- 3分類 ------------------------------------------------------------------
def test_three_categories():
    raw_records = [
        # 自社が言及された回答
        raw("2026-08-24", "A-1", "claude",
            ["https://cross-com.jp/about/", "https://prtimes.jp/x"]),
        # 自社が言及されなかった回答
        raw("2026-08-24", "B-1", "claude",
            ["https://prtimes.jp/y", "https://ipros.com/z"]),
    ]
    observations = [obs("2026-08-24", "A-1", "claude", True),
                    obs("2026-08-24", "B-1", "claude", False)]
    rows = by_domain(classify(raw_records, observations))

    assert rows["cross-com.jp"]["category"] == citation_gap.CATEGORY_SELF
    # 自社言及ありの回答にも出る → 共通
    assert rows["prtimes.jp"]["category"] == citation_gap.CATEGORY_SHARED
    # 自社不在の回答でのみ出る → 掲載依頼先の候補
    assert rows["ipros.com"]["category"] == citation_gap.CATEGORY_ABSENT


def test_absent_category_needs_zero_appearances_with_self():
    raw_records = [raw("2026-08-24", "B-1", "claude", ["https://ipros.com/a"]),
                   raw("2026-08-25", "B-1", "claude", ["https://ipros.com/b"])]
    observations = [obs("2026-08-24", "B-1", "claude", False),
                    obs("2026-08-25", "B-1", "claude", False)]
    row = by_domain(classify(raw_records, observations))["ipros.com"]
    assert row["category"] == citation_gap.CATEGORY_ABSENT
    assert row["cited_count"] == 2
    assert row["cited_with_self"] == 0


def test_one_mention_with_self_moves_it_to_shared():
    raw_records = [raw("2026-08-24", "B-1", "claude", ["https://ipros.com/a"]),
                   raw("2026-08-25", "A-1", "claude", ["https://ipros.com/b"])]
    observations = [obs("2026-08-24", "B-1", "claude", False),
                    obs("2026-08-25", "A-1", "claude", True)]
    assert by_domain(classify(raw_records, observations))["ipros.com"]["category"] \
        == citation_gap.CATEGORY_SHARED


# --- 数え方 ------------------------------------------------------------------
def test_duplicate_urls_in_one_answer_count_once():
    raw_records = [raw("2026-08-24", "A-1", "claude",
                       ["https://prtimes.jp/a", "https://prtimes.jp/b",
                        "https://www.prtimes.jp/c"])]
    observations = [obs("2026-08-24", "A-1", "claude", True)]
    assert by_domain(classify(raw_records, observations))["prtimes.jp"]["cited_count"] == 1


def test_www_prefix_is_normalised():
    raw_records = [raw("2026-08-24", "A-1", "claude", ["https://www.ipros.com/x"]),
                   raw("2026-08-25", "A-1", "claude", ["https://ipros.com/y"])]
    observations = [obs("2026-08-24", "A-1", "claude", True),
                    obs("2026-08-25", "A-1", "claude", True)]
    rows = by_domain(classify(raw_records, observations))
    assert "www.ipros.com" not in rows
    assert rows["ipros.com"]["cited_count"] == 2


def test_gemini_redirects_are_excluded_but_counted():
    raw_records = [raw("2026-08-24", "E-1", "gemini", [
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA",
        "https://prtimes.jp/x",
    ])]
    observations = [obs("2026-08-24", "E-1", "gemini", True)]
    result = classify(raw_records, observations)
    assert "vertexaisearch.cloud.google.com" not in by_domain(result)
    assert result["unresolved_citations"] == 1


def test_observations_without_extraction_are_skipped():
    """自社が出たか判定できない観測は分類に使えない。"""
    raw_records = [raw("2026-08-24", "A-1", "claude", ["https://prtimes.jp/x"])]
    result = classify(raw_records, [])
    assert result["rows"] == []
    assert result["evaluated_observations"] == 0


def test_self_domain_is_detected_by_fragment():
    raw_records = [raw("2026-08-24", "A-1", "claude",
                       ["https://cross-com.jp/service/", "https://crosscom.example/x"])]
    observations = [obs("2026-08-24", "A-1", "claude", True)]
    rows = by_domain(classify(raw_records, observations))
    assert rows["cross-com.jp"]["category"] == citation_gap.CATEGORY_SELF
    assert rows["crosscom.example"]["category"] == citation_gap.CATEGORY_SELF


def test_prompts_column_lists_where_it_appeared():
    raw_records = [raw("2026-08-24", "A-1", "claude", ["https://ipros.com/x"]),
                   raw("2026-08-24", "B-1", "claude", ["https://ipros.com/y"])]
    observations = [obs("2026-08-24", "A-1", "claude", False),
                    obs("2026-08-24", "B-1", "claude", False)]
    assert by_domain(classify(raw_records, observations))["ipros.com"]["prompts"] == "A-1, B-1"


def test_sheet_rows_use_the_approved_columns():
    raw_records = [raw("2026-08-24", "A-1", "claude", ["https://ipros.com/x"])]
    observations = [obs("2026-08-24", "A-1", "claude", False)]
    rows = citation_gap.build_rows("2026-08-24", raw_records, observations)
    assert set(rows[0]) == {"date", "domain", "category", "cited_count", "prompts"}
