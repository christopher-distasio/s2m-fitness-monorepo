from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from backend.models import FoodLog
from backend.services.food_parser import parse_food_input
from backend.services.transcriber import transcribe_audio

router = APIRouter()


class FoodLogRequest(BaseModel):
    user_id: str
    raw_input: str
    food_name: Optional[str] = None


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
    )


def build_response(food_log: FoodLog, parsed: dict, transcription: Optional[str] = None) -> dict:
    response = {
        "message": "Food logged successfully",
        "id": str(food_log.id),
        "parsed": {
            "food": parsed["food"],
            "calories": parsed.get("calories"),
            "confidence": parsed.get("confidence"),
            "notes": parsed.get("notes"),
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

    parsed = await parse_food_input(raw_input)

    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")

    food_log = build_food_log(user_id, raw_input, parsed)
    await food_log.insert()

    return build_response(food_log, parsed, transcription=raw_input)


from datetime import datetime, timezone

@router.get("/food/{user_id}/today")
async def get_today_food(user_id: str):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    logs = await FoodLog.find(
        FoodLog.user_id == user_id,
        FoodLog.logged_at >= start_of_day
    ).to_list()
    
    return logs
    

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


@router.put("/food/{log_id}")
async def update_food_log(log_id: str, request: FoodLogRequest):
    food_log = await FoodLog.get(log_id)
    if not food_log:
        raise HTTPException(status_code=404, detail="Food log not found")

    parsed = await parse_food_input(request.raw_input)

    if "error" in parsed:
        raise HTTPException(status_code=422, detail=f"Could not parse food input: {parsed}")

    food_log.raw_input = request.raw_input
    food_log.food_name = request.food_name or parsed["food"]
    food_log.calories = parsed.get("calories")
    macros = parsed.get("macronutrients", {})
    food_log.protein = macros.get("protein")
    food_log.carbs = macros.get("carbohydrates")
    food_log.fat = macros.get("fats")
    food_log.quantity = parsed.get("serving_size")
    from datetime import datetime, timezone
    food_log.modified_at = datetime.now(timezone.utc)

    await food_log.save()
    return build_response(food_log, parsed)

