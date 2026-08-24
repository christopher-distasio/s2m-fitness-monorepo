from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from backend.models import FoodLog, Correction, UserProfile, DietaryPreferences
from backend.services.food_parser import parse_food_input
from backend.services.transcriber import transcribe_audio_detailed
from backend.services.allergy_check import check_allergy_block, moderate_allergy_warnings
from beanie import PydanticObjectId
from datetime import datetime, timezone, timedelta
from backend.services.utterance_pipeline import (
    dispatch_voice_utterance,
    run_safety_and_domain,
)
from backend.services.confirmation import (
    apply_self_repair,
    attach_confirmation,
    resolve_confirmation_reply,
    spoken_candidates_from_history,
)
from backend.services.clarification import (
    parse_clarification_command,
    parse_brand_choice,
    parse_timeout_choice,
    parse_stop_command,
    clarification_state,
)
from backend.services.tts_service import speak
from backend.services.correct_last import (
    apply_food_event_correction,
    identity_fields_changed,
)
from backend.services.edit_entry import factual_restriction_message, handle_edit_entry
from backend.services.restriction_eval import evaluate_restrictions
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
    brand: Optional[str] = None
    variant: Optional[str] = None
    preparation: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None


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


def _is_brand_choice(parsed: dict) -> bool:
    return (parsed.get("resolution") or {}).get("status") == "needs_brand_choice"


def _ask_payload(parsed: dict, *, transcription: str | None = None) -> dict:
    confirmation = parsed.get("confirmation") or {}
    payload = {
        "logged": False,
        "confirmation": confirmation,
        "parsed": parsed,
        "message": confirmation.get("question"),
    }
    if transcription is not None:
        payload["transcription"] = transcription
    return payload


async def _parse_log_utterance(
    raw_input: str,
    conversation_history: list | None = None,
    **kwargs,
) -> dict:
    """Parse a log utterance: self-repair rewrite, then Spec 2 confirmation."""
    text, repaired = apply_self_repair(raw_input)
    parsed = await parse_food_input(text, conversation_history or [], **kwargs)
    if parsed.get("error") or _is_unresolved(parsed) or _is_brand_choice(parsed):
        return parsed
    if parsed.get("confidence") == "blocked":
        return parsed
    attach_confirmation(parsed, raw_input, self_repaired=repaired)
    return parsed


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
    markers = (parsed.get("confirmation") or {}).get("markers") or None
    if isinstance(stored_event, dict) and markers:
        stored_event = {**stored_event, "confirmation_markers": markers}
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
        confirmation_markers=(parsed.get("confirmation") or {}).get("markers") or None,
    )


def _overlay_structured_edit(parsed: dict, request: FoodLogRequest) -> None:
    """Tap-to-edit fields win over re-parse; keep food_event in sync."""
    event = parsed.get("food_event")
    if not isinstance(event, dict):
        event = {}
        parsed["food_event"] = event
    if request.brand is not None:
        parsed["brand"] = request.brand
        event["brand"] = request.brand
    if request.preparation is not None:
        parsed["preparation"] = request.preparation
        event["preparation"] = request.preparation
    if request.amount is not None:
        parsed["amount"] = request.amount
        event["amount"] = request.amount
    if request.unit is not None:
        parsed["unit"] = request.unit
        event["unit"] = request.unit
    if request.variant:
        parsed["variant"] = request.variant
        event["variant_tags"] = [{"type": "variant", "value": request.variant}]
    if request.food_name:
        parsed["food"] = request.food_name
        event["food"] = request.food_name
    if request.amount is not None or request.unit:
        amount = request.amount if request.amount is not None else event.get("amount")
        unit = request.unit or event.get("unit") or ""
        if amount is not None:
            parsed["serving_size"] = f"{amount} {unit}".strip()


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
    confirmation = parsed.get("confirmation")
    if confirmation:
        response["confirmation"] = confirmation
    return response


@router.post("/food/parse")
async def parse_food(request: ParseRequest):
    """
    Parse-only endpoint used by the frontend to decide whether to auto-log
    (high confidence) or ask the user to confirm (medium/low confidence).
    """
    gated = await run_safety_and_domain(request.raw_input, request.user_id)
    if gated.response is not None:
        return gated.response
    parsed = await _parse_log_utterance(
        request.raw_input,
        request.conversation_history,
        source_filter=request.source_filter,
        user_id=request.user_id,
    )
    if parsed.get("error") == "nutrition_unavailable":
        return _nutrition_unavailable_response(parsed)
    return parsed


@router.post("/food")
async def log_food(request: FoodLogRequest):
    gated = await run_safety_and_domain(request.raw_input, request.user_id)
    if gated.response is not None:
        return gated.response

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

    parsed = await _parse_log_utterance(request.raw_input, user_id=request.user_id)

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

    if (parsed.get("confirmation") or {}).get("action") == "ASK":
        return _ask_payload(parsed)

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
    if state == "edit_entry":
        return await handle_edit_entry(
            user_id, raw_input, history=history, asr=transcript.asr
        )
    if state == "list":
        spoken = spoken_candidates_from_history(history)
        command = resolve_confirmation_reply(raw_input, spoken) if spoken else parse_clarification_command(raw_input)
        if command:
            return {"transcription": raw_input, "clarification": command}
        return {
            "transcription": raw_input,
            "clarification": {"type": "unrecognized"},
        }

    dispatched = await dispatch_voice_utterance(
        raw_input,
        user_id,
        history=history,
        asr=transcript.asr,
    )
    if dispatched.response is not None:
        return dispatched.response

    # default — treat as food log (text path still bypasses intent classification)
    parsed = await _parse_log_utterance(
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

    if _is_unresolved(parsed):
        return {"transcription": raw_input, "parsed": parsed, "logged": False}

    if _is_brand_choice(parsed):
        return {"transcription": raw_input, "parsed": parsed}

    if (parsed.get("confirmation") or {}).get("action") == "ASK":
        return _ask_payload(parsed, transcription=raw_input)

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

    _overlay_structured_edit(parsed, request)

    previous_event = dict(food_log.food_event) if isinstance(food_log.food_event, dict) else {}
    previous_name = food_log.food_name

    await apply_food_event_correction(
        food_log,
        parsed,
        request.user_id,
        raw_input=request.raw_input,
        food_name=request.food_name,
    )

    response = _with_allergy_warning(build_response(food_log, parsed), warnings)
    after_event = (
        food_log.food_event if isinstance(food_log.food_event, dict) else parsed
    )
    if identity_fields_changed(
        previous_event,
        after_event,
        before_name=previous_name,
        after_name=food_log.food_name,
    ):
        verdict = evaluate_restrictions(after_event or parsed, user_prefs)
        response["restriction_verdict"] = verdict.model_dump()
        restriction_message = factual_restriction_message(
            previous_event, after_event or parsed, verdict
        )
        if restriction_message:
            response["restriction_update"] = restriction_message
    return response


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
