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

# USDA FDC nutrient numbers (SR Legacy / branded classic ids). Spec 1 CHANGE 1.
USDA_NUTRIENT_IDS: dict[str, int] = {
    "calories": 1008,
    "protein": 1003,
    "fat": 1004,
    "fats": 1004,
    "carbs": 1005,
    "carbohydrates": 1005,
    "fiber": 1079,
    "sugar": 2000,
    "saturated_fat": 1258,
    "trans_fat": 1257,
    "sodium": 1093,
    "cholesterol": 1253,
    "calcium": 1087,
    "iron": 1089,
    "magnesium": 1090,
    "potassium": 1092,
    "zinc": 1095,
    "vitamin_a_rae_mcg": 1106,
    "vitamin_c": 1162,
    "vitamin_d_mcg": 1114,
    "vitamin_e_mg": 1109,
    "vitamin_k": 1185,
    "vitamin_b1": 1165,
    "vitamin_b2": 1166,
    "vitamin_b3": 1167,
    "vitamin_b6": 1175,
    "folate_dfe_mcg": 1190,
    "pantothenic_acid": 1170,
    "vitamin_b12": 1178,
    "caffeine": 1057,
    "phosphorus": 1091,
    "copper": 1098,
    "manganese": 1101,
    "selenium": 1103,
    "choline": 1180,
    "iodine": 1100,
    "chromium": 1096,
    "molybdenum": 1102,
    "biotin": 1176,
}


def wrap_nutrient(name: str, value: float | None) -> dict:
    """Typed nutrient payload: value + unit + usda_nutrient_id."""
    meta = NUTRIENT_META.get(name, {})
    unit = meta.get("unit") or ("kcal" if name == "calories" else "g")
    return {
        "value": value,
        "unit": unit,
        "usda_nutrient_id": USDA_NUTRIENT_IDS.get(name),
    }


def wrap_nutrient_map(values: dict | None) -> dict:
    if not values:
        return {}
    out = {}
    for key, raw in values.items():
        if raw is None:
            continue
        if isinstance(raw, dict) and "value" in raw:
            out[key] = raw
            continue
        try:
            out[key] = wrap_nutrient(key, float(raw))
        except (TypeError, ValueError):
            continue
    return out


def unwrap_nutrient_map(values: dict | None) -> dict[str, float]:
    """Flatten typed nutrients back to the legacy {name: number} UI shape."""
    if not values:
        return {}
    out: dict[str, float] = {}
    for key, raw in values.items():
        if isinstance(raw, dict):
            val = raw.get("value")
        else:
            val = getattr(raw, "value", raw)
        if val is None:
            continue
        try:
            out[key] = float(val)
        except (TypeError, ValueError):
            continue
    return out


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
