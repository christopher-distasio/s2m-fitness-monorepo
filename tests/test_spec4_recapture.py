"""Spec 4 — partial recapture, circuit-breaker, and merge into Spec 2."""

from __future__ import annotations

from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.confidence import ASR_MEDIUM, compute_band
from backend.services.confirmation import attach_confirmation, evaluate_confirmation
from backend.services.recapture import (
    BREAKER_VARIED_PROMPT,
    MODALITY_SWITCH_PROMPT,
    NOTHING_USABLE_PROMPT,
    PARTIAL_PROMPT,
    RECAPTURE_FAILURES_BEFORE_BREAKER,
    food_identity_trusted,
    merge_recapture_text,
    next_recapture_state,
    recapture_from_history,
    recapture_prompt,
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


def test_successful_recapture_merge_then_spec2_uses_real_bands():
    merged = merge_recapture_text({"food": "chicken sandwich"}, "two")
    assert merged == "chicken sandwich two"
    parsed = _parsed({"amount": "medium", "food": "high"}, food="chicken sandwich")
    parsed["amount"] = 2
    attach_confirmation(parsed, merged)
    amount_band = parsed["confidence_detail"]["amount"]["band"]
    assert amount_band in {"high", "medium", "low"}
    assert amount_band == "medium"
    decision = evaluate_confirmation(parsed, merged)
    assert decision.action in {"SILENT", "CONFIRM", "ASK"}
    band = compute_band(asr=-0.4, semantic=-0.3)
    assert band in {"high", "medium", "low"}


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
