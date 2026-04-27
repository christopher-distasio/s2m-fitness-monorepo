import pytest

from backend.services.food_parser import parse_food_input


@pytest.mark.asyncio
async def test_parse_two_scrambled_eggs_high_confidence():
    result = await parse_food_input("two scrambled eggs")
    assert result.get("confidence") == "high"


@pytest.mark.asyncio
async def test_parse_some_chicken_medium_and_alternatives():
    result = await parse_food_input("some chicken")
    assert result.get("confidence") == "medium"
    alternatives = result.get("alternatives") or []
    assert isinstance(alternatives, list)
    assert len(alternatives) > 0


@pytest.mark.asyncio
async def test_parse_lunch_low_confidence():
    result = await parse_food_input("lunch")
    assert result.get("confidence") == "low"


@pytest.mark.asyncio
async def test_parse_paper_has_error_key():
    result = await parse_food_input("paper")
    assert "error" in result


@pytest.mark.asyncio
async def test_parse_some_chips_alternatives_no_cal_substring():
    result = await parse_food_input("some chips")
    alternatives = result.get("alternatives") or []
    for alt in alternatives:
        assert isinstance(alt, str)
        assert "cal" not in alt.lower()
