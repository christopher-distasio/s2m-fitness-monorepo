"""Live regression: Dannon Light / Light + Fit must resolve, not 'not recognized'.

Needs local Qdrant + embeddings. Skip in default CI.

Run: poetry run pytest tests/test_dannon_light_lookup.py -v -m live
"""

from __future__ import annotations

import pytest

from backend.services.nutrition_service import lookup_food
from backend.services.parse_query_modifiers import parse_query_modifiers


def _mentions_dannon(result: dict) -> bool:
    hay = f"{result.get('food_name') or ''} {result.get('brand') or ''}".lower()
    return "dannon" in hay or "danone" in hay


@pytest.fixture(scope="module")
def ensure_qdrant():
    try:
        from qdrant_client import QdrantClient

        from backend.services.nutrition_service import COLLECTION_NAME, QDRANT_URL

        client = QdrantClient(url=QDRANT_URL, timeout=10)
        client.get_collection(COLLECTION_NAME)
    except Exception as exc:
        pytest.skip(f"Qdrant not available: {exc}")


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "dannon light and fit yogurt",
        "dannon light yogurt",
    ],
)
async def test_dannon_light_queries_resolve_to_dannon(ensure_qdrant, query):
    modifiers = parse_query_modifiers(query)
    assert modifiers["fat_level"] == "NONE"

    result = await lookup_food(
        query,
        source_filter="brand",
        modifiers=modifiers,
        stated_brand="Dannon",
    )
    assert result is not None
    assert not result.get("blocked_by_allergy")
    assert result.get("calories") is not None
    assert float(result["calories"]) > 0.5
    assert _mentions_dannon(result)
