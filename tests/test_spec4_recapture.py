"""Spec 4 — partial recapture, circuit-breaker, and merge into Spec 2."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.confidence import ASR_MEDIUM, compute_band
from backend.services.confirmation import attach_confirmation, evaluate_confirmation
from backend.services.recapture import (
    BREAKER_VARIED_PROMPT,
    MODALITY_SWITCH_PROMPT,
    NOTHING_USABLE_PROMPT,
    RECAPTURE_FAILURES_BEFORE_BREAKER,
    food_identity_trusted,
    merge_recapture_text,
    next_recapture_state,
    recapture_from_history,
    recapture_prompt,
    reset_recapture_state,
    should_enter_recapture,
    unparsed_tail,
)


ERROR_PROCESSING_AUDIO = "Error processing audio. Please try again."


def _parsed(bands: dict[str, str] | None = None, **extra) -> dict:
    detail = {key: {"band": "high"} for key in CONFIDENCE_FIELD_KEYS}
    for key, band in (bands or {}).items():
        detail[key] = {"band": band}
    out = {
        "food": extra.pop("food", "chicken sandwich"),
        "calories": extra.pop("calories", 420),
        "confidence_detail": detail,
        "macronutrients": extra.pop(
            "macronutrients",
            {"protein": 30, "carbohydrates": 40, "fats": 12},
        ),
    }
    out.update(extra)
    return out


def test_partial_recapture_names_captured_food_not_generic_restart():
    parsed = _parsed()
    transcript = "chicken sandwich blargh xyzzy"
    assert unparsed_tail(transcript, "chicken sandwich")
    assert should_enter_recapture(parsed, transcript, asr=-0.2, input_modality="voice")
    state = recapture_prompt(
        parsed=parsed,
        transcript=transcript,
        asr=-0.2,
        failures=0,
        input_modality="voice",
    )
    assert "chicken sandwich" in state["prompt"]
    assert "missed what came after" in state["prompt"]
    assert "sorry, i didn't understand" not in state["prompt"].lower()
    assert ERROR_PROCESSING_AUDIO not in state["prompt"]


def test_nothing_usable_is_actionable_not_generic_audio_error():
    parsed = {"error": "unparseable", "raw": "asdfgh"}
    assert should_enter_recapture(parsed, "asdfgh", asr=-1.2, input_modality="voice")
    state = recapture_prompt(
        parsed=parsed,
        transcript="asdfgh",
        asr=-1.2,
        failures=0,
        input_modality="voice",
    )
    assert state["prompt"] == NOTHING_USABLE_PROMPT
    assert ERROR_PROCESSING_AUDIO not in state["prompt"]
    assert "error processing audio" not in state["prompt"].lower()


def test_old_generic_audio_error_not_used_in_voice_codepath():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/services/recapture.py",
        root / "backend/routes/food.py",
        root / "frontend/pages/index.tsx",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert ERROR_PROCESSING_AUDIO not in text, path


def test_typed_input_does_not_enter_recapture():
    parsed = {"error": "unparseable", "raw": "asdf"}
    assert not should_enter_recapture(parsed, "asdf", asr=-1.0, input_modality="text")
    assert not should_enter_recapture(parsed, "asdf", asr=-1.0, input_modality=None)


_GPT_PARSE_NO_BANDS = {
    "food": "chicken sandwich",
    "amount": 2,
    "serving_size": "2",
    "confidence": "high",
    "alternatives": [],
}


@pytest.mark.asyncio
async def test_merged_recapture_amount_band_comes_from_compute_band():
    """Recaptured 'two' gets compute_band() through the real parse path.

    Merge → _continue_recapture → _parse_log_utterance → parse_food_input →
    field_confidence/compute_band → attach_confirmation. The GPT stub has no
    confidence_detail. asr=-0.50 yields medium; a recapture high/low stamp fails.
    """
    from backend.routes.food import _continue_recapture, _parse_log_utterance

    merged = merge_recapture_text({"food": "chicken sandwich"}, "two")
    assert merged == "chicken sandwich two"
    assert "confidence_detail" not in _GPT_PARSE_NO_BANDS
    assert "band" not in _GPT_PARSE_NO_BANDS

    asr = -0.50
    expected_band = compute_band(asr=asr, semantic=None)
    assert expected_band == "medium"

    history = [
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "recapture": {
                        "pending": True,
                        "captured": {"food": "chicken sandwich"},
                        "failures": 0,
                        "missing_field": "trailing",
                    }
                }
            ),
        }
    ]
    seen_user_text: dict[str, str] = {}

    async def fake_create(**kwargs):
        seen_user_text["content"] = kwargs["messages"][-1]["content"]
        mock_response = AsyncMock()
        mock_response.choices[0].message.content = json.dumps(_GPT_PARSE_NO_BANDS)
        mock_response.choices[0].logprobs = None
        return mock_response

    with patch(
        "backend.services.food_parser.client.chat.completions.create",
        side_effect=fake_create,
    ), patch(
        "backend.services.food_parser.lookup_food",
        new_callable=AsyncMock,
        return_value={
            "calories": 420,
            "carbs": 40,
            "protein": 30,
            "fat": 12,
        },
    ), patch(
        "backend.services.food_parser._fetch_dietary_preferences",
        new_callable=AsyncMock,
        return_value=None,
    ):
        continued = await _continue_recapture("user-1", "two", history, asr)
        first_pass = await _parse_log_utterance(
            merged,
            [],
            user_id="user-1",
            input_modality="voice",
            activation="push_to_talk",
            asr=asr,
        )

    assert continued.get("raw_input") == merged
    assert not continued.get("recapture")
    parsed = continued["parsed"]
    assert seen_user_text["content"] == merged
    amount = parsed["confidence_detail"]["amount"]
    assert amount["band"] == expected_band
    assert amount["asr"] == asr
    assert amount["band"] == first_pass["confidence_detail"]["amount"]["band"]
    attach_confirmation(parsed, merged)
    assert parsed["confidence_detail"]["amount"]["band"] == expected_band
    decision = evaluate_confirmation(parsed, merged)
    assert decision.action in {"SILENT", "CONFIRM", "ASK"}


def test_low_asr_food_identity_is_not_trusted():
    parsed = _parsed({"food": "high"})
    assert food_identity_trusted(parsed, asr=-0.2)
    assert not food_identity_trusted(parsed, asr=ASR_MEDIUM - 0.05)


def test_circuit_breaker_third_prompt_differs():
    parsed = {"error": "unparseable", "raw": "xx"}
    p1 = recapture_prompt(
        parsed=parsed, transcript="xx", asr=-1.0, failures=0, input_modality="voice"
    )
    p2 = recapture_prompt(
        parsed=parsed, transcript="xx", asr=-1.0, failures=1, input_modality="voice"
    )
    p3 = recapture_prompt(
        parsed=parsed, transcript="xx", asr=-1.0, failures=2, input_modality="voice"
    )
    assert RECAPTURE_FAILURES_BEFORE_BREAKER == 2
    assert p1["prompt"] == p2["prompt"] == NOTHING_USABLE_PROMPT
    assert p3["prompt"] != p1["prompt"]
    assert p3["prompt"] != p2["prompt"]
    assert p3["kind"] == "modality_switch"
    assert p3["modality_switch"] is True


def test_modality_switch_not_on_first_failure_uses_input_modality():
    parsed = {"error": "unparseable"}
    first = recapture_prompt(
        parsed=parsed, transcript="x", asr=-1.0, failures=0, input_modality="voice"
    )
    assert first["modality_switch"] is False
    assert first["input_modality"] == "voice"
    text_breaker = recapture_prompt(
        parsed=parsed, transcript="x", asr=-1.0, failures=2, input_modality="text"
    )
    assert text_breaker["modality_switch"] is False
    assert text_breaker["prompt"] == BREAKER_VARIED_PROMPT
    voice_breaker = recapture_prompt(
        parsed=parsed, transcript="x", asr=-1.0, failures=2, input_modality="voice"
    )
    assert voice_breaker["modality_switch"] is True
    assert voice_breaker["prompt"] == MODALITY_SWITCH_PROMPT
    with_candidates = recapture_prompt(
        parsed={
            "error": "unparseable",
            "candidates": [{"name": "oats"}, {"name": "oatmeal"}],
        },
        transcript="oat",
        asr=-1.0,
        failures=2,
        input_modality="voice",
    )
    assert with_candidates["kind"] == "contrastive"
    assert with_candidates["modality_switch"] is False
    assert "oats" in with_candidates["prompt"].lower()


def test_failure_counter_resets_after_success():
    failed = next_recapture_state(
        {"pending": True, "failures": 2, "missing_field": "food", "captured": {}},
        parsed={"error": "unparseable"},
        transcript="zz",
        asr=-1.0,
        input_modality="voice",
        failed=True,
    )
    assert failed["failures"] == 3
    reset = next_recapture_state(
        failed,
        parsed=_parsed(),
        transcript="two eggs",
        asr=-0.2,
        input_modality="voice",
        failed=False,
    )
    assert reset["failures"] == 0
    later = recapture_from_history(
        [
            {
                "role": "assistant",
                "content": '{"recapture": {"pending": false, "failures": 0}}',
            }
        ]
    )
    assert later is None
    fresh = recapture_prompt(
        parsed={"error": "unparseable"},
        transcript="nn",
        asr=-1.0,
        failures=0,
        input_modality="voice",
    )
    assert fresh["failures"] == 0
    assert fresh["prompt"] == NOTHING_USABLE_PROMPT


def test_failure_counter_resets_on_dismiss():
    """dismissPending() clears conversation history; the next attempt starts at 0."""
    pending = recapture_prompt(
        parsed={"error": "unparseable"},
        transcript="xx",
        asr=-1.0,
        failures=2,
        input_modality="voice",
    )
    assert pending["failures"] == 2
    history = [
        {
            "role": "assistant",
            "content": json.dumps({"recapture": pending}),
        }
    ]
    assert recapture_from_history(history)["failures"] == 2

    dismissed_history: list = []
    assert recapture_from_history(dismissed_history) is None
    assert reset_recapture_state()["failures"] == 0

    later = next_recapture_state(
        recapture_from_history(dismissed_history),
        parsed={"error": "unparseable"},
        transcript="yy",
        asr=-1.0,
        input_modality="voice",
        failed=True,
    )
    assert later["failures"] == 1
    assert later["prompt"] == NOTHING_USABLE_PROMPT
    assert later["prompt"] != pending["prompt"]


def test_breaker_uses_contrastive_helper_not_a_copy():
    state = recapture_prompt(
        parsed={
            "candidates": [
                {"name": "chicken sandwich"},
                {"name": "turkey sandwich"},
            ]
        },
        transcript="sandwich",
        asr=-1.0,
        failures=2,
        input_modality="voice",
    )
    assert state["prompt"].startswith("Was that ")
    assert "chicken sandwich" in state["prompt"]
