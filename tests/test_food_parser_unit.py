import json
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.food_parser import parse_food_input

def make_history(food: str) -> list:
    """Helper — builds a minimal conversation history with a previous food parse."""
    assistant_content = json.dumps({"food": food, "serving_size": "unknown", "confidence": "medium"})
    return [
        {"role": "user", "content": f"some {food}"},
        {"role": "assistant", "content": assistant_content},
    ]


@pytest.mark.asyncio
async def test_clarification_prepends_food_from_history():
    """Given history containing pasta, 'a large bowl' should become 'a large bowl of pasta'."""
    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "pasta",
            "serving_size": "a large bowl",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    with patch("backend.services.food_parser.client.chat.completions.create", side_effect=fake_create):
        with patch("backend.services.food_parser.lookup_food", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {"calories": 300, "carbs": 60, "protein": 10, "fat": 2}

            from backend.services.food_parser import parse_food_input
            await parse_food_input("a large bowl", conversation_history=make_history("pasta"))

    last_user_message = captured["messages"][-1]["content"]
    assert "pasta" in last_user_message, f"Expected 'pasta' in input, got: {last_user_message}"
    assert "a large bowl" in last_user_message


@pytest.mark.asyncio
async def test_no_history_passes_raw_input_unchanged():
    """Without history, the raw input should go to GPT unmodified."""
    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "scrambled eggs",
            "serving_size": "2 eggs",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    with patch("backend.services.food_parser.client.chat.completions.create", side_effect=fake_create):
        with patch("backend.services.food_parser.lookup_food", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {"calories": 180, "carbs": 2, "protein": 12, "fat": 14}

            from backend.services.food_parser import parse_food_input
            await parse_food_input("two scrambled eggs", conversation_history=[])

    last_user_message = captured["messages"][-1]["content"]
    assert last_user_message == "two scrambled eggs"


@pytest.mark.asyncio
async def test_never_returns_unparseable_when_history_present():
    """Even if GPT returns unparseable, with history present we should not get that error."""
    async def fake_create(**kwargs):
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "pasta",
            "serving_size": "a small bowl",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    with patch("backend.services.food_parser.client.chat.completions.create", side_effect=fake_create):
        with patch("backend.services.food_parser.lookup_food", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {"calories": 200, "carbs": 40, "protein": 7, "fat": 1}

            from backend.services.food_parser import parse_food_input
            result = await parse_food_input("a small bowl", conversation_history=make_history("pasta"))

    assert "error" not in result


@pytest.mark.asyncio
async def test_high_confidence_returns_correct_shape():
    """A clear specific input should return high confidence with correct fields."""
    async def fake_create(**kwargs):
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "banana",
            "serving_size": "1 medium",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    with patch("backend.services.food_parser.client.chat.completions.create", side_effect=fake_create):
        with patch("backend.services.food_parser.lookup_food", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {"calories": 89, "carbs": 23, "protein": 1, "fat": 0}

            from backend.services.food_parser import parse_food_input
            result = await parse_food_input("one banana", conversation_history=[])

    assert result["confidence"] == "high"
    assert result["food"] == "banana"
    assert result["calories"] == 89
    assert "macronutrients" in result


@pytest.mark.asyncio
async def test_parse_stuff_low_confidence():
    result = await parse_food_input("stuff")
    assert result.get("confidence") == "low" or "error" in result


@pytest.mark.asyncio
async def test_medium_confidence_alternatives_are_nonempty_strings():
    result = await parse_food_input("some pasta")
    alternatives = result.get("alternatives") or []
    assert len(alternatives) > 0
    assert all(isinstance(a, str) and len(a) > 0 for a in alternatives)


@pytest.mark.asyncio
async def test_low_confidence_unknown_food_has_empty_alternatives():
    result = await parse_food_input("asdfgh")
    alternatives = result.get("alternatives") or []
    assert alternatives == []