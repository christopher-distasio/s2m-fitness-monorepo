"""Look up the current user's logs. Always keyed by explicit subject user_id."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.models import FoodLog, UserProfile


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def latest_log_for_user(
    user_id: str,
    *,
    recency: timedelta | None = None,
) -> FoodLog | None:
    """Most recent FoodLog for this user only — never 'latest across all users'."""
    last = (
        await FoodLog.find(FoodLog.user_id == user_id)
        .sort(-FoodLog.logged_at)
        .first_or_none()
    )
    if last is None:
        return None
    if recency is not None:
        now = datetime.now(timezone.utc)
        if now - _as_aware(last.logged_at) > recency:
            return None
    return last


async def load_user_profile(user_id: str):
    return await UserProfile.find_one(UserProfile.user_id == user_id)
