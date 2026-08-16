"""Unit tests for serving_size quantity scaling.

Guards the silent 1.0 fallback: GPT used to return serving_size like
'2 bananas', float() failed, and logs stored 1x nutrition.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.food_parser import (
    SYSTEM_PROMPT,
    parse_food_input,
    parse_quantity_multiplier,
)

pytestmark = pytest.mark.unit

BANANA_NUTRITION = {
    "calories": 89,
    "carbs": 23.0,
    "protein": 1.1,
    "fat": 0.3,
    "nutrients": {"fiber": 2.6, "potassium": 358.0},
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}

EGG_NUTRITION = {
    "calories": 72,
    "carbs": 0.4,
    "protein": 6.3,
    "fat": 4.8,
    "nutrients": {"cholesterol": 186.0},
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}

YOGURT_NUTRITION = {
    "calories": 100,
    "carbs": 12.0,
    "protein": 17.0,
    "fat": 0.0,
    "nutrients": {"calcium": 150.0},
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}

RICE_NUTRITION = {
    "calories": 205,
    "carbs": 45.0,
    "protein": 4.3,
    "fat": 0.4,
    "nutrients": {"fiber": 0.6},
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}


def _gpt_payload(food: str, serving_size: str, confidence: str = "high") -> str:
    return json.dumps(
        {
            "food": food,
            "brand": "",
            "serving_size": serving_size,
            "confidence": confidence,
            "notes": "",
            "reasoning": "",
            "alternatives": [],
        }
    )


def _fake_gpt(payload: str):
    async def fake_create(**kwargs):
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = payload
        return mock_response

    return fake_create


async def _parse(raw_input: str, serving_size: str, food: str, nutrition: dict):
    with patch(
        "backend.services.food_parser.client.chat.completions.create",
        side_effect=_fake_gpt(_gpt_payload(food, serving_size)),
    ):
        with patch(
            "backend.services.food_parser.lookup_food",
            new_callable=AsyncMock,
        ) as mock_lookup:
            mock_lookup.return_value = dict(nutrition)
            return await parse_food_input(raw_input, conversation_history=[])


def _assert_scaled(result: dict, base: dict, quantity: float):
    assert result["quantity_used"] == quantity
    assert result["calories"] == int(round(base["calories"] * quantity))
    macros = result["macronutrients"]
    assert macros["protein"] == round(base["protein"] * quantity, 1)
    assert macros["carbohydrates"] == round(base["carbs"] * quantity, 1)
    assert macros["fats"] == round(base["fat"] * quantity, 1)
    for key, value in (base.get("nutrients") or {}).items():
        assert result["nutrients"][key] == round(float(value) * quantity, 2)


# --- parse_quantity_multiplier (pure) ---


def test_bare_number():
    assert parse_quantity_multiplier("2") == 2.0
    assert parse_quantity_multiplier("1") == 1.0
    assert parse_quantity_multiplier("3.5") == 3.5


def test_old_bug_food_name_in_serving_size():
    """Regression: '2 bananas' used to ValueError and silently become 1.0."""
    assert parse_quantity_multiplier("2 bananas") == 2.0
    assert parse_quantity_multiplier("2 eggs") == 2.0


def test_word_numbers_and_dozen():
    assert parse_quantity_multiplier("two") == 2.0
    assert parse_quantity_multiplier("two yogurts") == 2.0
    assert parse_quantity_multiplier("three") == 3.0
    assert parse_quantity_multiplier("dozen") == 12.0
    assert parse_quantity_multiplier("a dozen") == 12.0
    assert parse_quantity_multiplier("a dozen eggs") == 12.0


def test_measured_quantity_uses_leading_number():
    assert parse_quantity_multiplier("2 cups") == 2.0
    assert parse_quantity_multiplier("1 cup") == 1.0
    assert parse_quantity_multiplier("1 medium") == 1.0


def test_unparseable_serving_defaults_to_one(caplog):
    with caplog.at_level("WARNING"):
        assert parse_quantity_multiplier("unknown") == 1.0
    assert any("defaulting multiplier to 1.0" in rec.message for rec in caplog.records)


# --- prompt consistency ---


def test_prompt_serving_size_examples_never_include_food_name():
    shape_block = SYSTEM_PROMPT.split("Return this exact shape:")[1].split("Rules:")[0]
    assert "'2 eggs'" not in shape_block
    assert "quantity only" in shape_block
    assert "never include the food name" in shape_block
    assert "'1 cup'" in shape_block
    assert "'2'" in shape_block
    assert "Wrong: '2 bananas', '2 eggs'" in SYSTEM_PROMPT
    assert "Right: '2'" in SYSTEM_PROMPT
    assert "Wrong: '2 cups of rice'" in SYSTEM_PROMPT


# --- parse_food_input scaling ---


@pytest.mark.asyncio
async def test_two_bananas_scales_2x_even_when_gpt_includes_food_name():
    """Tier 1: the old GPT shape still must 2x calories/macros/nutrients."""
    result = await _parse("2 bananas", "2 bananas", "banana", BANANA_NUTRITION)
    _assert_scaled(result, BANANA_NUTRITION, 2.0)


@pytest.mark.asyncio
async def test_two_bananas_clean_serving_size():
    result = await _parse("2 bananas", "2", "banana", BANANA_NUTRITION)
    _assert_scaled(result, BANANA_NUTRITION, 2.0)


@pytest.mark.asyncio
async def test_one_banana_no_regression():
    result = await _parse("1 banana", "1", "banana", BANANA_NUTRITION)
    assert result["quantity_used"] == 1.0
    assert result["calories"] == 89
    assert result["macronutrients"]["protein"] == 1.1
    assert result["nutrients"]["fiber"] == 2.6


@pytest.mark.asyncio
async def test_three_eggs():
    result = await _parse("3 eggs", "3", "egg", EGG_NUTRITION)
    _assert_scaled(result, EGG_NUTRITION, 3.0)


@pytest.mark.asyncio
async def test_two_yogurts_word_number_serving_size():
    result = await _parse("two yogurts", "two", "yogurt", YOGURT_NUTRITION)
    _assert_scaled(result, YOGURT_NUTRITION, 2.0)


@pytest.mark.asyncio
async def test_a_dozen_eggs():
    result = await _parse("a dozen eggs", "a dozen", "egg", EGG_NUTRITION)
    _assert_scaled(result, EGG_NUTRITION, 12.0)


@pytest.mark.asyncio
async def test_two_cups_of_rice_measured_quantity():
    result = await _parse("2 cups of rice", "2 cups", "rice", RICE_NUTRITION)
    _assert_scaled(result, RICE_NUTRITION, 2.0)


@pytest.mark.asyncio
async def test_text_and_voice_transcripts_share_parse_path():
    """Tier 4: typed text and a Whisper transcript both hit parse_food_input."""
    typed = await _parse("2 bananas", "2 bananas", "banana", BANANA_NUTRITION)

    whisper_transcript = "2 bananas"
    voiced = await _parse(
        whisper_transcript, "2 bananas", "banana", BANANA_NUTRITION
    )

    assert typed["calories"] == voiced["calories"] == 178
    assert typed["quantity_used"] == voiced["quantity_used"] == 2.0
