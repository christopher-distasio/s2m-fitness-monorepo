"""Shared demo account leftover allergen prefs must not look like an empty profile.

The guest/demo user is one Mongo document. Saving egg/milk on it made banana/apple
lookups withhold results even when the UI later looked empty. These tests lock the
filter + zero-hit behavior so a walkthrough isn't the only coverage.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.models import AllergyConstraint, DietaryPreferences, Tier1Preferences
from backend.services.dietary_filters import (
    build_tier_1_filter,
    has_active_allergen_constraint,
    wants_lactose_avoidance,
)
from backend.services.nutrition_service import lookup_food

pytestmark = pytest.mark.unit


def _leftover_demo_prefs() -> DietaryPreferences:
    """Shape stored on the guest user when banana/apple started failing."""
    return DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={
                "milk": AllergyConstraint(enabled=True, severity="moderate"),
                "egg": AllergyConstraint(enabled=True, severity="severe"),
                "fish": AllergyConstraint(),
                "shellfish": AllergyConstraint(),
                "tree_nut": AllergyConstraint(),
                "peanut": AllergyConstraint(),
                "wheat": AllergyConstraint(),
                "soy": AllergyConstraint(),
                "sesame": AllergyConstraint(),
            },
            lactose_free=False,
        )
    )


def _filter_keys(filt) -> set[str]:
    keys: set[str] = set()
    if filt is None:
        return keys
    for cond in list(filt.must or []) + list(filt.must_not or []):
        if getattr(cond, "key", None):
            keys.add(cond.key)
        for inner in getattr(cond, "should", None) or []:
            if getattr(inner, "key", None):
                keys.add(inner.key)
    return keys


def test_empty_profile_builds_no_allergen_filter():
    assert build_tier_1_filter(None) is None
    empty = DietaryPreferences().tier_1
    assert build_tier_1_filter(empty) is None
    assert has_active_allergen_constraint(empty) is False
    assert wants_lactose_avoidance("banana", empty) is False


def test_leftover_demo_egg_milk_filter_is_restrictive_not_lactose():
    prefs = _leftover_demo_prefs()
    filt = build_tier_1_filter(prefs.tier_1)
    assert filt is not None
    assert has_active_allergen_constraint(prefs.tier_1) is True
    assert wants_lactose_avoidance("banana", prefs.tier_1) is False

    keys = _filter_keys(filt)
    assert keys == {"egg", "egg_may_contain", "milk"}
    assert "lactose_free" not in keys
    assert "dairy_free" not in keys

    must_keys = {c.key for c in (filt.must or []) if getattr(c, "key", None)}
    must_not_keys = {c.key for c in (filt.must_not or []) if getattr(c, "key", None)}
    assert must_keys == {"egg"}
    assert filt.must[0].match.value == "FREE"
    assert must_not_keys == {"milk", "egg_may_contain"}


@pytest.mark.asyncio
async def test_zero_generic_hits_with_leftover_allergens_withhold():
    with patch(
        "backend.services.nutrition_service._retrieve_best",
        new_callable=AsyncMock,
        return_value=([], "banana"),
    ) as retrieve:
        result = await lookup_food(
            "banana",
            source_filter="generic",
            dietary_preferences=_leftover_demo_prefs(),
        )

    assert result is not None
    assert result["blocked_by_allergy"] is True
    assert "allergy requirements" in result["message"]

    combined = retrieve.await_args.args[1]
    keys = _filter_keys(combined)
    assert "egg" in keys
    assert "milk" in keys
    assert combined.must[0].key == "source"


@pytest.mark.asyncio
async def test_zero_generic_hits_with_empty_prefs_are_not_an_allergy_block():
    with patch(
        "backend.services.nutrition_service._retrieve_best",
        new_callable=AsyncMock,
        return_value=([], "banana"),
    ) as retrieve:
        result = await lookup_food(
            "banana",
            source_filter="generic",
            dietary_preferences=DietaryPreferences(),
        )

    assert result is None or not result.get("blocked_by_allergy")
    combined = retrieve.await_args.args[1]
    assert _filter_keys(combined) == {"source"}
    assert combined.must_not in (None, [])
