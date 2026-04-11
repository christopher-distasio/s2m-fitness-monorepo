from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.models import UserProfile


router = APIRouter()


class UpdateProfile(BaseModel):
    calorie_goal: Optional[float] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    screen_name: Optional[str] = None


@router.get("/user/{user_id}/profile")
async def get_profile(user_id: str):
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
        await profile.insert()    
    return profile


@router.patch("/user/{user_id}/profile")
async def update_profile(user_id: str, updates: UpdateProfile):
    profile = await UserProfile.find_one(UserProfile.user_id == user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)
    await profile.save()
    return profile
