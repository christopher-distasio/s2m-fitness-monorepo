"""Unit tests for serving_size quantity scaling.

Guards the silent 1.0 fallback: GPT used to return serving_size like
'2 bananas', float() failed, and logs stored 1x nutrition.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.food_parser import (
    SYSTEM_PROMPT,
    grams_per_tablespoon,
    leading_fraction,
    parse_food_input,
    parse_quantity_multiplier,
    stated_fluid_grams,
    stated_volume_unit,
    stated_weight_grams,
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
async def test_half_a_banana_scales_down():
    """Regression: quantities below 1 were skipped, so 'half a banana' logged a whole one."""
    result = await _parse("half a banana", "0.5", "banana", BANANA_NUTRITION)
    _assert_scaled(result, BANANA_NUTRITION, 0.5)


@pytest.mark.asyncio
async def test_half_word_serving_size_scales_down():
    result = await _parse("half a bagel", "half", "bagel", BANANA_NUTRITION)
    _assert_scaled(result, BANANA_NUTRITION, 0.5)


@pytest.mark.asyncio
async def test_two_cups_of_rice_measured_quantity():
    result = await _parse("2 cups of rice", "2 cups", "rice", RICE_NUTRITION)
    _assert_scaled(result, RICE_NUTRITION, 2.0)


# --- fractions written in serving_size text ---


def test_leading_fraction_forms():
    assert leading_fraction("1/4 cup") == 0.25
    assert leading_fraction("1 1/2 cups") == 1.5
    assert leading_fraction("½ cup") == 0.5
    assert leading_fraction("3/4") == 0.75
    assert leading_fraction("2 cups") is None
    assert leading_fraction("1/0 cup") is None


def test_parse_quantity_multiplier_reads_fractions():
    assert parse_quantity_multiplier("1/4 cup") == 0.25
    assert parse_quantity_multiplier("1 1/2 cups") == 1.5


@pytest.mark.asyncio
async def test_fraction_text_beats_gpt_amount_field():
    """Regression: GPT wrote serving_size '1/4 cup' with amount 1.0, logging a whole serving."""
    payload = json.loads(_gpt_payload("almonds", "1/4 cup"))
    payload["amount"] = 1.0
    with patch(
        "backend.services.food_parser.client.chat.completions.create",
        side_effect=_fake_gpt(json.dumps(payload)),
    ):
        with patch(
            "backend.services.food_parser.lookup_food", new_callable=AsyncMock
        ) as mock_lookup:
            mock_lookup.return_value = dict(BANANA_NUTRITION)
            result = await parse_food_input("a quarter cup of almonds", conversation_history=[])
    _assert_scaled(result, BANANA_NUTRITION, 0.25)


# --- stated weights convert to grams ---

CHICKEN_NUTRITION = {
    "calories": 140,
    "carbs": 0.0,
    "protein": 26.0,
    "fat": 3.0,
    "nutrients": {"sodium": 60.0},
    "serving_size_g": 85.0,
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}


def test_stated_weight_grams_units():
    assert stated_weight_grams("100 grams", "grams", 100.0) == 100.0
    assert stated_weight_grams("100 g", "", 100.0) == 100.0
    assert stated_weight_grams("8 oz", "oz", 8.0) == pytest.approx(226.796)
    assert stated_weight_grams("1 lb", "", 1.0) == pytest.approx(453.592)
    assert stated_weight_grams("0.5 kg", "", 0.5) == 500.0


def test_stated_weight_grams_trusts_text_over_unit_field():
    assert stated_weight_grams("100 grams", "serving", 100.0) == 100.0


def test_stated_weight_grams_ignores_counts_and_volumes():
    assert stated_weight_grams("2", "count", 2.0) is None
    assert stated_weight_grams("2 cups", "cup", 2.0) is None
    assert stated_weight_grams("1 medium", "", 1.0) is None
    assert stated_weight_grams("a dozen", "", 12.0) is None


@pytest.mark.asyncio
async def test_100_grams_scales_by_serving_grams():
    """Regression: '100 grams of chicken breast' logged 100 x the default serving."""
    result = await _parse(
        "100 grams of chicken breast", "100 grams", "chicken breast", CHICKEN_NUTRITION
    )
    _assert_scaled(result, CHICKEN_NUTRITION, 100.0 / 85.0)
    assert result["amount"] == 100.0


@pytest.mark.asyncio
async def test_8_oz_by_weight_scales_by_serving_grams():
    result = await _parse("8 oz of steak", "8 oz", "steak", CHICKEN_NUTRITION)
    _assert_scaled(result, CHICKEN_NUTRITION, 8 * 28.3495 / 85.0)
    assert result["amount"] == 8.0


@pytest.mark.asyncio
async def test_weight_without_serving_grams_keeps_count_scaling():
    """No serving_size_g to convert against: fall back to the leading number."""
    result = await _parse("100 grams of banana", "100 grams", "banana", BANANA_NUTRITION)
    _assert_scaled(result, BANANA_NUTRITION, 100.0)


# --- drinks are fluid ounces ---

MILK_NUTRITION = {
    "calories": 149,
    "carbs": 12.0,
    "protein": 8.0,
    "fat": 8.0,
    "nutrients": {"calcium": 276.0},
    "serving_size_g": 244.0,
    "candidates": [],
    "portion_options": [],
    "resolution": {"status": "ok"},
}


def test_stated_fluid_grams_units():
    assert stated_fluid_grams("8 fl oz", "", 8.0) == pytest.approx(236.588)
    assert stated_fluid_grams("8 fluid ounces", "", 8.0) == pytest.approx(236.588)
    assert stated_fluid_grams("330 ml", "ml", 330.0) == 330.0
    assert stated_fluid_grams("8", "fl oz", 8.0) == pytest.approx(236.588)


def test_stated_fluid_grams_leaves_weights_alone():
    assert stated_fluid_grams("8 oz", "oz", 8.0) is None
    assert stated_fluid_grams("100 grams", "grams", 100.0) is None


def test_prompt_says_drink_ounces_are_fluid_ounces():
    assert "Drinks measured in ounces are fluid ounces" in SYSTEM_PROMPT
    assert "milk → fluid ounce" in SYSTEM_PROMPT
    assert "milk → ounce" not in SYSTEM_PROMPT


def test_prompt_defaults_unbranded_grains_to_cooked():
    assert "Unbranded grains and pasta" in SYSTEM_PROMPT
    assert "\"a cup of rice\" → food 'cooked rice'" in SYSTEM_PROMPT
    assert "unless the user says dry, uncooked or raw" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_8_fl_oz_of_milk_scales_by_volume():
    result = await _parse("8 oz of milk", "8 fl oz", "milk", MILK_NUTRITION)
    _assert_scaled(result, MILK_NUTRITION, 8 * 29.5735 / 244.0)
    assert result["amount"] == 8.0


# --- kitchen volumes convert through the food's own volume portion ---

OLIVE_OIL_NUTRITION = {
    "calories": 2016,
    "carbs": 0.0,
    "protein": 0.0,
    "fat": 224.0,
    "nutrients": {},
    "serving_size_g": 224.0,
    "candidates": [],
    "portion_options": [
        {"label": "1 tablespoon", "gram_weight": 14.0, "calories": 126.0},
        {"label": "1 cup", "gram_weight": 224.0, "calories": 2016.0},
    ],
    "resolution": {"status": "ok"},
}

DRY_RICE_NUTRITION = {
    "calories": 150,
    "carbs": 33.0,
    "protein": 3.0,
    "fat": 0.5,
    "nutrients": {},
    "serving_size_g": 45.0,
    "candidates": [],
    "portion_options": [{"label": "1/4 cup", "gram_weight": 45.0, "calories": 150.0}],
    "resolution": {"status": "ok"},
}

ALMOND_NUTRITION = {
    "calories": 160,
    "carbs": 6.0,
    "protein": 6.0,
    "fat": 14.0,
    "nutrients": {},
    "serving_size_g": 28.0,
    "candidates": [],
    "portion_options": [{"label": "1 ONZ", "gram_weight": 28.0, "calories": 160.0}],
    "resolution": {"status": "resolved", "axis": None},
}


def test_stated_volume_unit():
    assert stated_volume_unit("1 tablespoon", "serving") == "tablespoon"
    assert stated_volume_unit("1/4 cup", "cup") == "cup"
    assert stated_volume_unit("2 tsp", "") == "tsp"
    assert stated_volume_unit("2", "count") is None
    assert stated_volume_unit("100 grams", "grams") is None


def test_grams_per_tablespoon_from_portions():
    assert grams_per_tablespoon(OLIVE_OIL_NUTRITION["portion_options"]) == 14.0
    assert grams_per_tablespoon(DRY_RICE_NUTRITION["portion_options"]) == 45.0 / 4
    assert grams_per_tablespoon([{"label": "1 Tbsp", "gram_weight": 14.0}]) == 14.0
    assert grams_per_tablespoon(
        [{"label": "1 teaspoon, NFS", "gram_weight": 4.6}]
    ) == pytest.approx(13.8)


def test_grams_per_tablespoon_skips_yield_portions():
    """'yields' rows convert between forms (in shell -> kernels, dry -> cooked)."""
    peanuts = [
        {"label": "1 cup, in shell, yields", "gram_weight": 51.0},
        {"label": "1 cup", "gram_weight": 146.0},
    ]
    assert grams_per_tablespoon(peanuts) == 146.0 / 16
    oatmeal = [
        {"label": "1 cup, dry, yields", "gram_weight": 485.0},
        {"label": "1 cup, cooked", "gram_weight": 240.0},
    ]
    assert grams_per_tablespoon(oatmeal) == 240.0 / 16
    assert grams_per_tablespoon([{"label": "1 cup, dry, yields", "gram_weight": 485.0}]) is None


def test_grams_per_tablespoon_none_without_volume_portion():
    assert grams_per_tablespoon(ALMOND_NUTRITION["portion_options"]) is None
    assert grams_per_tablespoon(
        [{"label": "Guideline amount per fl oz of beverage", "gram_weight": 1.4}]
    ) is None
    assert grams_per_tablespoon([]) is None


@pytest.mark.asyncio
async def test_tablespoon_of_olive_oil_uses_tablespoon_portion():
    """Regression: '1 tablespoon' logged the record's 1-cup default (2,016 kcal)."""
    result = await _parse(
        "a tablespoon of olive oil", "1 tablespoon", "olive oil", OLIVE_OIL_NUTRITION
    )
    _assert_scaled(result, OLIVE_OIL_NUTRITION, 14.0 / 224.0)
    assert result["calories"] == 126


@pytest.mark.asyncio
async def test_cups_convert_through_quarter_cup_portion():
    result = await _parse("2 cups of rice", "2 cups", "rice", DRY_RICE_NUTRITION)
    _assert_scaled(result, DRY_RICE_NUTRITION, 8.0)


@pytest.mark.asyncio
async def test_unconvertible_volume_asks_instead_of_logging():
    result = await _parse("a quarter cup of almonds", "1/4 cup", "almonds", ALMOND_NUTRITION)
    assert result["resolution_status"] == "needs_clarification"
    assert result["resolution"]["axis"] == "amount"
    assert "cup measurement" in result["resolution"]["question"]
    assert "1 ONZ (160 cal)" in result["resolution"]["question"]
    assert result["confidence"] != "high"


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
