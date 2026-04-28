import pytest

USER_ID = "test_user"

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


@pytest.mark.asyncio
async def test_post_food_two_eggs_returns_id_and_parsed(async_client):
    log_id = None
    try:
        resp = await async_client.post(
            "/food",
            json={"user_id": USER_ID, "raw_input": "two eggs"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert "parsed" in body
        assert isinstance(body["parsed"], dict)
        log_id = body["id"]
    finally:
        if log_id is not None:
            await async_client.delete(f"/food/{log_id}")


@pytest.mark.asyncio
async def test_delete_food_removes_entry(async_client):
    log_id = None
    try:
        post = await async_client.post(
            "/food",
            json={"user_id": USER_ID, "raw_input": "two eggs"},
        )
        assert post.status_code == 200
        log_id = post.json()["id"]
        del_resp = await async_client.delete(f"/food/{log_id}")
        assert del_resp.status_code == 200
        get_resp = await async_client.get(f"/food/{USER_ID}")
        assert get_resp.status_code == 200
        logs = get_resp.json()
        assert log_id not in [log["_id"] for log in logs]
    finally:
        if log_id is not None:
            await async_client.delete(f"/food/{log_id}")


@pytest.mark.asyncio
async def test_get_food_summary_has_expected_keys(async_client):
    resp = await async_client.get(f"/food/{USER_ID}/summary")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("calories", "protein", "carbs", "fat", "entry_count"):
        assert key in body