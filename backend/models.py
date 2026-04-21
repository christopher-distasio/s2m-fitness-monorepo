from beanie import Document
from pydantic import Field
from typing import Optional, List
from datetime import datetime, timezone

class FoodLog(Document):
    user_id: str
    raw_input: str
    food_name: str
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    quantity: Optional[str] = None
    confidence: Optional[str] = None       # "high" | "medium" | "low"
    reasoning: Optional[str] = None
    alternatives: Optional[List[str]] = None
    logged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: Optional[datetime] = None

    class Settings:
        name = "food_logs"

class UserProfile(Document):
    user_id: str
    calorie_goal: float = 2000.0
    first_name: str = ""
    last_name: str = ""
    screen_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "user_profiles"

class Correction(Document):
    user_id: str
    log_id: str                            
    original_food: str
    original_calories: Optional[float]
    original_confidence: Optional[str]
    corrected_food: Optional[str] = None
    corrected_calories: Optional[float] = None
    correction_type: Optional[str] = None  # "food" | "quantity" | "both"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "corrections"