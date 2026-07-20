"""Unit tests for Atwater calorie fill-in (used by scale_nutrients / ranking)."""
from backend.services.query_match_rank import effective_calories_per_100g


def test_atwater_when_calories_zero_but_macros_present():
    meta = {
        "name": "SMOKED DELI STYLE LEAN HAM",
        "brand_name": "Kroger",
        "calories": 0,
        "protein": 18,
        "carbs": 1,
        "fat": 3,
    }
    # per 100g: 4*18 + 4*1 + 9*3 = 72+4+27 = 103
    assert effective_calories_per_100g(meta) == 103
    # Same math scale_nutrients uses for a ~2 oz serving.
    scaled = round(103 * (56 / 100), 2)
    assert scaled > 50


def test_keeps_real_zero_when_no_macros():
    meta = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    assert effective_calories_per_100g(meta) == 0


def test_prefers_stored_calories_when_present():
    meta = {"calories": 145, "protein": 18, "carbs": 1, "fat": 3}
    assert effective_calories_per_100g(meta) == 145
