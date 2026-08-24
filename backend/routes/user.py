from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Optional
from backend.models import UserProfile, DietaryPreferences


router = APIRouter()


class UpdateProfile(BaseModel):
    calorie_goal: Optional[float] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    screen_name: Optional[str] = None
    voice: Optional[str] = None
    wake_word_enabled: Optional[bool] = None
    verbosity_level: Optional[str] = None
    safety_mode_enabled: Optional[bool] = None
    nutrient_display_preferences: Optional[list[str]] = None
    contribution_consent: Optional[bool] = None
    timezone: Optional[str] = None
    subscription_tier: Optional[str] = None


@router.get("/user/{user_id}/profile")
async def get_profile(user_id: str):
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
        await profile.insert()    
    return profile


@router.patch("/user/{user_id}/profile")
async def update_profile(user_id: str, updates: UpdateProfile = Body(...)):
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    update_data = updates.model_dump(exclude_unset=True)
    if "verbosity_level" in update_data:
        level = update_data["verbosity_level"]
        if level not in {"quick", "standard", "careful"}:
            raise HTTPException(
                status_code=422, detail="verbosity_level must be quick, standard, or careful"
            )
    for key, value in update_data.items():
        setattr(profile, key, value)
    await profile.save()
    return profile


@router.get("/user/{user_id}/dietary-preferences")
async def get_dietary_preferences(user_id: str):
    """Return saved dietary preferences, or an empty default object if unset."""
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        return DietaryPreferences()
    return profile.dietary_preferences


@router.put("/user/{user_id}/dietary-preferences")
async def put_dietary_preferences(user_id: str, prefs: DietaryPreferences = Body(...)):
    """Replace dietary preferences wholesale (full-object PUT, not partial PATCH)."""
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
        await profile.insert()

    prefs.updated_at = datetime.now(timezone.utc)
    profile.dietary_preferences = prefs
    profile.updated_at = datetime.now(timezone.utc)
    await profile.save()
    return profile.dietary_preferences
