from beanie import Document
from pydantic import BaseModel, Field
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
    modified_at: Optional[datetime] = None

    class Settings:
        name = "food_logs"
    
class UserProfile(Document):
    user_id: str
    calorie_goal: float = 2000.0
    first_name: str = ""
    last_name: str = ""
    screen_name: str = ""
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "user_profiles"

class Correction(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    original_transcript: str
    user_correction: dict  # {"food": "...", "quantity": "...", ...}
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


    
    