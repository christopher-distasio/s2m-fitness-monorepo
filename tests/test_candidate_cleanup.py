"""Unit tests for clarification candidate cleanup (dedupe / junk / primary)."""

from backend.services.nutrition_service import clean_clarification_candidates


def _c(name, *, brand="", calories=100, fdc_id="1", serving_label="1 oz"):
    return {
        "fdc_id": fdc_id,
        "name": name,
        "brand": brand,
        "calories": calories,
        "serving_label": serving_label,
    }


def test_excludes_primary_by_fdc_id():
    primary = _c("NUTTY & FRUITY BANANA", brand="Acme", calories=94, fdc_id="111")
    others = [
        primary,
        _c("Banana, raw", calories=89, fdc_id="222"),
    ]
    out = clean_clarification_candidates(others, primary=primary, query="banana")
    assert [c["fdc_id"] for c in out] == ["222"]


def test_excludes_primary_by_display_soft_key_when_ids_differ():
    """Primary parsed.food may not match raw candidate casing; soft key does."""
    primary = _c(
        "NUTTY & FRUITY BANANA",
        brand="ACME",
        calories=94,
        fdc_id="111",
        serving_label="1 ONZ",
    )
    clone = _c(
        "nutty & fruity banana",
        brand="ACME",
        calories=94,
        fdc_id="999",
        serving_label="1 oz",
    )
    out = clean_clarification_candidates(
        [clone, _c("Generic banana", calories=89, fdc_id="222")],
        primary=primary,
        query="banana",
    )
    assert [c["fdc_id"] for c in out] == ["222"]


def test_dedupes_identical_display_clones():
    clones = [
        _c("NUTTY BANANA", brand="X", calories=94, fdc_id="1", serving_label="1 oz"),
        _c("NUTTY BANANA", brand="X", calories=94, fdc_id="2", serving_label="1 ONZ"),
        _c("NUTTY BANANA", brand="X", calories=94, fdc_id="3", serving_label="28 g"),
    ]
    out = clean_clarification_candidates(clones, primary=None, query="banana")
    assert len(out) == 1
    assert out[0]["fdc_id"] == "1"


def test_collapses_same_display_name_across_calorie_skus():
    clones = [
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=48.59, fdc_id="a"),
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=49.72, fdc_id="b"),
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=43.0, fdc_id="c"),
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=51.0, fdc_id="d"),
    ]
    out = clean_clarification_candidates(clones, primary=None, query="yogurt")
    assert len(out) == 1
    assert out[0]["fdc_id"] == "a"


def test_stated_brand_keeps_great_value_drops_yoplait():
    from backend.services.nutrition_service import filter_candidates_to_stated_brand

    rows = [
        _c("GREAT VALUE GREEK LIGHT NON FAT YOGURT", brand="GREAT VALUE", calories=90, fdc_id="gv"),
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=49, fdc_id="yo"),
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=43, fdc_id="yo2"),
    ]
    out = filter_candidates_to_stated_brand(rows, "Great Value")
    assert [c["fdc_id"] for c in out] == ["gv"]


def test_stated_brand_filter_is_noop_when_brand_omitted():
    from backend.services.nutrition_service import filter_candidates_to_stated_brand

    rows = [
        _c("Yoplait Light Strawberry Yogurt", brand="Yoplait", calories=49, fdc_id="yo"),
    ]
    assert filter_candidates_to_stated_brand(rows, "") == rows
    assert filter_candidates_to_stated_brand(rows, None) == rows


def test_filter_matches_falls_back_when_brand_absent_from_hits():
    from backend.services.nutrition_service import filter_matches_to_stated_brand

    matches = [
        {
            "id": "yo",
            "score": 0.68,
            "metadata": {
                "name": "Yoplait Light Strawberry Yogurt",
                "brand_name": "Yoplait",
            },
        }
    ]
    out = filter_matches_to_stated_brand(matches, "Great Value")
    assert out == matches


def test_filters_placeholder_name_and_zero_cal():
    junk = [
        _c("100 g", calories=0, fdc_id="1"),
        _c("28 oz", calories=0, fdc_id="2"),
        _c("Real Banana Bread", calories=0, fdc_id="3"),
        _c("Banana chips", calories=150, fdc_id="4"),
    ]
    out = clean_clarification_candidates(junk, primary=None, query="banana")
    assert [c["fdc_id"] for c in out] == ["4"]


def test_stated_brand_tokens_must_all_appear():
    from backend.services.nutrition_service import stated_brand_matches

    assert stated_brand_matches(
        "Great Value",
        brand="GREAT VALUE",
        name="GREAT VALUE GREEK LIGHT NON FAT YOGURT",
    )
    assert not stated_brand_matches(
        "Great Value",
        brand="Yoplait",
        name="Yoplait Light Strawberry Yogurt",
    )


def test_allows_zero_cal_for_diet_soda_query():
    out = clean_clarification_candidates(
        [_c("Diet Coke", calories=0, fdc_id="1")],
        primary=None,
        query="diet coke",
    )
    assert len(out) == 1


def test_collapse_retrieval_clones_keeps_one_great_value_row():
    from backend.services.nutrition_service import collapse_retrieval_clones

    matches = [
        {
            "id": "1",
            "score": 0.75,
            "metadata": {
                "name": "GREAT VALUE GREEK LIGHT NON FAT YOGURT",
                "brand_name": "GREAT VALUE",
            },
        },
        {
            "id": "2",
            "score": 0.75,
            "metadata": {
                "name": "GREAT VALUE GREEK LIGHT NON FAT YOGURT",
                "brand_name": "GREAT VALUE",
            },
        },
        {
            "id": "3",
            "score": 0.68,
            "metadata": {
                "name": "Yoplait Light Strawberry Yogurt",
                "brand_name": "Yoplait",
            },
        },
    ]
    out = collapse_retrieval_clones(matches)
    assert [m["id"] for m in out] == ["1", "3"]
