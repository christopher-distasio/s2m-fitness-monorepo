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


def test_filters_placeholder_name_and_zero_cal():
    junk = [
        _c("100 g", calories=0, fdc_id="1"),
        _c("28 oz", calories=0, fdc_id="2"),
        _c("Real Banana Bread", calories=0, fdc_id="3"),
        _c("Banana chips", calories=150, fdc_id="4"),
    ]
    out = clean_clarification_candidates(junk, primary=None, query="banana")
    assert [c["fdc_id"] for c in out] == ["4"]


def test_allows_zero_cal_for_diet_soda_query():
    out = clean_clarification_candidates(
        [_c("Diet Coke", calories=0, fdc_id="1")],
        primary=None,
        query="diet coke",
    )
    assert len(out) == 1
