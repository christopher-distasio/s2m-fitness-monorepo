import asyncio
import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from asgi_lifespan import LifespanManager
from backend.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def async_client():
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

@pytest.fixture(autouse=True)
def _dense_search_mode_by_default(monkeypatch):
    """Unit tests run in the code default (dense) whatever the local .env
    sets; hybrid tests opt in with monkeypatch. The local .env switched to
    SEARCH_MODE=hybrid on 2026-11-21, which sent tests that fake the dense
    client through the real hybrid client instead."""
    import backend.services.nutrition_service as ns

    monkeypatch.setattr(ns, "SEARCH_MODE", "dense")
