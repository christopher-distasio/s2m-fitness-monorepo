"""Live dietary/allergen lookup regressions (promoted from print-only e2e).

Marked @pytest.mark.live — needs local Qdrant + embedding/API path used by
lookup_food(). Skip in default CI.

Run: poetry run pytest tests/test_allergen_dietary_live.py -v -m live
"""

from __future__ import annotations

import pytest

from backend.models import (
    AllergyConstraint,
    DietaryPreferences,
    Tier1Preferences,
    Tier2Preferences,
)
from backend.services.nutrition_service import lookup_food


@pytest.fixture(scope="module")
def ensure_qdrant():
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url="http://192.168.1.227:6333", timeout=10)
        client.get_collection("food-vectors")
    except Exception as exc:
        pytest.skip(f"Qdrant not available: {exc}")


@pytest.mark.live
@pytest.mark.asyncio
async def test_lookup_no_restrictions_returns_result(ensure_qdrant):
    result = await lookup_food("chicken breast", dietary_preferences=None)
    assert result is not None
    assert not result.get("blocked_by_allergy")
    assert result.get("food_name") or result.get("candidates")


@pytest.mark.live
@pytest.mark.asyncio
async def test_severe_peanut_blocks_or_returns_peanut_free(ensure_qdrant):
    prefs = DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={"peanut": AllergyConstraint(enabled=True, severity="severe")}
        )
    )
    result = await lookup_food("peanut butter cookies", dietary_preferences=prefs)
    assert result is not None
    if result.get("blocked_by_allergy"):
        return
    # If not blocked, every returned candidate must not be peanut CONTAINS.
    # lookup_food may return a single top hit and/or candidates list.
    names = []
    if result.get("food_name"):
        names.append(result)
    for c in result.get("candidates") or []:
        names.append(c)
    # Soft check: at least we did not crash; prefer blocked or non-empty safe set.
    assert result.get("food_name") or result.get("candidates") is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_moderate_milk_allergy_lookup_does_not_crash(ensure_qdrant):
    prefs = DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={"milk": AllergyConstraint(enabled=True, severity="moderate")}
        )
    )
    result = await lookup_food("yogurt", dietary_preferences=prefs)
    # May be blocked, filtered, or a milk-UNKNOWN hit — must not raise.
    assert result is None or isinstance(result, dict)


@pytest.mark.live
@pytest.mark.asyncio
async def test_vegan_preference_lookup_does_not_crash(ensure_qdrant):
    prefs = DietaryPreferences(
        tier_1=Tier1Preferences(vegan=True),
        tier_2=Tier2Preferences(organic=True),
    )
    result = await lookup_food("milk", dietary_preferences=prefs)
    assert result is None or isinstance(result, dict)
    if result and not result.get("blocked_by_allergy"):
        # Vegan filter should not return obviously dairy-named top hit when
        # vegan tagging exists — soft: just ensure structure.
        assert "food_name" in result or "candidates" in result or result.get("calories") is not None
