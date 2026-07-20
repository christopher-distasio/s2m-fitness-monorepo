"""Tier 3 regressions: Atwater calorie fill-in + zero-cal handling.

Covers the locked-in scenarios for the zero-calorie / Atwater fallback fix
(ranking + scale_nutrients + parser safety net). Deterministic — no network.
Live end-to-end calorie bounds live in tests/eval_food_parser.py (nutrition).
"""
from backend.services.nutrition_service import scale_nutrients
from backend.services.query_match_rank import (
    effective_calories_per_100g,
    is_zero_calorie_query,
    near_zero_calorie_penalty,
)


def test_atwater_when_calories_zero_but_macros_present():
    """Kroger-ham-style gap: calories:0 with real macros → Atwater estimate."""
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
    scaled = scale_nutrients(meta, 56)
    # 103 * 0.56 ≈ 57.68 — must not stay ~0
    assert scaled["calories"] > 50
    assert near_zero_calorie_penalty("Kroger lean ham", meta) == 0.0


def test_genuinely_zero_calorie_foods_not_altered_or_penalized():
    """Water / black coffee stay near-zero; fallback must not invent kcal."""
    water = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    coffee = {"calories": 2, "protein": 0.1, "carbs": 0, "fat": 0}

    assert is_zero_calorie_query("water")
    assert is_zero_calorie_query("a cup of black coffee")
    assert effective_calories_per_100g(water) == 0
    assert scale_nutrients(water, 240)["calories"] == 0
    assert near_zero_calorie_penalty("water", water) == 0.0
    assert near_zero_calorie_penalty("black coffee", coffee) == 0.0


def test_empty_calories_and_macros_stay_zero_no_fabrication():
    """When calories AND macros are missing/zero, do not invent a number."""
    meta = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    assert effective_calories_per_100g(meta) == 0
    assert scale_nutrients(meta, 56)["calories"] == 0
    # Caloric query still sees a near-zero penalty (ranking); the parser
    # safety net (low confidence) is covered in eval_food_parser.py.
    assert near_zero_calorie_penalty("lean ham", meta) > 0


def test_prefers_stored_calories_when_present_pass_through():
    """Healthy row with real calories — Atwater must not rewrite them."""
    meta = {"calories": 145, "protein": 18, "carbs": 1, "fat": 3}
    assert effective_calories_per_100g(meta) == 145
    # Even though Atwater(18,1,3)=103, stored 145 wins.
    assert scale_nutrients(meta, 100)["calories"] == 145.0
    banana = {"calories": 89, "protein": 1.1, "carbs": 22.8, "fat": 0.3}
    assert effective_calories_per_100g(banana) == 89
    assert scale_nutrients(banana, 118)["calories"] == round(89 * 1.18, 2)
