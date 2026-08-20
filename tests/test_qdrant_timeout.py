"""Qdrant outage should fail fast with NutritionStoreUnavailable, not hang."""

from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from backend.services.nutrition_service import (
    NutritionStoreUnavailable,
    _retrieve_best,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_retrieve_best_raises_on_qdrant_timeout():
    item = MagicMock()
    item.embedding = [0.1, 0.2]
    fake_embedding = MagicMock()
    fake_embedding.data = [item, item]

    async def fake_embed(**kwargs):
        return fake_embedding

    with patch(
        "backend.services.nutrition_service.openai_client.embeddings.create",
        side_effect=fake_embed,
    ):
        with patch(
            "backend.services.nutrition_service.qdrant_client.query_points",
            side_effect=ResponseHandlingException("timed out"),
        ):
            with pytest.raises(NutritionStoreUnavailable):
                await _retrieve_best("yogurt")
