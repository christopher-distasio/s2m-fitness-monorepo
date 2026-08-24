"""Spec 3 — verbosity (floor) + Safety Mode (content) + voice allergen read-back."""

from __future__ import annotations

from types import SimpleNamespace

from backend.models import AllergyConstraint, DietaryPreferences, Tier1Preferences
from backend.models import UserProfile
from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.allergen_readback import (
    apply_readback_to_event,
    classify_readback_reply,
    defer_allergen_fields,
    explicit_allergen_declarations,
    needs_allergen_readback,
    readback_prompt,
)
from backend.services.confirmation import evaluate_confirmation
from backend.services.response_compose import (
    PROTECTED_RESPONSE_TYPES,
    VERBOSITY_TABLE,
    compose_response,
    contains_calorie_metric,
    contains_energy_language,
    settings_from_profile,
)
from backend.services.restriction_eval import evaluate_restrictions
from backend.services.safety_detector import MEDICAL_ACKNOWLEDGMENT, SELF_HARM_RESPONSE


def _parsed(bands: dict[str, str] | None = None, **extra) -> dict:
    detail = {key: {"band": "high"} for key in CONFIDENCE_FIELD_KEYS}
    for key, band in (bands or {}).items():
        detail[key] = {"band": band}
    out = {
        "food": extra.pop("food", "yogurt"),
        "calories": extra.pop("calories", 150),
        "confidence_detail": detail,
        "macronutrients": extra.pop(
            "macronutrients",
            {"protein": 12, "carbohydrates": 8, "fats": 4},
        ),
    }
    out.update(extra)
    return out


def test_user_profile_spec3_field_defaults():
    fields = UserProfile.model_fields
    assert fields["verbosity_level"].default == "standard"
    assert fields["safety_mode_enabled"].default is False


def test_verbosity_defaults_and_table_has_no_safety_types():
    verbosity, safety = settings_from_profile(SimpleNamespace())
    assert verbosity == "standard"
    assert safety is False
    for protected in PROTECTED_RESPONSE_TYPES:
        assert protected not in VERBOSITY_TABLE


def test_safety_mode_log_confirmation_has_no_energy_language_at_any_verbosity():
    ctx = {
        "food": "eggs",
        "calories": 180,
        "protein": 12,
        "carbs": 1,
        "fat": 10,
        "calorie_goal": 2000,
        "entry_count": 1,
    }
    for level in ("quick", "standard", "careful"):
        text = compose_response(
            "log_confirmation",
            ctx,
            verbosity_level=level,
            safety_mode_enabled=True,
        )
        assert "Logged eggs" in text
        assert not contains_energy_language(text)
        assert not contains_calorie_metric(text)
        assert "left" not in text.lower()
        assert "offset" not in text.lower()
        assert "burn" not in text.lower()


def test_safety_mode_does_not_suppress_restriction_verdicts():
    prefs = DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={"peanut": AllergyConstraint(enabled=True, severity="severe")}
        )
    )
    verdict = evaluate_restrictions(
        {"allergens": ["peanut"], "allergen_state": {"peanut": "contains"}},
        prefs,
    )
    assert verdict.verdict == "block"
    spoken = compose_response(
        "log_confirmation",
        {
            "food": "peanut butter",
            "calories": 190,
            "restriction_reasons": verdict.reasons,
        },
        verbosity_level="quick",
        safety_mode_enabled=True,
    )
    assert not contains_calorie_metric(spoken)
    assert "Contains peanut" in spoken
    assert "The record shows" in spoken


def test_spec0_safety_response_identical_across_verbosity():
    for level in ("quick", "standard", "careful"):
        crisis = compose_response(
            "spec0_safety",
            {"message": SELF_HARM_RESPONSE},
            verbosity_level=level,
            safety_mode_enabled=True,
        )
        medical = compose_response(
            "spec0_safety",
            {"message": MEDICAL_ACKNOWLEDGMENT},
            verbosity_level=level,
            safety_mode_enabled=False,
        )
        assert crisis == SELF_HARM_RESPONSE
        assert medical == MEDICAL_ACKNOWLEDGMENT
        assert crisis == compose_response(
            "spec0_safety",
            {"message": SELF_HARM_RESPONSE},
            verbosity_level="careful",
            safety_mode_enabled=False,
        )


def test_spec2_ask_fires_regardless_of_safety_mode():
    parsed = _parsed({"amount": "low", "food": "high"}, food="soup")
    decision = evaluate_confirmation(parsed, "some soup")
    assert decision.action == "ASK"
    assert decision.question
    asked = compose_response(
        "spec2_ask",
        {"question": decision.question},
        verbosity_level="quick",
        safety_mode_enabled=True,
    )
    assert asked == decision.question
    assert "Logged" not in asked


def test_voice_high_confidence_no_peanuts_requires_readback():
    parsed = _parsed()
    assert parsed["confidence_detail"]["negation"]["band"] == "high"
    assert parsed["confidence_detail"]["allergen_match"]["band"] == "high"
    attach = evaluate_confirmation(parsed, "yogurt with no peanuts")
    parsed["confirmation"] = attach.to_payload()
    assert parsed["confirmation"]["action"] == "SILENT"
    assert needs_allergen_readback(parsed, "yogurt with no peanuts", "voice")
    assert "no peanuts" in explicit_allergen_declarations("yogurt with no peanuts")[0]
    prompt = readback_prompt("no peanuts")
    spoken = compose_response(
        "allergen_readback",
        {"message": prompt},
        verbosity_level="quick",
        safety_mode_enabled=True,
    )
    assert spoken == "Logging: no peanuts. Is that correct?"


def test_unrelated_negation_does_not_trigger_readback():
    parsed = _parsed()
    parsed["confirmation"] = evaluate_confirmation(parsed, "yogurt with no salt").to_payload()
    assert not needs_allergen_readback(parsed, "yogurt with no salt", "voice")


def test_typed_no_peanuts_does_not_require_readback():
    parsed = _parsed()
    parsed["confirmation"] = evaluate_confirmation(
        parsed, "yogurt with no peanuts"
    ).to_payload()
    assert not needs_allergen_readback(parsed, "yogurt with no peanuts", "text")
    assert not needs_allergen_readback(parsed, "yogurt with no peanuts", None)


def test_declining_readback_leaves_negation_unresolved():
    parsed = defer_allergen_fields(_parsed(), "no peanuts")
    event = parsed["food_event"]
    assert event["allergen_readback"]["status"] == "pending"
    assert event["stated_negation"] is None
    declined = apply_readback_to_event(event, "no")
    assert declined["allergen_readback"]["status"] == "unresolved"
    assert declined["stated_negation"] is None
    timed_out = apply_readback_to_event(event, "other")
    assert timed_out["allergen_readback"]["status"] == "unresolved"
    assert timed_out["stated_negation"] is None
    confirmed = apply_readback_to_event(event, "yes")
    assert confirmed["allergen_readback"]["status"] == "confirmed"
    assert confirmed["stated_negation"] == "no peanuts"


def test_readback_reply_classifier():
    assert classify_readback_reply("yes") == "yes"
    assert classify_readback_reply("that's right") == "yes"
    assert classify_readback_reply("no") == "no"
    assert classify_readback_reply("two eggs") == "other"


def test_verbosity_changes_routine_length_but_not_protected_types():
    ctx = {"food": "toast", "calories": 80, "protein": 3, "carbs": 14, "fat": 1}
    quick = compose_response("log_confirmation", ctx, verbosity_level="quick")
    careful = compose_response("log_confirmation", ctx, verbosity_level="careful")
    assert len(careful) > len(quick)
    assert "calories" not in quick.lower()
    assert "calories" in careful.lower()
