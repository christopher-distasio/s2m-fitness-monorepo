"""Tests for serving-size sanitization (branded grams off-by-1000 bug)."""
from backend.services.nutrition_service import (
    get_serving_size_g,
    scale_nutrients,
    _sanitize_serving_size_g,
)


def test_sanitize_multiplies_tiny_mg_grams_by_1000():
    grams, fix = _sanitize_serving_size_g(0.056, serving_size_unit="mg")
    assert grams == 56.0
    assert fix == "serving_size_g_x1000_fix"


def test_sanitize_does_not_x1000_subgram_without_mg_unit():
    grams, fix = _sanitize_serving_size_g(0.056)
    assert grams == 0.056
    assert fix is None


def test_sanitize_leaves_normal_serving_alone():
    grams, fix = _sanitize_serving_size_g(56)
    assert grams == 56.0
    assert fix is None


def test_sanitize_leaves_subgram_g_serving_alone():
    grams, fix = _sanitize_serving_size_g(0.25, serving_size_unit="g")
    assert grams == 0.25
    assert fix is None


def test_kroger_smoked_lean_ham_serving_not_near_zero_calories():
    """Live bug: serving_size_g=0.056 made 125 kcal/100g scale to ~0.07 kcal."""
    meta = {
        "name": "KROGER SMOKED DELI STYLE LEAN HAM, SMOKED",
        "fdc_id": "2533433",
        "serving_size_g": 0.056,
        "serving_size_unit": "mg",
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


def test_kroger_ham_2533433_mg_unit_scales_to_56g_70_kcal():
    """Pin the MG-means-grams undo on the live ham payload shape."""
    meta = {
        "fdc_id": "2533433",
        "qdrant_id": "2533433",
        "name": "KROGER SMOKED DELI STYLE LEAN HAM, SMOKED",
        "data_source": "LI",
        "serving_size_g": 0.056,
        "household_serving_fulltext": "6 slices",
        "calories": 125.0,
        "protein": 17.86,
        "carbs": 3.57,
        "fat": 4.46,
    }
    serving_g, source = get_serving_size_g(meta)
    assert serving_g == 56.0
    assert source == "serving_size_g_x1000_fix"
    assert scale_nutrients(meta, serving_g)["calories"] == 70.0


def test_tropicana_2501658_mg_unit_scales_to_240g_110_kcal():
    """Pin the MG-means-grams undo on Tropicana 8 fl oz (240 MG -> 240 g)."""
    meta = {
        "fdc_id": "2501658",
        "qdrant_id": "2501658",
        "name": "TROPICANA, ORANGE JUICE",
        "data_source": "LI",
        "serving_size_g": 0.24,
        "household_serving_fulltext": "8 fl oz",
        "calories": 46.0,
        "protein": 0.83,
        "carbs": 10.83,
        "fat": 0.0,
    }
    serving_g, source = get_serving_size_g(meta)
    assert serving_g == 240.0
    assert source == "serving_size_g_x1000_fix"
    assert scale_nutrients(meta, serving_g)["calories"] == 110.4


def test_euromonitor_mozzarella_not_x1000():
    meta = {
        "fdc_id": "2755908",
        "data_source": "Euromonitor",
        "serving_size_g": 0.25,
        "serving_size_unit": "g",
        "calories": 80.0,
    }
    serving_g, source = get_serving_size_g(meta)
    assert serving_g == 0.25
    assert source == "branded_serving_size"
