"""Euromonitor branded rows store label per-SERVING values, not per-100g.

Regression for the 1.5025x double-scaling that reported Dannon Light + Fit
(fdc_id 2756921) as 120.2 kcal for its 150.25 g cup instead of the label's 80.

Payloads below are copied verbatim from the live Qdrant collection
("food-vectors", 2026-08-30) and match branded_food.csv / food_nutrient.csv
2026-04-30 exactly. Only the fields the nutrient math reads are kept.
"""

from types import SimpleNamespace

from backend.services.nutrition_service import (
    _qdrant_results_to_matches,
    get_serving_size_g,
    normalize_nutrients_to_per_100g,
    scale_nutrients,
    stores_nutrients_per_serving,
)

# fdc_id 2756921 — "Dannon Light + Fit Greek Nonfat Yogurt", peach, UPC
# 00036632037367. USDA stores fat=8.0 for this row; that is wrong for a nonfat
# yogurt (the label says 0 g) but it is a source-data error, not a scaling one,
# so the assertions below pin what the record actually says.
DANNON_2756921 = {
    "fdc_id": "2756921",
    "qdrant_id": "2756921",
    "name": "Dannon Light + Fit Greek Nonfat Yogurt",
    "description": "Dannon Light + Fit Greek Nonfat Yogurt",
    "source": "branded_foods",
    "brand_name": "Dannon",
    "data_source": "Euromonitor",
    "serving_size_g": 150.24969482421875,
    "calories": 80.0,
    "protein": 12.0,
    "fat": 8.0,
    "carbs": 8.0,
    "fiber": 0.0,
    "sugar": 7.0,
    "saturated_fat": 0.0,
    "sodium": 45.0,
}

# fdc_id 2756149 — same description string, blackberry, UPC 00036632037541.
# Distinct calories (110) and fat (0.0), which is what makes it a useful
# control that carbs and fat are read from separate payload fields.
DANNON_2756149 = {
    "fdc_id": "2756149",
    "qdrant_id": "2756149",
    "name": "Dannon Light + Fit Greek Nonfat Yogurt",
    "description": "Dannon Light + Fit Greek Nonfat Yogurt",
    "source": "branded_foods",
    "brand_name": "Dannon",
    "data_source": "Euromonitor",
    "serving_size_g": 150.24969482421875,
    "calories": 110.0,
    "protein": 12.0,
    "fat": 0.0,
    "carbs": 8.0,
    "fiber": 0.0,
    "sugar": 7.0,
    "saturated_fat": 0.0,
    "sodium": 50.0,
}

# fdc_id 2688156 — NIDO Fortificada powdered milk, data_source GDSN. 500 kcal
# per 100 g is right for milk powder (~5 kcal/g) and 30 g scales to 150 kcal;
# reading it per-serving would imply an impossible 16.7 kcal/g. Guards against
# the fix leaking onto the 99.9% of rows that really are per-100g.
NIDO_2688156_GDSN = {
    "fdc_id": "2688156",
    "qdrant_id": "2688156",
    "name": "NIDO Fortificada Powdered Drink Mix",
    "source": "branded_foods",
    "data_source": "GDSN",
    "serving_size_g": 30.0,
    "calories": 500.0,
    "protein": 26.7,
    "fat": 26.7,
    "carbs": 40.0,
}


def _serving_macros(payload: dict) -> dict:
    """Full read path: normalize basis, resolve serving grams, scale."""
    meta = normalize_nutrients_to_per_100g(payload)
    serving_size_g, _ = get_serving_size_g(meta)
    return scale_nutrients(meta, serving_size_g)


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------

def test_dannon_2756921_reports_label_values_not_double_scaled():
    macros = _serving_macros(DANNON_2756921)
    assert macros["calories"] == 80.0
    assert macros["protein"] == 12.0
    assert macros["carbs"] == 8.0
    assert macros["fat"] == 8.0


def test_dannon_2756921_extras_are_not_double_scaled():
    macros = _serving_macros(DANNON_2756921)
    assert macros["sugar"] == 7.0
    assert macros["sodium"] == 45.0
    assert macros["fiber"] == 0.0
    assert macros["saturated_fat"] == 0.0


def test_dannon_2756921_no_longer_returns_the_1_5025x_values():
    """The exact wrong numbers from the 2026-08-30 session log."""
    macros = _serving_macros(DANNON_2756921)
    assert macros["calories"] != 120.2
    assert macros["protein"] != 18.03
    assert macros["carbs"] != 12.02
    assert macros["fat"] != 12.02


def test_unnormalized_payload_still_double_scales():
    """Pins the mechanism: the old path squared serving_size_g/100."""
    serving_size_g, source = get_serving_size_g(DANNON_2756921)
    assert source == "branded_serving_size"
    naive = scale_nutrients(DANNON_2756921, serving_size_g)
    assert naive["calories"] == 120.2
    assert naive["protein"] == 18.03
    assert naive["carbs"] == 12.02
    assert naive["fat"] == 12.02


# ---------------------------------------------------------------------------
# Basis detection and conversion
# ---------------------------------------------------------------------------

def test_euromonitor_is_detected_as_per_serving():
    assert stores_nutrients_per_serving(DANNON_2756921) is True
    assert stores_nutrients_per_serving(DANNON_2756149) is True


def test_other_providers_are_left_on_per_100g():
    assert stores_nutrients_per_serving(NIDO_2688156_GDSN) is False
    assert stores_nutrients_per_serving({"data_source": "LI"}) is False
    assert stores_nutrients_per_serving({}) is False
    assert stores_nutrients_per_serving(None) is False


def test_gdsn_row_is_untouched_and_still_scales():
    assert normalize_nutrients_to_per_100g(NIDO_2688156_GDSN) is NIDO_2688156_GDSN
    macros = _serving_macros(NIDO_2688156_GDSN)
    # 500 kcal/100g over a 30 g serving.
    assert macros["calories"] == 150.0


def test_conversion_puts_dannon_on_a_plausible_per_100g_density():
    meta = normalize_nutrients_to_per_100g(DANNON_2756921)
    # 80 kcal / 150.25 g = 0.53 kcal/g, i.e. ~53 kcal per 100 g.
    assert round(meta["calories"], 2) == 53.24
    assert round(meta["protein"], 2) == 7.99
    assert DANNON_2756921["calories"] == 80.0, "source payload must not mutate"


def test_normalization_is_idempotent():
    once = normalize_nutrients_to_per_100g(DANNON_2756921)
    twice = normalize_nutrients_to_per_100g(once)
    assert twice["calories"] == once["calories"]
    serving_size_g, _ = get_serving_size_g(twice)
    assert scale_nutrients(twice, serving_size_g)["calories"] == 80.0


def test_conversion_survives_an_arbitrary_portion_size():
    """Basis conversion must not assume the record's own serving size."""
    meta = normalize_nutrients_to_per_100g(DANNON_2756921)
    # Half the 150.25 g cup.
    assert scale_nutrients(meta, 75.124847412109375)["calories"] == 40.0
    assert scale_nutrients(meta, 300.4993896484375)["calories"] == 160.0


# ---------------------------------------------------------------------------
# Distinct macro fields
# ---------------------------------------------------------------------------

def test_carbs_and_fat_read_from_separate_payload_fields():
    """2756921 reports equal carbs/fat only because USDA stores 8.0 for both;
    2756149 stores carbs=8.0 fat=0.0 and must report them differently."""
    macros = _serving_macros(DANNON_2756149)
    assert macros["calories"] == 110.0
    assert macros["protein"] == 12.0
    assert macros["carbs"] == 8.0
    assert macros["fat"] == 0.0
    assert macros["carbs"] != macros["fat"]


def test_two_dannon_records_share_a_description_but_not_their_numbers():
    """Both rows are named "Dannon Light + Fit Greek Nonfat Yogurt", so a name
    match cannot tell them apart — but the logged numbers must still differ."""
    assert DANNON_2756921["name"] == DANNON_2756149["name"]
    assert (
        _serving_macros(DANNON_2756921)["calories"]
        != _serving_macros(DANNON_2756149)["calories"]
    )


# ---------------------------------------------------------------------------
# Retrieval bridge
# ---------------------------------------------------------------------------

def test_qdrant_bridge_normalizes_every_payload():
    results = [
        SimpleNamespace(payload=DANNON_2756921, score=0.85),
        SimpleNamespace(payload=NIDO_2688156_GDSN, score=0.40),
    ]
    matches = _qdrant_results_to_matches(results)
    assert [m["id"] for m in matches] == ["2756921", "2688156"]

    dannon = matches[0]["metadata"]
    serving_size_g, _ = get_serving_size_g(dannon)
    assert scale_nutrients(dannon, serving_size_g)["calories"] == 80.0

    nido = matches[1]["metadata"]
    serving_size_g, _ = get_serving_size_g(nido)
    assert scale_nutrients(nido, serving_size_g)["calories"] == 150.0
