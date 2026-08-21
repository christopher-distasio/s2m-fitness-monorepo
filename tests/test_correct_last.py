"""correct_last updates the prior log in place — never a phantom insert."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.correct_last import (
    CORRECT_LAST_RECENCY,
    NOTHING_TO_CORRECT_MESSAGE,
    handle_correct_last,
)
from backend.services.utterance_pipeline import dispatch_voice_utterance


def _log(*, food="whole milk", user_id="u1", age=timedelta(minutes=5)):
    log = MagicMock()
    log.id = "507f1f77bcf86cd799439011"
    log.user_id = user_id
    log.food_name = food
    log.calories = 150
    log.confidence = "high"
    log.quantity = "1 cup"
    log.logged_at = datetime.now(timezone.utc) - age
    log.food_event = {"food": food}
    log.save = AsyncMock()
    log.delete = AsyncMock()
    return log


def _parsed_oat():
    return {
        "food": "oat milk",
        "calories": 120,
        "serving_size": "1 cup",
        "confidence": "high",
        "macronutrients": {"protein": 3, "carbohydrates": 16, "fats": 5},
        "notes": None,
        "reasoning": None,
        "alternatives": None,
        "allergens": [],
        "resolution_status": "resolved",
    }


@pytest.mark.asyncio
async def test_correct_last_updates_existing_log_count_stays_one():
    existing = _log()
    parsed = _parsed_oat()
    correction = SimpleNamespace(insert=AsyncMock())

    with (
        patch(
            "backend.services.correct_last.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=existing,
        ),
        patch(
            "backend.services.correct_last.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.services.correct_last._load_dietary_preferences",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.services.correct_last.Correction", return_value=correction),
        patch("backend.models.FoodLog.insert", new_callable=AsyncMock) as mock_insert,
    ):
        result = await handle_correct_last("u1", "actually it was oat milk")

    assert result["corrected"] is True
    assert result["logged"] is False
    assert existing.food_name == "oat milk"
    existing.save.assert_awaited()
    correction.insert.assert_awaited()
    mock_insert.assert_not_called()
    assert "oat milk" in result["message"].lower()


@pytest.mark.asyncio
async def test_correct_last_with_no_prior_log_does_not_create_one():
    with (
        patch(
            "backend.services.correct_last.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.services.correct_last.parse_food_input",
            new_callable=AsyncMock,
        ) as mock_parse,
        patch("backend.models.FoodLog.insert", new_callable=AsyncMock) as mock_insert,
    ):
        result = await handle_correct_last("u1", "actually it was oat milk")

    assert result["corrected"] is False
    assert result["logged"] is False
    assert result["message"] == NOTHING_TO_CORRECT_MESSAGE
    mock_parse.assert_not_awaited()
    mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_correct_last_outside_recency_window_is_nothing_to_correct():
    """latest_log_for_user is called with the recency window — stale logs don't count."""
    with (
        patch(
            "backend.services.correct_last.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_latest,
        patch(
            "backend.services.correct_last.parse_food_input",
            new_callable=AsyncMock,
        ) as mock_parse,
    ):
        result = await handle_correct_last("u1", "actually it was oat milk")

    mock_latest.assert_awaited_once()
    assert mock_latest.await_args.kwargs["recency"] == CORRECT_LAST_RECENCY
    assert result["message"] == NOTHING_TO_CORRECT_MESSAGE
    mock_parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_correct_last_intent_does_not_fall_through_to_log():
    """Classification of correct_last must not continue into parse/insert."""
    handler_payload = {
        "message": "Updated your last entry to oat milk.",
        "transcription": "actually it was oat milk",
        "logged": False,
        "corrected": True,
        "id": "507f1f77bcf86cd799439011",
    }
    with (
        patch(
            "backend.services.utterance_pipeline.run_safety_and_domain",
            new_callable=AsyncMock,
            return_value=MagicMock(response=None, stages=["safety", "domain_boundary"]),
        ),
        patch(
            "backend.services.utterance_pipeline.classify_intent",
            new_callable=AsyncMock,
            return_value={"intent": "correct_last", "text": "actually it was oat milk"},
        ),
        patch(
            "backend.services.utterance_pipeline.handle_correct_last",
            new_callable=AsyncMock,
            return_value=handler_payload,
        ) as mock_handler,
        patch(
            "backend.services.food_parser.parse_food_input",
            new_callable=AsyncMock,
        ) as mock_parse,
    ):
        result = await dispatch_voice_utterance("actually it was oat milk", "u1")

    assert result.kind == "correct_last"
    assert result.kind != "log"
    assert result.response == handler_payload
    mock_handler.assert_awaited_once_with(
        "u1", "actually it was oat milk", history=None, asr=None
    )
    mock_parse.assert_not_called()
    assert "intent" in result.stages
    assert "handler" in result.stages
