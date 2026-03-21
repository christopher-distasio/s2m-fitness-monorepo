from fastapi import APIRouter
from pydantic import BaseModel
from backend.models import FoodLog

router = APIRouter()


class FoodLogRequest(BaseModel):
    user_id: str
    raw_input: str
    food_name: str


@router.post("/food")
async def log_food(request: FoodLogRequest):
    food_log = FoodLog(
        user_id=request.user_id,
        raw_input=request.raw_input,
        food_name=request.food_name,
    )
    await food_log.insert()
    return {"message": "Food logged successfully", "id": str(food_log.id)}