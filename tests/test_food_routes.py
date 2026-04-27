import pytest


@pytest.mark.asyncio
async def test_post_food_parse_valid_returns_confidence(async_client):
    resp = await async_client.post(
        "/food/parse",
        json={"raw_input": "one apple"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "confidence" in body


@pytest.mark.asyncio
async def test_post_food_parse_paper_returns_error_not_422(async_client):
    resp = await async_client.post(
        "/food/parse",
        json={"raw_input": "paper"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
