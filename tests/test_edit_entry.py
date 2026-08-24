"""edit_entry: bounded search, in-place correction, Spec 2 contrastive list."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.models import AllergyConstraint, DietaryPreferences, Tier1Preferences
from backend.services.clarification import clarification_state
from backend.services.correct_last import (
    CORRECT_LAST_RECENCY,
    NOTHING_TO_CORRECT_MESSAGE,
    handle_correct_last,
)
from backend.services.edit_entry import (
    EDIT_ENTRY_SEARCH_WINDOW,
    NO_MATCH_MESSAGE,
    handle_edit_entry,
    match_logs,
    parse_edit_reference,
    pending_edit_entry,
)
from backend.services.utterance_pipeline import dispatch_voice_utterance


def _prefs(*, allergen: str, severity: str) -> DietaryPreferences:
    return DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={allergen: AllergyConstraint(enabled=True, severity=severity)}
        )
    )


def _log(
    *,
    food: str,
    logged_at: datetime,
    user_id: str = "u1",
    log_id: str = "507f1f77bcf86cd799439011",
    food_event: dict | None = None,
):
    log = MagicMock()
    log.id = log_id
    log.user_id = user_id
    log.food_name = food
    log.calories = 150
    log.confidence = "high"
    log.quantity = "1"
    log.raw_input = food
    log.logged_at = logged_at
    log.food_event = food_event or {"food": food}
    log.save = AsyncMock()
    return log


def _parsed(food: str, **extra) -> dict:
    payload = {
        "food": food,
        "calories": 200,
        "serving_size": "2",
        "confidence": "high",
        "macronutrients": {"protein": 12, "carbohydrates": 1, "fats": 10},
        "allergens": extra.get("allergens", []),
        "allergen_state": extra.get("allergen_state", {}),
        "resolution_status": "resolved",
        "food_event": {
            "food": food,
            "brand": extra.get("brand"),
            "preparation": extra.get("preparation"),
            "allergen_state": extra.get("allergen_state", {}),
        },
    }
    payload.update({k: v for k, v in extra.items() if k not in payload})
    return payload


def test_parse_edit_reference_splits_correction_and_time():
    ref = parse_edit_reference(
        "the eggs I had this morning, that was actually two eggs"
    )
    assert ref.relative_days == 0
    assert ref.meal_label == "morning"
    assert "eggs" in ref.food_terms
    assert ref.correction_text
    assert "two eggs" in ref.correction_text.lower()


def test_match_logs_scopes_to_user_window_and_terms():
    tz = ZoneInfo("UTC")
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    eggs = _log(food="eggs", logged_at=datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc))
    toast = _log(
        food="toast",
        logged_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
        log_id="507f1f77bcf86cd799439012",
    )
    old = _log(
        food="eggs",
        logged_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
        log_id="507f1f77bcf86cd799439013",
    )
    ref = parse_edit_reference("the eggs I had this morning")
    matches = match_logs([eggs, toast, old], ref, now=now, tz=tz)
    assert [m.food_name for m in matches] == ["eggs"]


@pytest.mark.asyncio
async def test_edit_entry_unambiguous_match_updates_in_place():
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    existing = _log(food="eggs", logged_at=datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc))
    parsed = _parsed("eggs", serving_size="2")
    correction = SimpleNamespace(insert=AsyncMock())
    profile = SimpleNamespace(timezone="UTC", dietary_preferences=None)

    with (
        patch(
            "backend.services.edit_entry.load_user_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "backend.services.edit_entry.logs_for_user_since",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "backend.services.edit_entry.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.services.edit_entry.check_allergy_block",
            return_value=(False, None),
        ),
        patch(
            "backend.services.edit_entry.apply_food_event_correction",
            new_callable=AsyncMock,
            return_value=correction,
        ) as mock_apply,
        patch("backend.models.FoodLog.insert", new_callable=AsyncMock) as mock_insert,
    ):
        result = await handle_edit_entry(
            "u1",
            "the eggs I had this morning, that was actually two eggs",
            now=now,
        )

    assert result["corrected"] is True
    assert result["logged"] is False
    mock_apply.assert_awaited_once()
    mock_insert.assert_not_called()
    # Search window is 7 days, not unbounded.
    since = mock_apply.call_args
    assert since  # applied to the existing log
    assert mock_apply.await_args.args[0] is existing


@pytest.mark.asyncio
async def test_edit_entry_zero_matches_speaks_miss_and_does_not_insert():
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    profile = SimpleNamespace(timezone="UTC", dietary_preferences=None)
    with (
        patch(
            "backend.services.edit_entry.load_user_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "backend.services.edit_entry.logs_for_user_since",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_logs,
        patch(
            "backend.services.edit_entry.parse_food_input",
            new_callable=AsyncMock,
        ) as mock_parse,
        patch("backend.models.FoodLog.insert", new_callable=AsyncMock) as mock_insert,
        patch(
            "backend.services.edit_entry.apply_food_event_correction",
            new_callable=AsyncMock,
        ) as mock_apply,
    ):
        result = await handle_edit_entry(
            "u1", "the pizza I logged this morning", now=now
        )

    assert result["corrected"] is False
    assert result["logged"] is False
    assert result["message"] == NO_MATCH_MESSAGE
    mock_parse.assert_not_awaited()
    mock_insert.assert_not_called()
    mock_apply.assert_not_called()
    since_arg = mock_logs.await_args.args[1]
    assert now - since_arg == EDIT_ENTRY_SEARCH_WINDOW


@pytest.mark.asyncio
async def test_edit_entry_multiple_matches_asks_once_then_resolves():
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    eggs = _log(food="eggs", logged_at=datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc))
    toast = _log(
        food="toast",
        logged_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
        log_id="507f1f77bcf86cd799439012",
    )
    profile = SimpleNamespace(timezone="UTC", dietary_preferences=None)
    parsed = _parsed("oatmeal")

    with (
        patch(
            "backend.services.edit_entry.load_user_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "backend.services.edit_entry.logs_for_user_since",
            new_callable=AsyncMock,
            return_value=[eggs, toast],
        ),
        patch(
            "backend.services.edit_entry.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.services.edit_entry.check_allergy_block",
            return_value=(False, None),
        ),
        patch(
            "backend.services.edit_entry.apply_food_event_correction",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(insert=AsyncMock()),
        ) as mock_apply,
        patch(
            "backend.services.edit_entry.FoodLog.get",
            new_callable=AsyncMock,
            return_value=eggs,
        ),
    ):
        first = await handle_edit_entry(
            "u1",
            "change this morning's log, that was actually oatmeal",
            now=now,
        )
        assert first["needs_clarification"] is True
        assert first["confirmation"]["question_kind"] == "contrastive"
        question = first["message"]
        assert question.count("?") == 1
        assert " or " in question.lower()
        spoken = first["confirmation"]["spoken_candidates"]
        assert 2 <= len(spoken) <= 3

        history = [
            {
                "role": "user",
                "content": "change this morning's log, that was actually oatmeal",
            },
            {"role": "assistant", "content": json.dumps(first)},
        ]
        assert pending_edit_entry(history)
        assert clarification_state(history) == "edit_entry"

        second = await handle_edit_entry("u1", "the first one", history=history, now=now)

    assert second["corrected"] is True
    mock_apply.assert_awaited_once()
    assert mock_apply.await_args.args[0] is eggs


@pytest.mark.asyncio
async def test_edit_entry_identity_change_reports_restriction_factually():
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    existing = _log(
        food="oatmeal",
        logged_at=datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc),
        food_event={"food": "oatmeal", "allergen_state": {}},
    )
    parsed = _parsed(
        "peanut butter",
        allergens=["peanut"],
        allergen_state={"peanut": "contains"},
    )
    prefs = _prefs(allergen="peanut", severity="moderate")
    profile = SimpleNamespace(timezone="UTC", dietary_preferences=prefs)

    with (
        patch(
            "backend.services.edit_entry.load_user_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "backend.services.edit_entry.logs_for_user_since",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "backend.services.edit_entry.parse_food_input",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.services.edit_entry.check_allergy_block",
            return_value=(False, None),
        ),
        patch(
            "backend.services.edit_entry.apply_food_event_correction",
            new_callable=AsyncMock,
            side_effect=lambda log, changes, uid, **kw: setattr(
                log, "food_event", changes.get("food_event")
            )
            or setattr(log, "food_name", changes.get("food")),
        ),
    ):
        result = await handle_edit_entry(
            "u1",
            "the oatmeal this morning, that was actually peanut butter",
            now=now,
        )

    assert result["corrected"] is True
    text = result["message"].lower()
    assert "peanut" in text
    assert "ingredient" in text or "contains" in text
    assert "safe" not in text
    assert "unsafe" not in text


@pytest.mark.asyncio
async def test_edit_entry_does_not_search_other_users():
    now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    profile = SimpleNamespace(timezone="UTC", dietary_preferences=None)
    with (
        patch(
            "backend.services.edit_entry.load_user_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "backend.services.edit_entry.logs_for_user_since",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_logs,
    ):
        await handle_edit_entry("u1", "change yesterday's coffee", now=now)

    mock_logs.assert_awaited_once()
    assert mock_logs.await_args.args[0] == "u1"


@pytest.mark.asyncio
async def test_correct_last_still_uses_24h_window_after_refactor():
    """Existing correct_last contract is unchanged by the shared helper."""
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
async def test_voice_edit_entry_intent_does_not_fall_through_to_log():
    payload = {
        "message": "Updated your eggs.",
        "transcription": "the eggs this morning were actually two",
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
            return_value={"intent": "edit_entry", "text": "the eggs this morning were actually two"},
        ),
        patch(
            "backend.services.utterance_pipeline.handle_edit_entry",
            new_callable=AsyncMock,
            return_value=payload,
        ) as mock_handler,
        patch(
            "backend.services.food_parser.parse_food_input",
            new_callable=AsyncMock,
        ) as mock_parse,
    ):
        result = await dispatch_voice_utterance(
            "the eggs this morning were actually two", "u1"
        )

    assert result.kind == "edit_entry"
    assert result.kind != "log"
    mock_handler.assert_awaited_once()
    mock_parse.assert_not_called()
    assert "handler" in result.stages
