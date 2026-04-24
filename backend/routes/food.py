from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from backend.models import FoodLog, Correction
from backend.services.food_parser import parse_food_input
from backend.services.transcriber import transcribe_audio
from beanie import PydanticObjectId
from datetime import datetime, timezone, timedelta
from backend.services.intent_classifier import classify_intent
from backend.services.nutrition_service import parse_nutrition


router = APIRouter()


class FoodLogRequest(BaseModel):
    user_id: str
    raw_input: str
    food_name: Optional[str] = None

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

    
def build_food_log(user_id: str, raw_input: str, parsed: dict, food_name: Optional[str] = None) -> FoodLog:
    macros = parsed.get("macronutrients", {})
    return FoodLog(
        user_id=user_id,
        raw_input=raw_input,
        food_name=food_name or parsed["food"],
        calories=parsed.get("calories"),
        protein=macros.get("protein"),
        carbs=macros.get("carbohydrates"),
        fat=macros.get("fats"),
        quantity=parsed.get("serving_size"),
        confidence=parsed.get("confidence"),
        reasoning=parsed.get("reasoning"),
        alternatives=parsed.get("alternatives"),
    )

def build_response(food_log: FoodLog, parsed: dict, transcription: Optional[str] = None) -> dict:
    response = {
        "message": "Food logged successfully",
        "id": str(food_log.id),
        "parsed": {
            "food": parsed["food"],
            "calories": parsed.get("calories"),
            "confidence": parsed.get("confidence"),
        }
    }
    if transcription:
        response["transcription"] = transcription
    return response


@router.post("/food")
async def log_food(request: FoodLogRequest):
    parsed = await parse_food_input(request.raw_input)

    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")

    food_log = build_food_log(request.user_id, request.raw_input, parsed, request.food_name)
    await food_log.insert()

    return build_response(food_log, parsed)

@router.post("/food/voice")
async def log_food_voice(
    user_id: str = Form(...),
    audio: UploadFile = File(...),
):
    audio_bytes = await audio.read()
    raw_input = await transcribe_audio(audio_bytes, audio.filename)

    intent = await classify_intent(raw_input)

    if intent["intent"] == "delete_last":
        last = await FoodLog.find(FoodLog.user_id == user_id).sort(-FoodLog.logged_at).first_or_none()
        if last:
            await last.delete()
            return {"message": "Last entry deleted", "transcription": raw_input}
        return {"message": "No entries to delete", "transcription": raw_input}

    if intent["intent"] == "calories_today":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = await FoodLog.find(FoodLog.user_id == user_id, FoodLog.logged_at >= start).to_list()
        total = sum(log.calories or 0 for log in logs)
        return {"message": f"You have logged {total} calories today", "transcription": raw_input}

    if intent["intent"] == "read_today":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = await FoodLog.find(FoodLog.user_id == user_id, FoodLog.logged_at >= start).to_list()
        names = ", ".join(log.food_name for log in logs) or "nothing yet"
        return {"message": f"Today you ate: {names}", "transcription": raw_input}

    # default — treat as food log
    parsed = await parse_food_input(raw_input)
    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")

    food_log = build_food_log(user_id, raw_input, parsed)
    await food_log.insert()
    return build_response(food_log, parsed, transcription=raw_input)

@router.get("/food/{user_id}/today")
async def get_today_food(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    logs = await FoodLog.find(
        FoodLog.user_id == user_id,
        FoodLog.logged_at >= start_of_day
    ).to_list()
    
    return logs


@router.get("/food/{user_id}/summary")
async def get_daily_summary(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    logs = await FoodLog.find(
        FoodLog.user_id == user_id,
        FoodLog.logged_at >= start_of_day
    ).to_list()

    return {
        "calories": sum(log.calories or 0 for log in logs),
        "protein": sum(log.protein or 0 for log in logs),
        "carbs": sum(log.carbs or 0 for log in logs),
        "fat": sum(log.fat or 0 for log in logs),
        "entry_count": len(logs),
    }
    

@router.get("/food/{user_id}")
async def get_food_logs(user_id: str):
    logs = await FoodLog.find(FoodLog.user_id == user_id).to_list()
    return logs


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

    parsed = await parse_food_input(request.raw_input)
    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")

    food_changed = food_log.food_name.lower() != parsed["food"].lower()
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
        corrected_food=parsed["food"],
        corrected_calories=parsed.get("calories"),
        correction_type=correction_type,
    )
    await correction.insert()

    food_log.raw_input = request.raw_input
    food_log.food_name = request.food_name or parsed["food"]
    food_log.calories = parsed.get("calories")
    macros = parsed.get("macronutrients", {})
    food_log.protein = macros.get("protein")
    food_log.carbs = macros.get("carbohydrates")
    food_log.fat = macros.get("fats")
    food_log.quantity = parsed.get("serving_size")
    food_log.modified_at = datetime.now(timezone.utc)

    await food_log.save()
    return build_response(food_log, parsed)

@router.get("/food/{user_id}/weekly")
async def get_weekly_summary(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)

    logs = await FoodLog.find(
        FoodLog.user_id == user_id,
        FoodLog.logged_at >= start_of_week
    ).to_list()

    days = {}
    for log in logs:
        day = log.logged_at.strftime("%Y-%m-%d")
        if day not in days:
            days[day] = {"date": day, "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "entries": 0}
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
        }
    }

@router.post("/test-confidence")
async def test_confidence(transcript: str):
    """Test confidence parsing with a sample transcript."""
    result = await parse_nutrition(transcript)
    return result

@router.post("/corrections")
async def save_correction(user_id: str, original_transcript: str, correction: dict):
    correction_doc = Correction(
        user_id=user_id,
        original_transcript=original_transcript,
        user_correction=correction
    )

    await db.corrections.insert_one(correction_doc.dict())
    return correction_doc

@router.post("/food/parse")
async def parse_food_only(request: ParseRequest):
    parsed = await parse_food_input(request.raw_input)
    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")
    return parsed