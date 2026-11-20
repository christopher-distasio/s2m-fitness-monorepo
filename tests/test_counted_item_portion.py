"""A counted food ("3 eggs") defaults to one whole item, not USDA's first portion."""
import json

from backend.services.food_parser import _is_plain_count
from backend.services.nutrition_service import counted_item_portion


def _meta(name, portions):
    return {"description": name, "portions_json": json.dumps(portions)}


EGG = _meta("Egg, whole, cooked, hard-boiled", [
    {"amount": 1.0, "modifier": "cup, chopped", "gram_weight": 136.0, "description": ""},
    {"amount": 1.0, "modifier": "tbsp", "gram_weight": 8.5, "description": ""},
    {"amount": 1.0, "modifier": "large", "gram_weight": 50.0, "description": ""},
])
FILLET = _meta("Chicken fillet, grilled", [
    {"amount": 0.0, "modifier": "61508", "gram_weight": 16.0, "description": "1 nugget"},
    {"amount": 0.0, "modifier": "60765", "gram_weight": 100.0, "description": "1 fillet"},
    {"amount": 0.0, "modifier": "51000", "gram_weight": 17.0, "description": "1 cubic inch"},
    {"amount": 0.0, "modifier": "90000", "gram_weight": 100.0, "description": "Quantity not specified"},
])


def test_egg_picks_large_over_cup_and_tbsp():
    assert counted_item_portion(EGG, "hard boiled egg")["gram_weight"] == 50.0


def test_portion_named_after_the_food_beats_other_items():
    assert counted_item_portion(FILLET, "grilled chicken breast")["description"] == "1 fillet"


def test_medium_preferred_over_small_and_large():
    meta = _meta("Apples, raw", [
        {"amount": 1.0, "modifier": "large", "gram_weight": 223.0, "description": ""},
        {"amount": 1.0, "modifier": "medium", "gram_weight": 182.0, "description": ""},
        {"amount": 1.0, "modifier": "small", "gram_weight": 149.0, "description": ""},
    ])
    assert counted_item_portion(meta, "apple")["gram_weight"] == 182.0


def test_only_measures_means_no_override():
    meta = _meta("Rice, white, cooked", [
        {"amount": 1.0, "modifier": "cup", "gram_weight": 158.0, "description": ""},
        {"amount": 1.0, "modifier": "oz", "gram_weight": 28.35, "description": ""},
    ])
    assert counted_item_portion(meta, "cooked rice") is None


def test_plain_count_detection():
    assert _is_plain_count({"quantity_kind": "count", "serving_size": "3"})
    assert _is_plain_count({"quantity_kind": "count", "serving_size": "1/2"})
    assert not _is_plain_count({"quantity_kind": "measure", "serving_size": "2 cups"})
    assert not _is_plain_count({"quantity_kind": "count", "serving_size": "2 slices"})
    assert not _is_plain_count({"quantity_kind": "count", "serving_size": "1", "unit": "slice"})
