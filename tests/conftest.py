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