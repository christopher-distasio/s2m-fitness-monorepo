"""Asserting unit tests for allergen text-scan logic.

Promotes the pasta/wheat fix and modifier/compound gates from print-only
__main__ cases in allergen_extraction_logic.py into CI-failing pytest.
"""

import pytest

from allergen_extraction_logic import extract_allergen_states, scan_ingredients_for_terms


# ---------------------------------------------------------------------------
# Pasta / noodle wheat fix (2026-08-09)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "description,expected_wheat",
    [
        ("Macaroni or pasta salad with tuna and egg", "CONTAINS"),
        ("Beef, noodles, and vegetables excluding carrots, broccoli, and dark-green leafy; gravy", "CONTAINS"),
        ("Shrimp and noodles with cream or white sauce", "CONTAINS"),
        ("flavored pasta", "CONTAINS"),
        ("spaghetti with meat sauce", "CONTAINS"),
        ("Rice noodles, dry", "UNKNOWN"),
        ("Long rice noodles, made from mung beans, cooked", "UNKNOWN"),
        ("Squash, winter, spaghetti, cooked, boiled, drained, or baked, with salt", "UNKNOWN"),
        ("chickpea pasta, dry", "UNKNOWN"),
        ("gluten-free pasta", "UNKNOWN"),
        ("gluten free noodles", "UNKNOWN"),
    ],
)
def test_pasta_noodle_wheat_states(description, expected_wheat):
    states = extract_allergen_states(description)
    assert states["wheat"] == expected_wheat, states


def test_macaroni_salad_also_flags_fish_and_egg():
    states = extract_allergen_states("Macaroni or pasta salad with tuna and egg")
    assert states["wheat"] == "CONTAINS"
    assert states["fish"] == "CONTAINS"
    assert states["egg"] == "CONTAINS"


def test_shrimp_noodles_flags_shellfish_and_wheat():
    states = extract_allergen_states("Shrimp and noodles with cream or white sauce")
    assert states["wheat"] == "CONTAINS"
    assert states["shellfish"] == "CONTAINS"
    assert states["milk"] == "CONTAINS"  # cream


# ---------------------------------------------------------------------------
# Modifier gates / compound exclusions (safety false-positive guards)
# ---------------------------------------------------------------------------

def test_almond_milk_is_not_dairy_milk():
    states = extract_allergen_states("INGREDIENTS: ALMOND MILK, VANILLA, SEA SALT.")
    assert states["milk"] == "UNKNOWN"
    assert states["tree_nut"] == "CONTAINS"


def test_oat_milk_is_not_dairy_milk():
    states = extract_allergen_states("INGREDIENTS: OAT MILK, OAT FLOUR.")
    assert states["milk"] == "UNKNOWN"


def test_crab_apple_is_not_shellfish():
    states = extract_allergen_states("INGREDIENTS: APPLE, CRAB APPLE CONCENTRATE, SUGAR.")
    assert states["shellfish"] == "UNKNOWN"


def test_water_chestnut_is_not_tree_nut():
    states = extract_allergen_states("INGREDIENTS: WATER CHESTNUT, SOY SAUCE, GINGER.")
    assert states["tree_nut"] == "UNKNOWN"
    assert states["soy"] == "CONTAINS"


def test_vegan_mayonnaise_is_not_egg():
    states = extract_allergen_states(
        "INGREDIENTS: VEGAN MAYONNAISE (SOY PROTEIN, VINEGAR)."
    )
    assert states["egg"] == "UNKNOWN"
    assert states["soy"] == "CONTAINS"


def test_explicit_contains_statement_sets_free_for_unnamed():
    states = extract_allergen_states(
        "INGREDIENTS: WHEAT FLOUR, SUGAR, EGGS, BUTTER. CONTAINS: WHEAT, MILK, EGG."
    )
    assert states["wheat"] == "CONTAINS"
    assert states["milk"] == "CONTAINS"
    assert states["egg"] == "CONTAINS"
    assert states["peanut"] == "FREE"
    assert states["soy"] == "FREE"


def test_empty_ingredients_all_unknown():
    states = extract_allergen_states("")
    assert all(v == "UNKNOWN" for v in states.values())
    assert len(states) == 9


def test_scan_finds_wheat_in_pasta_dish_name():
    found = scan_ingredients_for_terms("macaroni salad with vegetables")
    assert "wheat" in found
