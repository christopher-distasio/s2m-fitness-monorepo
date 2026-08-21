"""Old food_logs shape → FoodEvent (dry-run transformer)."""

from migrate_logs_to_food_event import transform_log


def test_legacy_doc_becomes_valid_food_event():
    old = {
        "user_id": "u1",
        "raw_input": "banana",
        "food_name": "banana",
        "calories": 89,
        "protein": 1.1,
        "carbs": 23.0,
        "fat": 0.3,
        "extra_nutrients": {"sodium": 1.0},
        "quantity": "1 medium",
        "confidence": "high",
    }
    new = transform_log(old)
    event = new["food_event"]
    assert event["food"] == "banana"
    assert event["resolution_status"] == "resolved"
    assert event["provenance"]["food"] == "record_default"
    assert event["confidence"]["food"]["band"] == "low"
    assert event["confidence"]["food"]["asr"] is None
    assert new["food_name"] == "banana"
    typed = event["nutrients"]["sodium"]
    assert typed["value"] == 1.0
    assert typed["unit"] == "mg"
    assert typed["usda_nutrient_id"] == 1093


def test_missing_quantity_defaults_count():
    new = transform_log({"food_name": "apple", "user_id": "u"})
    assert new["food_event"]["amount"] == 1.0
    assert new["food_event"]["unit"] == "count"
    assert new["food_event"]["allergen_state"] == {}
