"""Spec 1 FoodEvent / UtteranceResult schema tests."""

from backend.models.food_event import (
    CONFIDENCE_FIELD_KEYS,
    FieldConfidence,
    FoodEvent,
    UtteranceResult,
    empty_confidence_map,
)
from backend.services.food_event_build import food_event_from_parsed


def test_food_event_defaults():
    event = FoodEvent()
    assert event.item_type == "food"
    assert event.visibility == "private"
    assert event.entry_mode == "resolved"
    assert event.consumption_fraction == 1.0
    assert event.resolution_status == "resolved"


def test_direct_macro_allows_empty_food():
    event = FoodEvent(entry_mode="direct_macro", food=None, calories=300)
    assert event.food is None
    assert event.resolution_status == "resolved"
    parsed = event.to_legacy_parsed()
    assert parsed["entry_mode"] == "direct_macro"
    assert parsed["calories"] == 300


def test_confidence_keys_populated():
    event = food_event_from_parsed(
        {
            "food": "banana",
            "brand": None,
            "serving_size": "1",
            "calories": 89,
            "confidence": "high",
            "macronutrients": {"carbohydrates": 23, "protein": 1, "fats": 0},
        },
        raw_input="one banana",
    )
    for key in CONFIDENCE_FIELD_KEYS:
        assert key in event.confidence
        assert event.confidence[key].band in {"high", "medium", "low"}
    assert event.provenance["food"] == "user_stated"
    legacy = event.to_legacy_parsed()
    assert legacy["food"] == "banana"
    assert legacy["calories"] == 89
    assert "confidence_detail" in legacy


def test_hedged_input_sets_user_approximate():
    event = food_event_from_parsed(
        {"food": "chicken", "serving_size": "1", "confidence": "medium"},
        raw_input="I think it was chicken",
    )
    assert event.provenance["food"] == "user_approximate"


def test_consumption_fraction_not_inferred():
    event = food_event_from_parsed(
        {
            "food": "pizza",
            "serving_size": "1",
            "consumption_fraction": 0.5,
            "confidence": "high",
        }
    )
    assert event.consumption_fraction == 1.0


def test_food_event_from_parsed_accepts_dumped_confidence_map():
    """POST /food re-walks food_events dumps where confidence is per-field dicts."""
    dumped = food_event_from_parsed(
        {"food": "yogurt", "serving_size": "1", "calories": 90, "confidence": "high"},
        raw_input="great value light greek yogurt",
    ).model_dump(mode="python")
    assert isinstance(dumped["confidence"], dict)
    event = food_event_from_parsed(dumped, raw_input="great value light greek yogurt")
    assert event.food == "yogurt"
    assert event.calories == 90
    legacy = event.to_legacy_parsed()
    assert legacy["confidence"] in {"high", "medium", "low"}


def test_utterance_result_is_list_and_explicit_user():
    banana = FoodEvent(food="banana")
    toast = FoodEvent(food="toast")
    coffee = FoodEvent(food="coffee", item_type="beverage")
    utterance = UtteranceResult(
        food_events=[banana, toast, coffee],
        subject_user_id="user-1",
        input_modality="text",
    )
    assert len(utterance.food_events) == 3
    assert utterance.subject_user_id == "user-1"
    assert utterance.activation is None
    payload = utterance.to_parse_response()
    assert payload["food"] == "banana"
    assert len(payload["food_events"]) == 3


def test_voice_activation_null_for_barcode():
    utterance = UtteranceResult(
        food_events=[FoodEvent(food="bar")],
        subject_user_id="u",
        input_modality="barcode",
        activation=None,
    )
    assert utterance.activation is None


def test_empty_confidence_map_has_all_keys():
    mapping = empty_confidence_map(band="low")
    assert set(mapping) == set(CONFIDENCE_FIELD_KEYS)
    assert all(isinstance(v, FieldConfidence) for v in mapping.values())
