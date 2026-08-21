"""Spec 0 safety detector + pipeline ordering."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.domain_boundary import OFF_DOMAIN_DECLINE, is_off_domain
from backend.services.safety_detector import (
    FORBIDDEN_SAFETY_ASSERTIONS,
    SELF_HARM_RESPONSE,
    build_safety_response,
    contains_safety_assertion,
    detect_safety,
)
from backend.services.utterance_pipeline import (
    PIPELINE_ORDER,
    dispatch_voice_utterance,
    run_safety_and_domain,
)


def test_pipeline_order_is_safety_first():
    assert PIPELINE_ORDER[0] == "safety"
    assert PIPELINE_ORDER[1] == "domain_boundary"
    assert PIPELINE_ORDER[2] == "intent"


@pytest.mark.asyncio
async def test_safety_runs_before_intent_and_domain():
    """A medical utterance stops at safety — classifier never runs."""
    with (
        patch(
            "backend.services.utterance_pipeline.classify_intent",
            new_callable=AsyncMock,
        ) as mock_classify,
        patch(
            "backend.services.utterance_pipeline.is_off_domain",
            return_value=True,
        ) as mock_domain,
        patch(
            "backend.services.safety_detector.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await dispatch_voice_utterance(
            "I think I'm having an allergic reaction", "u1"
        )

    assert result.kind == "safety"
    assert result.stages == ["safety"]
    mock_classify.assert_not_called()
    mock_domain.assert_not_called()
    assert result.response["logged"] is False
    assert result.response["error"] == "safety"


@pytest.mark.asyncio
async def test_medical_reaction_is_not_off_domain_and_has_no_safety_assertion():
    log = SimpleNamespace(
        food_name="peanut butter sandwich",
        food_event={
            "food": "peanut butter sandwich",
            "allergen_state": {"peanut": "contains"},
            "restriction_tags": {},
            "certification_status": {},
            "evidence_basis": {"peanut": "declared_ingredient"},
        },
    )
    with (
        patch(
            "backend.services.safety_detector.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=log,
        ),
        patch(
            "backend.services.safety_detector.load_user_profile",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        hit = detect_safety("I think I'm having an allergic reaction")
        assert hit is not None
        assert hit.category == "medical_reaction"
        response = await build_safety_response(hit, "u1", hit.matched)

    message = response["message"]
    assert contains_safety_assertion(message) is False
    for phrase in FORBIDDEN_SAFETY_ASSERTIONS:
        assert phrase not in message.lower()
    assert "peanut butter sandwich" in message
    assert "peanut" in message.lower()
    assert "contains" in message.lower()
    assert "can't provide medical guidance" in message.lower()
    assert is_off_domain("I think I'm having an allergic reaction") is False


@pytest.mark.asyncio
async def test_self_harm_is_not_routed_to_logging_and_points_to_help():
    with (
        patch(
            "backend.services.utterance_pipeline.classify_intent",
            new_callable=AsyncMock,
        ) as mock_classify,
        patch(
            "backend.services.safety_detector.latest_log_for_user",
            new_callable=AsyncMock,
        ) as mock_log,
    ):
        result = await dispatch_voice_utterance("I want to kill myself", "u1")

    assert result.kind == "safety"
    assert result.response["safety_category"] == "self_harm"
    assert result.response["logged"] is False
    assert "988" in result.response["message"]
    assert result.response["message"] == SELF_HARM_RESPONSE
    mock_classify.assert_not_called()
    mock_log.assert_not_called()
    assert "what did you eat" not in result.response["message"].lower()
    assert "calories" not in result.response["message"].lower()


def test_weather_is_off_domain_not_safety():
    assert detect_safety("what's the weather") is None
    assert is_off_domain("what's the weather") is True


@pytest.mark.asyncio
async def test_weather_gets_decline_not_safety_or_log():
    with patch(
        "backend.services.utterance_pipeline.classify_intent",
        new_callable=AsyncMock,
    ) as mock_classify:
        result = await dispatch_voice_utterance("what's the weather", "u1")

    assert result.kind == "off_domain"
    assert result.stages == ["safety", "domain_boundary"]
    assert result.response["message"] == OFF_DOMAIN_DECLINE
    assert result.response["logged"] is False
    mock_classify.assert_not_called()


@pytest.mark.asyncio
async def test_on_domain_log_flows_through_unchanged():
    with patch(
        "backend.services.utterance_pipeline.classify_intent",
        new_callable=AsyncMock,
        return_value={"intent": "log", "text": "two scrambled eggs"},
    ) as mock_classify:
        result = await dispatch_voice_utterance("two scrambled eggs", "u1")

    assert result.kind == "log"
    assert result.stages == ["safety", "domain_boundary", "intent", "handler"]
    assert result.response is None
    mock_classify.assert_awaited_once()


def test_safety_detector_is_cheap_on_every_utterance():
    samples = [
        "two eggs",
        "what's the weather",
        "delete my last entry",
        "I had a banana",
    ]
    start = time.perf_counter()
    for _ in range(200):
        for text in samples:
            detect_safety(text)
            is_off_domain(text)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_text_path_gate_intercepts_safety_without_intent_classifier():
    with (
        patch(
            "backend.services.utterance_pipeline.classify_intent",
            new_callable=AsyncMock,
        ) as mock_classify,
        patch(
            "backend.services.safety_detector.latest_log_for_user",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_safety_and_domain(
            "my throat feels tight", "u1"
        )

    assert result.kind == "safety"
    mock_classify.assert_not_called()


@pytest.mark.asyncio
async def test_text_path_still_bypasses_intent_on_normal_food():
    """Known gap: text does not classify intent. Do not make it worse."""
    with patch(
        "backend.services.utterance_pipeline.classify_intent",
        new_callable=AsyncMock,
    ) as mock_classify:
        result = await run_safety_and_domain("actually it was oat milk", "u1")

    assert result.kind == "log"
    assert result.response is None
    mock_classify.assert_not_called()
