"""evaluate_restrictions is a pure function — no logging, no LLM."""

from backend.models import AllergyConstraint, DietaryPreferences, Tier1Preferences
from backend.models.food_event import FoodEvent
from backend.services.restriction_eval import (
    ADVISORY_LANGUAGE_MAPS_TO,
    evaluate_restrictions,
)


def _prefs(*, allergen: str, severity: str) -> DietaryPreferences:
    return DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={allergen: AllergyConstraint(enabled=True, severity=severity)}
        )
    )


def test_advisory_language_constant_is_unknown():
    assert ADVISORY_LANGUAGE_MAPS_TO == "unknown"


def test_contains_severe_blocks_without_logging():
    verdict = evaluate_restrictions(
        {"allergens": ["peanut"], "allergen_state": {"peanut": "contains"}},
        _prefs(allergen="peanut", severity="severe"),
    )
    assert verdict.verdict == "block"
    assert verdict.hits[0].tag == "peanut"
    assert verdict.hits[0].state == "contains"


def test_contains_moderate_warns():
    verdict = evaluate_restrictions(
        {"allergens": ["milk"]},
        _prefs(allergen="milk", severity="moderate"),
    )
    assert verdict.verdict == "warn"
    assert verdict.reasons == ["Contains milk (moderate)"]


def test_unknown_moderate_warns():
    verdict = evaluate_restrictions(
        {"milk": "UNKNOWN"},
        _prefs(allergen="milk", severity="moderate"),
    )
    assert verdict.verdict == "warn"


def test_free_allows():
    verdict = evaluate_restrictions(
        {"allergen_state": {"peanut": "free"}},
        _prefs(allergen="peanut", severity="severe"),
    )
    assert verdict.verdict == "allowed"


def test_food_event_input_works():
    event = FoodEvent(food="yogurt", allergen_state={"milk": "contains"})
    verdict = evaluate_restrictions(event, _prefs(allergen="milk", severity="severe"))
    assert verdict.verdict == "block"


def test_no_profile_allows():
    verdict = evaluate_restrictions({"allergens": ["peanut"]}, None)
    assert verdict.verdict == "allowed"


def test_blocked_by_allergy_lookup_shape():
    verdict = evaluate_restrictions(
        {"blocked_by_allergy": True, "reasoning": "no safe matches"},
        _prefs(allergen="peanut", severity="severe"),
    )
    assert verdict.verdict == "block"
    assert "no safe matches" in verdict.reasons[0]
