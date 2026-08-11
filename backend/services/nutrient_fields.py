"""Canonical nutrient keys for scaling, logging, and summary display.

Core four (calories/protein/carbs/fat) stay first-class FoodLog fields.
Everything else is stored on FoodLog.extra_nutrients and summed into
summary["nutrients"].
"""

from __future__ import annotations

# Scaled into FoodLog.extra_nutrients / summary nutrients. Order = UI order.
MACRO_EXTRA_FIELDS: tuple[str, ...] = (
    "fiber",
    "sugar",
    "saturated_fat",
    "trans_fat",
    "cholesterol",
)

MICRO_FIELDS: tuple[str, ...] = (
    "sodium",
    "calcium",
    "iron",
    "magnesium",
    "potassium",
    "zinc",
    "phosphorus",
    "copper",
    "manganese",
    "selenium",
    "iodine",
    "chromium",
    "molybdenum",
    "vitamin_a_rae_mcg",
    "vitamin_c",
    "vitamin_d_mcg",
    "vitamin_e_mg",
    "vitamin_k",
    "vitamin_b1",
    "vitamin_b2",
    "vitamin_b3",
    "vitamin_b6",
    "folate_dfe_mcg",
    "pantothenic_acid",
    "vitamin_b12",
    "biotin",
    "choline",
    "caffeine",
)

EXTRA_NUTRIENT_FIELDS: tuple[str, ...] = MACRO_EXTRA_FIELDS + MICRO_FIELDS

CORE_SCALED_KEYS = frozenset({"calories", "protein", "carbs", "fat"})


def extras_from_scaled(scaled: dict) -> dict[str, float]:
    """Drop core macros/calories; keep scaled extras for FoodLog / summary."""
    out: dict[str, float] = {}
    for key, val in scaled.items():
        if key in CORE_SCALED_KEYS or val is None:
            continue
        try:
            out[key] = float(val)
        except (TypeError, ValueError):
            continue
    return out

# Human labels / units for UI (backend may ignore; frontend mirrors).
NUTRIENT_META: dict[str, dict[str, str]] = {
    "protein": {"label": "Protein", "unit": "g"},
    "carbs": {"label": "Carbs", "unit": "g"},
    "fat": {"label": "Fat", "unit": "g"},
    "fiber": {"label": "Fiber", "unit": "g"},
    "sugar": {"label": "Sugar", "unit": "g"},
    "saturated_fat": {"label": "Sat. fat", "unit": "g"},
    "trans_fat": {"label": "Trans fat", "unit": "g"},
    "cholesterol": {"label": "Cholesterol", "unit": "mg"},
    "sodium": {"label": "Sodium", "unit": "mg"},
    "calcium": {"label": "Calcium", "unit": "mg"},
    "iron": {"label": "Iron", "unit": "mg"},
    "magnesium": {"label": "Magnesium", "unit": "mg"},
    "potassium": {"label": "Potassium", "unit": "mg"},
    "zinc": {"label": "Zinc", "unit": "mg"},
    "phosphorus": {"label": "Phosphorus", "unit": "mg"},
    "copper": {"label": "Copper", "unit": "mg"},
    "manganese": {"label": "Manganese", "unit": "mg"},
    "selenium": {"label": "Selenium", "unit": "mcg"},
    "iodine": {"label": "Iodine", "unit": "mcg"},
    "chromium": {"label": "Chromium", "unit": "mcg"},
    "molybdenum": {"label": "Molybdenum", "unit": "mcg"},
    "vitamin_a_rae_mcg": {"label": "Vitamin A", "unit": "mcg"},
    "vitamin_c": {"label": "Vitamin C", "unit": "mg"},
    "vitamin_d_mcg": {"label": "Vitamin D", "unit": "mcg"},
    "vitamin_e_mg": {"label": "Vitamin E", "unit": "mg"},
    "vitamin_k": {"label": "Vitamin K", "unit": "mcg"},
    "vitamin_b1": {"label": "Thiamin (B1)", "unit": "mg"},
    "vitamin_b2": {"label": "Riboflavin (B2)", "unit": "mg"},
    "vitamin_b3": {"label": "Niacin (B3)", "unit": "mg"},
    "vitamin_b6": {"label": "Vitamin B6", "unit": "mg"},
    "folate_dfe_mcg": {"label": "Folate", "unit": "mcg"},
    "pantothenic_acid": {"label": "Pantothenic acid", "unit": "mg"},
    "vitamin_b12": {"label": "Vitamin B12", "unit": "mcg"},
    "biotin": {"label": "Biotin", "unit": "mcg"},
    "choline": {"label": "Choline", "unit": "mg"},
    "caffeine": {"label": "Caffeine", "unit": "mg"},
}


def scale_extra_nutrients(metadata: dict, serving_size_g: float) -> dict[str, float]:
    """Scale non-core nutrient fields from per-100g metadata to serving grams."""
    multiplier = serving_size_g / 100
    out: dict[str, float] = {}
    for key in EXTRA_NUTRIENT_FIELDS:
        raw = metadata.get(key)
        if raw is None:
            continue
        try:
            out[key] = round(float(raw) * multiplier, 2)
        except (TypeError, ValueError):
            continue
    return out
