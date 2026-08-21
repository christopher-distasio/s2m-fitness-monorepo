"""Voice correct_last: edit the prior log in place. Never insert a phantom log.

Choice (stated for the PR): this handler updates the existing FoodLog /
FoodEvent. It does not create a replacement record.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.models import Correction, DietaryPreferences, FoodLog, UserProfile
from backend.services.allergy_check import check_allergy_block
from backend.services.food_event_build import food_event_from_parsed
from backend.services.food_parser import parse_food_input
from backend.services.user_logs import latest_log_for_user

# Corrections only apply to a recent entry, not an old log from days ago.
CORRECT_LAST_RECENCY = timedelta(hours=24)

NOTHING_TO_CORRECT_MESSAGE = "There's nothing recent to correct."


def _flatten_nutrients(parsed: dict) -> dict[str, float] | None:
    extras = parsed.get("nutrients") or None
    if not extras:
        return None
    sample = next(iter(extras.values()), None)
    if isinstance(sample, dict):
        return {
            k: v["value"]
            for k, v in extras.items()
            if isinstance(v, dict) and v.get("value") is not None
        }
    return extras


def apply_parsed_to_food_log(
    food_log: FoodLog,
    parsed: dict,
    raw_input: str,
    food_name: str | None = None,
) -> None:
    """Mutate an existing log with newly parsed values. Does not insert."""
    extras = _flatten_nutrients(parsed)
    food_log.raw_input = raw_input
    food_log.food_name = food_name or parsed.get("food") or food_log.food_name
    food_log.calories = parsed.get("calories")
    macros = parsed.get("macronutrients", {}) or {}
    food_log.protein = macros.get("protein")
    food_log.carbs = macros.get("carbohydrates")
    food_log.fat = macros.get("fats")
    food_log.extra_nutrients = extras
    food_log.quantity = parsed.get("serving_size")
    food_log.confidence = parsed.get("confidence")
    food_log.reasoning = parsed.get("reasoning")
    food_log.alternatives = parsed.get("alternatives")
    food_log.modified_at = datetime.now(timezone.utc)

    stored_event = parsed.get("food_event")
    events = parsed.get("food_events")
    if isinstance(events, list) and events:
        stored_event = events[0]
    if stored_event is None and parsed.get("food"):
        stored_event = food_event_from_parsed(
            parsed, raw_input=raw_input
        ).model_dump()
    if isinstance(stored_event, dict):
        food_log.food_event = stored_event
        food_log.resolution_audit = stored_event.get("resolution_audit")


def _is_unresolved(parsed: dict) -> bool:
    if parsed.get("resolution_status") == "unresolved":
        return True
    return (parsed.get("resolution") or {}).get("status") == "unresolved"


async def _load_dietary_preferences(user_id: str) -> DietaryPreferences | None:
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        return None
    return profile.dietary_preferences


def _correction_type(food_log: FoodLog, parsed: dict) -> str:
    food_changed = (food_log.food_name or "").lower() != (parsed.get("food") or "").lower()
    quantity_changed = food_log.quantity != parsed.get("serving_size")
    if food_changed and quantity_changed:
        return "both"
    if food_changed:
        return "food"
    return "quantity"


async def handle_correct_last(
    user_id: str,
    raw_input: str,
    *,
    history: list[dict] | None = None,
    asr: float | None = None,
) -> dict:
    """Apply a correction to the user's most recent in-window log.

    Returns a voice-route payload. Never inserts a new FoodLog.
    """
    last = await latest_log_for_user(user_id, recency=CORRECT_LAST_RECENCY)
    if last is None:
        return {
            "message": NOTHING_TO_CORRECT_MESSAGE,
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
        }

    parsed = await parse_food_input(
        raw_input,
        history or [],
        user_id=user_id,
        input_modality="voice",
        activation="push_to_talk",
        asr=asr,
    )
    if parsed.get("error") == "nutrition_unavailable":
        return {
            "error": "nutrition_unavailable",
            "message": parsed.get("message")
            or "Nutrition search is temporarily unavailable. Please try again.",
            "raw": parsed.get("raw"),
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
        }
    if parsed.get("error") or _is_unresolved(parsed):
        return {
            "message": parsed.get("reasoning")
            or parsed.get("message")
            or "I didn't recognize that as a food I can look up. Nothing was changed.",
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
            "resolution_status": parsed.get("resolution_status") or "unresolved",
        }

    prefs = await _load_dietary_preferences(user_id)
    blocked, reason = check_allergy_block(parsed, prefs)
    if blocked:
        return {
            "transcription": raw_input,
            "error": "allergy_block",
            "message": reason or "Blocked by dietary safety filter",
            "logged": False,
            "corrected": False,
        }

    correction = Correction(
        user_id=user_id,
        log_id=str(last.id),
        original_food=last.food_name,
        original_calories=last.calories,
        original_confidence=last.confidence,
        corrected_food=parsed.get("food"),
        corrected_calories=parsed.get("calories"),
        correction_type=_correction_type(last, parsed),
    )
    apply_parsed_to_food_log(last, parsed, raw_input)
    await last.save()
    await correction.insert()

    label = last.food_name or parsed.get("food") or "your last entry"
    return {
        "message": f"Updated your last entry to {label}.",
        "transcription": raw_input,
        "id": str(last.id),
        "logged": False,
        "corrected": True,
    }
