"""Tests for serving-size sanitization (branded grams off-by-1000 bug)."""
from backend.services.nutrition_service import (
    get_serving_size_g,
    scale_nutrients,
    _sanitize_serving_size_g,
)


def test_sanitize_multiplies_tiny_grams_by_1000():
    grams, fix = _sanitize_serving_size_g(0.056)
    assert grams == 56.0
    assert fix == "serving_size_g_x1000_fix"


def test_sanitize_leaves_normal_serving_alone():
    grams, fix = _sanitize_serving_size_g(56)
    assert grams == 56.0
    assert fix is None


def test_kroger_smoked_lean_ham_serving_not_near_zero_calories():
    """Live bug: serving_size_g=0.056 made 125 kcal/100g scale to ~0.07 kcal."""
    meta = {
        "name": "KROGER SMOKED DELI STYLE LEAN HAM, SMOKED",
        "serving_size_g": 0.056,
        "household_serving_fulltext": "6 slices",
        "calories": 125,
        "protein": 17.86,
        "carbs": 3.57,
        "fat": 4.46,
    }
    serving_g, source = get_serving_size_g(meta)
    assert serving_g == 56.0
    assert source == "serving_size_g_x1000_fix"
    scaled = scale_nutrients(meta, serving_g)
    # 125 * 0.56 = 70
    assert scaled["calories"] == 70.0
    assert scaled["calories"] > 50
