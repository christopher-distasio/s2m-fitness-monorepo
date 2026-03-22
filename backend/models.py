from beanie import Document
from pydantic import Field
from typing import Optional
from datetime import datetime

class FoodLog(Document):
    user_id: str
    raw_input: str
    food_name: str
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    quantity: Optional[str] = None
    logged_at: datetime = Field(default_factory=datetime.utcnow)

class Settings:
    name = "food_logs"
    