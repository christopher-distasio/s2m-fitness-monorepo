"""Unit tests: PATCH /food allergy block + shared check_allergy_block.

Mocks DB / parse / Qdrant — no live dependencies. Included in default
``make test`` (``not live``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.models import (
    AllergyConstraint,
    DietaryPreferences,
    Tier1Preferences,
)
from backend.routes.food import FoodLogRequest, update_food_log, log_food
from backend.services.allergy_check import (
    check_allergy_block,
    moderate_allergy_warnings,
)


def _prefs(*, allergen: str, severity: str) -> DietaryPreferences:
    return DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={allergen: AllergyConstraint(enabled=True, severity=severity)}
        )
    )


def _parsed_ok(*, food: str = "peanut butter", allergens: list[str] | None = None) -> dict:
    return {
        "food": food,
        "calories": 200,
        "serving_size": "2 tbsp",
        "confidence": "high",
        "macronutrients": {"protein": 8, "carbohydrates": 6, "fats": 16},
        "notes": None,
        "reasoning": None,
        "alternatives": None,
        "allergens": allergens or [],
    }


# ---------------------------------------------------------------------------
# check_allergy_block (shared helper)
# ---------------------------------------------------------------------------


def test_check_allergy_block_severe_match_blocks():
    blocked, reason = check_allergy_block(
        {"allergens": ["peanut"]},
        _prefs(allergen="peanut", severity="severe"),
    )
    assert blocked is True
    assert reason == "Contains peanut (severe)"


def test_check_allergy_block_moderate_match_allows():
    blocked, reason = check_allergy_block(
        {"allergens": ["milk"]},
        _prefs(allergen="milk", severity="moderate"),
    )
    assert blocked is False
    assert reason is None


def test_moderate_allergy_warnings_present_for_moderate():
    warnings = moderate_allergy_warnings(
        {"allergens": ["milk"]},
        _prefs(allergen="milk", severity="moderate"),
    )
    assert warnings == ["Contains milk (moderate)"]


def test_check_allergy_block_preserves_parse_blocked_confidence():
    """Same inputs as the pre-refactor POST gate → same block outcome."""
    blocked, reason = check_allergy_block(
        {
            "confidence": "blocked",
            "reasoning": "I couldn't find any options matching your allergy requirements.",
        },
        None,
    )
    assert blocked is True
    assert "allergy" in reason.lower() or "withheld" in reason.lower() or "couldn't" in reason.lower()


# ---------------------------------------------------------------------------
# PATCH /food/{log_id}
# ---------------------------------------------------------------------------


def _mock_existing_log():
    log = MagicMock()
    log.food_name = "apple"
    log.calories = 95
    log.confidence = "high"
    log.quantity = "1 medium"
    log.id = "507f1f77bcf86cd799439011"
    log.save = AsyncMock()
    return log


@pytest.mark.asyncio
async def test_patch_blocks_severe_allergen_edit():
    """Tier 1: editing into a severe allergen must 403 and not save."""
    existing = _mock_existing_log()
    prefs = _prefs(allergen="peanut", severity="severe")
    parsed = _parsed_ok(food="peanut butter", allergens=["peanut"])

    with (
        patch("backend.routes.food.FoodLog.get", new_callable=AsyncMock) as mock_get,
        patch(
            "backend.routes.food.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.routes.food._load_dietary_preferences",
            new_callable=AsyncMock,
            return_value=prefs,
        ),
        patch("backend.routes.food.Correction") as mock_correction_cls,
    ):
        mock_get.return_value = existing
        mock_correction_cls.return_value = SimpleNamespace(insert=AsyncMock())

        request = FoodLogRequest(user_id="u1", raw_input="peanut butter")
        with pytest.raises(HTTPException) as exc_info:
            await update_food_log(str(existing.id), request)

        assert exc_info.value.status_code == 403
        assert "peanut" in str(exc_info.value.detail).lower()
        existing.save.assert_not_awaited()
        mock_correction_cls.return_value.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_allows_moderate_allergen_with_warning():
    """Tier 2: moderate severity allows the edit and surfaces allergy_warning."""
    existing = _mock_existing_log()
    prefs = _prefs(allergen="milk", severity="moderate")
    parsed = _parsed_ok(food="yogurt", allergens=["milk"])

    correction = SimpleNamespace(insert=AsyncMock())

    with (
        patch("backend.routes.food.FoodLog.get", new_callable=AsyncMock) as mock_get,
        patch(
            "backend.routes.food.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.routes.food._load_dietary_preferences",
            new_callable=AsyncMock,
            return_value=prefs,
        ),
        patch("backend.routes.food.Correction", return_value=correction),
    ):
        mock_get.return_value = existing

        request = FoodLogRequest(user_id="u1", raw_input="yogurt")
        response = await update_food_log(str(existing.id), request)

        assert response["message"] == "Food logged successfully"
        assert "allergy_warning" in response
        assert any("milk" in w for w in response["allergy_warning"])
        existing.save.assert_awaited()
        correction.insert.assert_awaited()


@pytest.mark.asyncio
async def test_patch_blocks_on_parse_confidence_blocked():
    """Lookup refusal (confidence=blocked) uses the same 403 shape as POST."""
    existing = _mock_existing_log()
    parsed = {
        "food": "peanut butter cookies",
        "confidence": "blocked",
        "reasoning": "Blocked by dietary safety filter",
        "calories": None,
        "macronutrients": {},
        "allergens": [],
    }

    with (
        patch("backend.routes.food.FoodLog.get", new_callable=AsyncMock) as mock_get,
        patch(
            "backend.routes.food.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.routes.food._load_dietary_preferences",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_get.return_value = existing
        request = FoodLogRequest(user_id="u1", raw_input="peanut butter cookies")
        with pytest.raises(HTTPException) as exc_info:
            await update_food_log(str(existing.id), request)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Blocked by dietary safety filter"
        existing.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_still_blocks_on_confidence_blocked():
    """POST /food behavior unchanged: confidence=blocked → 403, no insert."""
    parsed = {
        "food": "peanut butter",
        "confidence": "blocked",
        "reasoning": "I couldn't find any options matching your allergy requirements.",
        "calories": None,
        "macronutrients": {},
        "allergens": [],
    }

    with (
        patch(
            "backend.routes.food.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.routes.food._load_dietary_preferences",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.routes.food.FoodLog") as mock_food_log_cls,
    ):
        request = FoodLogRequest(user_id="u1", raw_input="peanut butter")
        with pytest.raises(HTTPException) as exc_info:
            await log_food(request)

        assert exc_info.value.status_code == 403
        mock_food_log_cls.assert_not_called()
