from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from backend.models import FoodLog, Correction, UserProfile, DietaryPreferences
from backend.services.food_parser import parse_food_input
from backend.services.transcriber import transcribe_audio_detailed
from backend.services.allergy_check import check_allergy_block, moderate_allergy_warnings
from beanie import PydanticObjectId
from datetime import datetime, timezone, timedelta
from backend.services.intent_classifier import classify_intent
from backend.services.clarification import (
    parse_clarification_command,
    parse_brand_choice,
    parse_timeout_choice,
    parse_stop_command,
    clarification_state,
)
from backend.services.tts_service import speak
from fastapi.responses import JSONResponse, Response
import json

router = APIRouter()


async def _load_dietary_preferences(user_id: str | None) -> DietaryPreferences | None:
    if not user_id:
        return None
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        return None
    return profile.dietary_preferences


def _apply_allergy_gate(parsed: dict, user_prefs: DietaryPreferences | None) -> list[str]:
    """Raise 403 on severe block; return moderate warnings for the response."""
    is_blocked, reason = check_allergy_block(parsed, user_prefs)
    if is_blocked:
        raise HTTPException(
            status_code=403,
            detail=reason or "Blocked by dietary safety filter",
        )
    return moderate_allergy_warnings(parsed, user_prefs)


def _with_allergy_warning(response: dict, warnings: list[str]) -> dict:
    if warnings:
        response["allergy_warning"] = warnings
    return response


def _nutrition_unavailable_response(parsed: dict, **extra):
    return JSONResponse(
        status_code=503,
        content={
            "error": "nutrition_unavailable",
            "message": parsed.get("message")
            or "Nutrition search is temporarily unavailable. Please try again.",
            "raw": parsed.get("raw"),
            **extra,
        },
    )


class FoodLogRequest(BaseModel):
    user_id: str
    raw_input: str
    food_name: Optional[str] = None
    resolved: bool = False
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    nutrients: Optional[dict[str, float]] = None
    quantity: Optional[str] = None


class CorrectionRequest(BaseModel):
    user_id: str
    log_id: str
    original_food: str
    original_calories: Optional[float] = None
    original_confidence: Optional[str] = None
    corrected_food: Optional[str] = None
    corrected_calories: Optional[float] = None
    correction_type: Optional[str] = None


class ParseRequest(BaseModel):
    raw_input: str
    conversation_history: list[dict] = []
    source_filter: Optional[str] = None
    # NEW (2026-08-04): needed so parse_food_input can fetch the user's
    # dietary preferences (allergens, vegan/kosher/etc, organic/keto/etc) and
    # apply them to the Qdrant search. Optional so this endpoint still works
    # (unrestricted search) if the frontend doesn't send it — but the
    # frontend's /food/parse calls (submitText, resolveWithSource) do NOT
    # currently send user_id at all, so dietary filtering is a no-op on the
    # text path until that's also updated. Voice logging already sends
    # user_id separately as Form data, so /food/voice is unaffected.
    user_id: Optional[str] = None


class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"


def _is_unresolved(parsed: dict) -> bool:
    if parsed.get("resolution_status") == "unresolved":
        return True
    return (parsed.get("resolution") or {}).get("status") == "unresolved"


def _events_to_log(parsed: dict) -> list[dict]:
    events = parsed.get("food_events")
    if isinstance(events, list) and events:
        from backend.services.food_event_build import food_event_from_parsed

        out = []
        for event in events:
            if isinstance(event, dict):
                out.append(
                    food_event_from_parsed(event, raw_input=parsed.get("raw_transcript")).to_legacy_parsed()
                    if "calories" in event or "food" in event
                    else event
                )
            else:
                out.append(event.to_legacy_parsed())
        # Prefer the already-legacy top-level parse for the first event so
        # scaled calories / candidates match what the client saw.
        if out:
            primary = dict(parsed)
            primary.pop("food_events", None)
            out[0] = primary
        return out
    return [parsed]


def build_food_log(
    user_id: str, raw_input: str, parsed: dict, food_name: Optional[str] = None
) -> FoodLog:
    macros = parsed.get("macronutrients", {})
    extras = parsed.get("nutrients") or {}
    if extras and isinstance(next(iter(extras.values()), None), dict):
        extras = {
            k: v["value"]
            for k, v in extras.items()
            if isinstance(v, dict) and v.get("value") is not None
        }
    display_name = food_name or parsed.get("food") or parsed.get("logged_food_name") or raw_input
    utterance = {
        "intent": parsed.get("intent") or "LOG",
        "subject_user_id": parsed.get("subject_user_id") or user_id,
        "input_modality": parsed.get("input_modality") or "text",
        "activation": parsed.get("activation"),
        "raw_transcript": parsed.get("raw_transcript") or raw_input,
    }
    food_event = parsed.get("food_events", [None])
    stored_event = food_event[0] if isinstance(food_event, list) and food_event else parsed.get("food_event")
    return FoodLog(
        user_id=user_id,
        raw_input=raw_input,
        food_name=display_name,
        calories=parsed.get("calories"),
        protein=macros.get("protein"),
        carbs=macros.get("carbohydrates"),
        fat=macros.get("fats"),
        extra_nutrients=extras or None,
        quantity=parsed.get("serving_size"),
        confidence=parsed.get("confidence"),
        reasoning=parsed.get("reasoning"),
        alternatives=parsed.get("alternatives"),
        food_event=stored_event if isinstance(stored_event, dict) else None,
        utterance=utterance,
        resolution_audit=(stored_event or {}).get("resolution_audit")
        if isinstance(stored_event, dict)
        else None,
    )


def build_response(
    food_log: FoodLog, parsed: dict, transcription: Optional[str] = None
) -> dict:
    response = {
        "message": "Food logged successfully",
        "id": str(food_log.id),
        "parsed": {
            "food": parsed["food"],
            "calories": parsed.get("calories"),
            "confidence": parsed.get("confidence"),
            "notes": parsed.get("notes"),
            "reasoning": parsed.get("reasoning"),
            "alternatives": parsed.get("alternatives"),
        },
    }
    if transcription:
        response["transcription"] = transcription
    return response


@router.post("/food/parse")
async def parse_food(request: ParseRequest):
    """
    Parse-only endpoint used by the frontend to decide whether to auto-log
    (high confidence) or ask the user to confirm (medium/low confidence).
    """
    parsed = await parse_food_input(
        request.raw_input,
        request.conversation_history,
        source_filter=request.source_filter,
        user_id=request.user_id,  # NEW (2026-08-04)
    )
    if parsed.get("error") == "nutrition_unavailable":
        return _nutrition_unavailable_response(parsed)
    return parsed


@router.post("/food")
async def log_food(request: FoodLogRequest):
    if request.resolved:
        food_log = FoodLog(
            user_id=request.user_id,
            raw_input=request.raw_input,
            food_name=request.food_name or request.raw_input,
            calories=request.calories,
            protein=request.protein,
            carbs=request.carbs,
            fat=request.fat,
            extra_nutrients=request.nutrients or None,
            quantity=request.quantity,
            confidence="high",
        )
        await food_log.insert()
        return {
            "message": "Food logged successfully",
            "id": str(food_log.id),
            "parsed": {
                "food": food_log.food_name,
                "calories": food_log.calories,
                "confidence": "high",
                "notes": None,
                "reasoning": None,
                "alternatives": None,
            },
        }

    parsed = await parse_food_input(request.raw_input, user_id=request.user_id)  # NEW: user_id

    if parsed.get("error") == "nutrition_unavailable":
        return _nutrition_unavailable_response(parsed)
    if parsed.get("error"):
        raise HTTPException(
            status_code=422, detail=f"Could not parse food input: {parsed}"
        )

    if _is_unresolved(parsed):
        return {
            "logged": False,
            "resolution_status": "unresolved",
            "message": parsed.get("reasoning")
            or "I didn't recognize that as a food I can look up. Please try a different name or more detail.",
            "parsed": parsed,
        }

    # Severe allergen refusal (lookup zero-safe-results or explicit allergen
    # match). Shared with PATCH so create/edit stay consistent.
    user_prefs = await _load_dietary_preferences(request.user_id)
    warnings = _apply_allergy_gate(parsed, user_prefs)

    inserted = []
    for event_parsed in _events_to_log(parsed):
        if _is_unresolved(event_parsed):
            continue
        food_log = build_food_log(
            request.user_id, request.raw_input, event_parsed, request.food_name
        )
        await food_log.insert()
        inserted.append(food_log)

    if not inserted:
        return {
            "logged": False,
            "resolution_status": "unresolved",
            "message": parsed.get("reasoning")
            or "I didn't recognize that as a food I can look up. Please try a different name or more detail.",
            "parsed": parsed,
        }

    food_log = inserted[0]
    response = _with_allergy_warning(build_response(food_log, parsed), warnings)
    if len(inserted) > 1:
        response["ids"] = [str(item.id) for item in inserted]
    return response


@router.post("/food/voice")
async def log_food_voice(
    user_id: str = Form(...),
    audio: UploadFile = File(...),
    conversation_history: str = Form(default="[]"),
    awaiting_more_time: str = Form(default="false"),
    awaiting_clarification: str = Form(default="false"),
):
    audio_bytes = await audio.read()
    clarify_flag = awaiting_clarification.strip().lower()
    transcript = await transcribe_audio_detailed(
        audio_bytes,
        audio.filename or "recording.webm",
        clarification=clarify_flag
        in ("list", "brand_choice", "true", "1", "yes"),
    )
    raw_input = transcript.text

    history = json.loads(conversation_history)

    if parse_stop_command(raw_input):
        return {
            "transcription": raw_input,
            "clarification": {"type": "stop"},
        }

    if awaiting_more_time.strip().lower() in ("true", "1", "yes"):
        timeout = parse_timeout_choice(raw_input)
        if timeout:
            return {
                "transcription": raw_input,
                "clarification": {"type": timeout},
            }

    state = clarification_state(history)
    flag = clarify_flag
    if state is None:
        if flag == "brand_choice":
            state = "brand_choice"
        elif flag in ("list", "true", "1", "yes"):
            state = "list"
    if state == "brand_choice":
        choice = parse_brand_choice(raw_input)
        if choice:
            return {
                "transcription": raw_input,
                "clarification": {"type": "brand_choice", "value": choice},
            }
        return {
            "transcription": raw_input,
            "clarification": {"type": "unrecognized"},
        }
    if state == "list":
        command = parse_clarification_command(raw_input)
        if command:
            return {"transcription": raw_input, "clarification": command}
        return {
            "transcription": raw_input,
            "clarification": {"type": "unrecognized"},
        }

    intent = await classify_intent(raw_input)

    if intent["intent"] == "delete_last":
        last = (
            await FoodLog.find(FoodLog.user_id == user_id)
            .sort(-FoodLog.logged_at)
            .first_or_none()
        )
        if last:
            await last.delete()
            return {"message": "Last entry deleted", "transcription": raw_input}
        return {"message": "No entries to delete", "transcription": raw_input}

    if intent["intent"] == "calories_today":
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = await FoodLog.find(
            FoodLog.user_id == user_id, FoodLog.logged_at >= start
        ).to_list()
        total = sum(log.calories or 0 for log in logs)
        return {
            "message": f"You have logged {total} calories today",
            "transcription": raw_input,
        }

    if intent["intent"] == "read_today":
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = await FoodLog.find(
            FoodLog.user_id == user_id, FoodLog.logged_at >= start
        ).to_list()
        names = ", ".join(log.food_name for log in logs) or "nothing yet"
        return {"message": f"Today you ate: {names}", "transcription": raw_input}

    # default — treat as food log
    parsed = await parse_food_input(
        raw_input,
        history,
        user_id=user_id,
        input_modality="voice",
        activation="push_to_talk",
        asr=transcript.asr,
    )
    if parsed.get("error") == "nutrition_unavailable":
        return _nutrition_unavailable_response(parsed, transcription=raw_input)
    if parsed.get("error"):
        return {
            "error": parsed.get("error", "unparseable"),
            "raw": parsed.get("raw", raw_input),
            "transcription": raw_input,
        }

    # NOTE: "blocked" already falls through here correctly, since it's not
    # "high" — the frontend receives parsed.reasoning (the safety message)
    # via the normal clarification-style response and speaks it. No extra
    # branch needed on the voice path, unlike POST /food above.
    if _is_unresolved(parsed):
        return {"transcription": raw_input, "parsed": parsed, "logged": False}

    if parsed.get("confidence") != "high":
        return {"transcription": raw_input, "parsed": parsed}

    user_prefs = await _load_dietary_preferences(user_id)
    try:
        warnings = _apply_allergy_gate(parsed, user_prefs)
    except HTTPException as exc:
        return {
            "transcription": raw_input,
            "parsed": parsed,
            "error": "allergy_block",
            "message": exc.detail,
        }

    food_log = build_food_log(user_id, raw_input, parsed)
    await food_log.insert()
    return _with_allergy_warning(
        build_response(food_log, parsed, transcription=raw_input), warnings
    )


@router.post("/food/tts")
async def text_to_speech(request: TTSRequest):
    audio = await speak(request.text, request.voice)
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/food/{user_id}/today")
async def get_today_food(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    logs = await FoodLog.find(
        FoodLog.user_id == user_id, FoodLog.logged_at >= start_of_day
    ).to_list()
    return logs


@router.get("/food/{user_id}/summary")
async def get_daily_summary(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    logs = await FoodLog.find(
        FoodLog.user_id == user_id, FoodLog.logged_at >= start_of_day
    ).to_list()
    nutrients: dict[str, float] = {}
    for log in logs:
        for key, val in (log.extra_nutrients or {}).items():
            if val is None:
                continue
            nutrients[key] = nutrients.get(key, 0.0) + float(val)
    return {
        "calories": sum(log.calories or 0 for log in logs),
        "protein": sum(log.protein or 0 for log in logs),
        "carbs": sum(log.carbs or 0 for log in logs),
        "fat": sum(log.fat or 0 for log in logs),
        "nutrients": {k: round(v, 2) for k, v in nutrients.items()},
        "entry_count": len(logs),
    }


@router.get("/food/{user_id}")
async def get_food_logs(user_id: str):
    logs = await FoodLog.find(FoodLog.user_id == user_id).to_list()
    return logs


@router.delete("/food/{user_id}/all")
async def delete_all_food_logs(user_id: str):
    await FoodLog.find(FoodLog.user_id == user_id).delete()
    return {"message": "All logs deleted"}


@router.delete("/food/{log_id}")
async def delete_food_log(log_id: str):
    food_log = await FoodLog.get(log_id)
    if not food_log:
        raise HTTPException(status_code=404, detail="Food log not found")
    await food_log.delete()
    return {"message": "Food log deleted successfully"}


@router.patch("/food/{log_id}")
async def update_food_log(log_id: str, request: FoodLogRequest):
    food_log = await FoodLog.get(PydanticObjectId(log_id))
    if not food_log:
        raise HTTPException(status_code=404, detail="Food log not found")

    parsed = await parse_food_input(request.raw_input, user_id=request.user_id)  # NEW: user_id
    if parsed.get("error") == "nutrition_unavailable":
        return _nutrition_unavailable_response(parsed)
    if parsed.get("error"):
        raise HTTPException(
            status_code=422, detail=f"Could not parse food input: {parsed}"
        )

    if _is_unresolved(parsed):
        return {
            "logged": False,
            "resolution_status": "unresolved",
            "message": parsed.get("reasoning")
            or "I didn't recognize that as a food I can look up. Please try a different name or more detail.",
            "parsed": parsed,
        }

    # Same severe-allergen gate as POST /food — refuse the edit before any
    # Correction / FoodLog write commits.
    user_prefs = await _load_dietary_preferences(request.user_id)
    warnings = _apply_allergy_gate(parsed, user_prefs)

    food_changed = (food_log.food_name or "").lower() != (parsed.get("food") or "").lower()
    quantity_changed = food_log.quantity != parsed.get("serving_size")

    if food_changed and quantity_changed:
        correction_type = "both"
    elif food_changed:
        correction_type = "food"
    else:
        correction_type = "quantity"

    correction = Correction(
        user_id=request.user_id,
        log_id=log_id,
        original_food=food_log.food_name,
        original_calories=food_log.calories,
        original_confidence=food_log.confidence,
        corrected_food=parsed.get("food"),
        corrected_calories=parsed.get("calories"),
        correction_type=correction_type,
    )
    await correction.insert()

    food_log.raw_input = request.raw_input
    food_log.food_name = request.food_name or parsed.get("food") or food_log.food_name
    food_log.calories = parsed.get("calories")
    macros = parsed.get("macronutrients", {})
    food_log.protein = macros.get("protein")
    food_log.carbs = macros.get("carbohydrates")
    food_log.fat = macros.get("fats")
    food_log.extra_nutrients = parsed.get("nutrients") or None
    food_log.quantity = parsed.get("serving_size")
    food_log.modified_at = datetime.now(timezone.utc)

    await food_log.save()
    return _with_allergy_warning(build_response(food_log, parsed), warnings)


@router.get("/food/{user_id}/weekly")
async def get_weekly_summary(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=6
    )
    logs = await FoodLog.find(
        FoodLog.user_id == user_id, FoodLog.logged_at >= start_of_week
    ).to_list()

    days = {}
    for log in logs:
        day = log.logged_at.strftime("%Y-%m-%d")
        if day not in days:
            days[day] = {
                "date": day,
                "calories": 0,
                "protein": 0,
                "carbs": 0,
                "fat": 0,
                "entries": 0,
            }
        days[day]["calories"] += log.calories or 0
        days[day]["protein"] += log.protein or 0
        days[day]["carbs"] += log.carbs or 0
        days[day]["fat"] += log.fat or 0
        days[day]["entries"] += 1

    return {
        "days": sorted(days.values(), key=lambda x: x["date"]),
        "totals": {
            "calories": sum(log.calories or 0 for log in logs),
            "protein": sum(log.protein or 0 for log in logs),
            "carbs": sum(log.carbs or 0 for log in logs),
            "fat": sum(log.fat or 0 for log in logs),
        },
    }


@router.post("/corrections")
async def save_correction(request: CorrectionRequest):
    correction = Correction(**request.model_dump())
    await correction.insert()
    return {"message": "Correction saved", "id": str(correction.id)}
