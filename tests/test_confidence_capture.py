"""Four-layer confidence band tests (mocked signals; no live APIs)."""

from types import SimpleNamespace

import pytest

from backend.services.confidence import (
    compute_band,
    extract_semantic_logprob,
    field_confidence,
)


def test_compute_band_skips_missing_layers():
    assert compute_band(asr=None, semantic=None, database=0.9) == "high"
    assert compute_band(asr=None, semantic=-0.1, database=None) == "high"
    assert compute_band(asr=None, semantic=None, database=None, fallback="high") == "high"


def test_compute_band_extraction_failure_is_low():
    assert (
        compute_band(
            asr=-0.1,
            semantic=-0.1,
            database=0.9,
            extraction_failed=True,
        )
        == "low"
    )


def test_compute_band_uses_minimum_present_layer():
    assert compute_band(asr=-0.1, semantic=-0.1, database=0.2) == "low"


def test_small_database_gap_caps_high_at_medium():
    assert (
        compute_band(database=0.9, database_gap=0.01) == "medium"
    )


def test_decision_logic_reads_band_only():
    fc = field_confidence(asr=-0.1, semantic=-0.1, database=0.9)
    assert fc.band == "high"
    # raw floats stored, not used for branching
    assert fc.asr == -0.1
    assert fc.database == 0.9


def test_extract_semantic_logprob_from_known_tokens():
    tokens = [
        SimpleNamespace(token="ban", logprob=-0.1),
        SimpleNamespace(token="ana", logprob=-0.2),
        SimpleNamespace(token="!", logprob=-2.0),
    ]
    response = SimpleNamespace(
        choices=[SimpleNamespace(logprobs=SimpleNamespace(content=tokens))]
    )
    value = extract_semantic_logprob(response, "banana")
    assert value == pytest.approx(-0.15)


def test_extract_semantic_logprob_missing_is_none():
    response = SimpleNamespace(choices=[SimpleNamespace(logprobs=None)])
    assert extract_semantic_logprob(response, "banana") is None
