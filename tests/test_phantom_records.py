"""Phantom Qdrant rows (no serving data + 0 kcal / empty name) must not resolve."""
import json
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from backend.services.food_parser import UNRECOGNIZED_MESSAGE, parse_food_input
from backend.services.nutrition_service import (
    _pick_match_with_usable_calories,
    filter_phantom_matches,
    is_phantom_lookup_result,
    is_phantom_record,
)


def _phantom_meta(description="Light + Fit Dannon"):
    return {
        "description": description,
        "source": "branded_foods",
        "fat_level": "FAT_LEVEL_REDUCED",
    }


def _real_meta(name="DANNON LIGHT + FIT GREEK VANILLA", calories=80, serving=150.0):
    return {
        "name": name,
        "description": name,
        "calories": calories,
        "protein": 12,
        "carbs": 9,
        "fat": 0,
        "serving_size_g": serving,
        "brand_name": "DANNON",
        "source": "branded_foods",
    }


def test_session_style_row_is_phantom():
    assert is_phantom_record(_phantom_meta())
    assert is_phantom_record(
        {"description": "VANILLA ICED COFFEE, VANILLA", "source": "branded_foods"}
    )


def test_real_branded_row_is_not_phantom():
    assert not is_phantom_record(_real_meta())


def test_named_zero_cal_with_serving_is_not_phantom():
    """Diet soda / water with a real label serving is not this failure class."""
    assert not is_phantom_record(
        {
            "name": "Diet Coke",
            "calories": 0,
            "serving_size_g": 355,
            "source": "branded_foods",
        }
    )


def test_filter_drops_phantoms_from_candidate_set():
    phantom = {"id": "2745074", "score": 0.80, "metadata": _phantom_meta()}
    real = {"id": "999", "score": 0.55, "metadata": _real_meta()}
    assert filter_phantom_matches([phantom]) == []
    assert [m["id"] for m in filter_phantom_matches([phantom, real])] == ["999"]


def test_higher_scoring_phantom_does_not_win_over_real():
    phantom = {"id": "2745074", "score": 0.80, "metadata": _phantom_meta()}
    real = {"id": "999", "score": 0.55, "metadata": _real_meta()}
    picked = _pick_match_with_usable_calories(
        "Dan and Light and Fit Yogurt", [phantom, real]
    )
    assert picked is not None
    assert picked["id"] == "999"


def test_only_phantoms_means_no_match():
    phantom = {"id": "1220005", "score": 0.70, "metadata": _phantom_meta(
        "VANILLA ICED COFFEE, VANILLA"
    )}
    assert _pick_match_with_usable_calories(
        "One large McDonald's vanilla iced coffee", [phantom]
    ) is None


def test_normal_caloric_pick_still_wins():
    real = {"id": "banana", "score": 0.72, "metadata": _real_meta(
        "Banana, raw", calories=89, serving=118
    )}
    picked = _pick_match_with_usable_calories("banana", [real])
    assert picked is not None
    assert picked["id"] == "banana"


def _fake_retrieval(shallow_points, deep_points):
    """(patched query_points, recorded limits) for a two-depth Qdrant stub."""
    from backend.services import nutrition_service as ns

    limits: list[int] = []

    def fake_query_points(**kwargs):
        limits.append(kwargs["limit"])
        points = (
            deep_points
            if kwargs["limit"] == ns.RETRIEVAL_TOP_K_PHANTOM_ESCALATION
            else shallow_points
        )
        return SimpleNamespace(points=points)

    return fake_query_points, limits


async def _fake_embed(**kwargs):
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.0]) for _ in kwargs["input"]]
    )


@pytest.mark.asyncio
async def test_all_phantom_window_escalates_retrieval_depth():
    """A duplicated stub cluster must not starve out every real product.

    2026-08-30: 48 identical "Light + Fit Dannon" phantoms filled the whole
    top-25, so the filtered set was empty and the query reported
    not-recognized while 131 real Dannon rows sat below the window.
    """
    from backend.services import nutrition_service as ns

    phantoms = [
        SimpleNamespace(payload=_phantom_meta(), score=0.847)
        for _ in range(ns.RETRIEVAL_TOP_K)
    ]
    deep = phantoms + [SimpleNamespace(payload=_real_meta(), score=0.84)]
    fake_query_points, limits = _fake_retrieval(phantoms, deep)

    with patch.object(ns.qdrant_client, "query_points", side_effect=fake_query_points):
        with patch.object(
            ns.openai_client.embeddings, "create", side_effect=_fake_embed
        ):
            matches, _variant = await ns._retrieve_best("dannon light and fit yogurt")

    assert ns.RETRIEVAL_TOP_K_PHANTOM_ESCALATION in limits
    assert any(not ns.is_phantom_match(m) for m in matches)


@pytest.mark.asyncio
async def test_window_with_a_real_hit_does_not_escalate():
    """Escalation is a miss-only path — it must not re-query working queries."""
    from backend.services import nutrition_service as ns

    points = [
        SimpleNamespace(payload=_phantom_meta(), score=0.847),
        SimpleNamespace(payload=_real_meta(), score=0.72),
    ]
    fake_query_points, limits = _fake_retrieval(points, points)

    with patch.object(ns.qdrant_client, "query_points", side_effect=fake_query_points):
        with patch.object(
            ns.openai_client.embeddings, "create", side_effect=_fake_embed
        ):
            await ns._retrieve_best("banana")

    assert limits
    assert ns.RETRIEVAL_TOP_K_PHANTOM_ESCALATION not in limits


def test_lookup_result_shape_is_phantom():
    assert is_phantom_lookup_result(
        {
            "food_name": None,
            "calories": 0.0,
            "serving_source": "no_serving_data_fallback",
            "resolution": {"status": "resolved"},
        }
    )
    assert not is_phantom_lookup_result(
        {
            "food_name": "DANNON LIGHT + FIT",
            "calories": 80,
            "serving_source": "branded_serving_size",
            "resolution": {"status": "resolved"},
        }
    )


@pytest.mark.asyncio
async def test_phantom_top_match_never_resolves_or_logs():
    async def fake_create(**kwargs):
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "Dan and Light and Fit Yogurt",
            "brand": "Dan",
            "serving_size": "1",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    phantom_nutrition = {
        "calories": 0.0,
        "carbs": 0,
        "protein": 0,
        "fat": 0,
        "food_name": None,
        "serving_source": "no_serving_data_fallback",
        "serving_label": "100 g",
        "fdc_id": "2745074",
        "candidates": [],
        "resolution": {"status": "resolved", "axis": None},
    }

    with patch(
        "backend.services.food_parser.client.chat.completions.create",
        side_effect=fake_create,
    ):
        with patch(
            "backend.services.food_parser.lookup_food",
            new_callable=AsyncMock,
        ) as mock_lookup:
            mock_lookup.return_value = phantom_nutrition
            result = await parse_food_input(
                "Dan and Light and Fit Yogurt", conversation_history=[]
            )

    assert result["resolution_status"] == "unresolved"
    assert (result.get("resolution") or {}).get("status") == "unresolved"
    assert result.get("calories") is None
    assert result["confidence"] == "low"
    assert UNRECOGNIZED_MESSAGE in (result.get("reasoning") or "")
    events = result.get("food_events") or []
    assert events
    assert all(e.get("resolution_status") == "unresolved" for e in events)


@pytest.mark.asyncio
async def test_real_lookup_still_resolves_normally():
    async def fake_create(**kwargs):
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps({
            "food": "banana",
            "brand": "",
            "serving_size": "1",
            "confidence": "high",
            "alternatives": [],
        })
        return mock_response

    with patch(
        "backend.services.food_parser.client.chat.completions.create",
        side_effect=fake_create,
    ):
        with patch(
            "backend.services.food_parser.lookup_food",
            new_callable=AsyncMock,
        ) as mock_lookup:
            mock_lookup.return_value = {
                "calories": 89,
                "carbs": 23,
                "protein": 1,
                "fat": 0,
                "food_name": "Banana, raw",
                "serving_source": "sr_legacy_default_portion",
                "serving_label": "1 medium",
                "resolution": {"status": "resolved"},
            }
            result = await parse_food_input("one banana", conversation_history=[])

    assert result["calories"] == 89
    assert result["confidence"] == "high"
    assert result["food"] == "banana"
