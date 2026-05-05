import pytest
from backend.services.intent_classifier import classify_intent


@pytest.mark.asyncio
async def test_log_intent():
    result = await classify_intent("I just had two scrambled eggs")
    assert result["intent"] == "log"


@pytest.mark.asyncio
async def test_delete_last_intent():
    result = await classify_intent("delete my last entry")
    assert result["intent"] == "delete_last"


@pytest.mark.asyncio
async def test_read_today_intent():
    result = await classify_intent("what did I eat today")
    assert result["intent"] == "read_today"


@pytest.mark.asyncio
async def test_calories_today_intent():
    result = await classify_intent("how many calories have I had today")
    assert result["intent"] == "calories_today"


@pytest.mark.asyncio
async def test_correct_last_intent():
    result = await classify_intent("actually that was a large bowl not a small one")
    assert result["intent"] == "correct_last"


@pytest.mark.asyncio
async def test_unknown_intent():
    result = await classify_intent("what is the weather like today")
    assert result["intent"] == "unknown"