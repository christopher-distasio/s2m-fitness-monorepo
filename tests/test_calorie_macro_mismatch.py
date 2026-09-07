"""Passive Atwater mismatch marker on match metadata.

Pins the four known cases from the branded residual analysis. Deterministic —
no network. The flag is metadata only; ranking is covered by the live
retrieval re-run, not these tests.
"""

from types import SimpleNamespace

import pytest

from backend.services.query_match_rank import rerank_matches_by_query
from backend.services.nutrition_service import (
    CALORIE_MACRO_MISMATCH_KCAL_KEY,
    CALORIE_MACRO_MISMATCH_KEY,
    CALORIE_MACRO_MISMATCH_REL_KEY,
    CALORIE_MACRO_MISMATCH_REL_THRESHOLD,
    _pick_match_with_usable_calories,
    _qdrant_results_to_matches,
    attach_calorie_macro_mismatch,
    calorie_macro_mismatch_fields,
    filter_phantom_matches,
    normalize_nutrients_to_per_100g,
)
from tests.test_per_serving_nutrient_basis import (
    DANNON_2756149,
    DANNON_2756921,
    NIDO_2688156_GDSN,
)

# fdc_id 1279267 — live Qdrant payload 2026-09-06. Eval query "Kirkland protein
# bar" retrieves this LI row (description "HIGH PROTEIN BAR"); brand_name on
# the point is SEITENBACHER. Numbers match the blast-radius pass (rel 0.19,
# 36.8 kcal at the 60 g serving).
KIRKLAND_1279267 = {
    "fdc_id": "1279267",
    "qdrant_id": "1279267",
    "name": "SEITENBACHER HIGH PROTEIN BAR",
    "description": "HIGH PROTEIN BAR",
    "source": "branded_foods",
    "brand_name": "SEITENBACHER",
    "data_source": "LI",
    "serving_size_g": 60.0,
    "calories": 317.0,
    "protein": 26.67,
    "fat": 11.67,
    "carbs": 41.67,
}

MISMATCH_KEYS = (
    CALORIE_MACRO_MISMATCH_KEY,
    CALORIE_MACRO_MISMATCH_REL_KEY,
    CALORIE_MACRO_MISMATCH_KCAL_KEY,
)


def _bridge_meta(payload: dict) -> dict:
    matches = _qdrant_results_to_matches(
        [SimpleNamespace(payload=payload, score=0.85)]
    )
    return matches[0]["metadata"]


def _mismatch_only(meta: dict) -> dict:
    return {k: meta[k] for k in MISMATCH_KEYS if k in meta}


def test_threshold_is_the_named_constant_not_an_inline_literal():
    assert CALORIE_MACRO_MISMATCH_REL_THRESHOLD == 0.15


def test_dannon_2756921_is_flagged():
    """Euromonitor, rel 0.90, 72 kcal at the cup — the known fat-duplication row."""
    meta = _bridge_meta(DANNON_2756921)
    assert meta[CALORIE_MACRO_MISMATCH_KEY] is True
    assert round(meta[CALORIE_MACRO_MISMATCH_REL_KEY], 2) == 0.90
    assert round(meta[CALORIE_MACRO_MISMATCH_KCAL_KEY], 1) == 72.0


def test_kirkland_1279267_is_flagged():
    """LI protein bar, rel 0.19, 36.8 kcal at the 60 g serving."""
    meta = _bridge_meta(KIRKLAND_1279267)
    assert meta[CALORIE_MACRO_MISMATCH_KEY] is True
    assert round(meta[CALORIE_MACRO_MISMATCH_REL_KEY], 2) == 0.19
    assert round(meta[CALORIE_MACRO_MISMATCH_KCAL_KEY], 1) == 36.8


def test_dannon_2756149_fat_zero_still_exceeds_threshold():
    """Sibling of 2756921 with fat=0.0 (correct for nonfat). Stored 110 vs
    Atwater 80 is a 27% residual, so the 15% rule flags it. Fat=0.0 is not
    missing — it is a present zero — and calories are positive, so this is
    a computed True, not unknown.
    """
    meta = _bridge_meta(DANNON_2756149)
    assert DANNON_2756149["fat"] == 0.0
    assert meta[CALORIE_MACRO_MISMATCH_KEY] is True
    assert round(meta[CALORIE_MACRO_MISMATCH_REL_KEY], 4) == 0.2727
    assert round(meta[CALORIE_MACRO_MISMATCH_KCAL_KEY], 1) == 30.0


def test_missing_macros_are_unknown_not_false():
    payload = {
        "fdc_id": "missing-protein",
        "qdrant_id": "missing-protein",
        "source": "branded_foods",
        "data_source": "LI",
        "serving_size_g": 100.0,
        "calories": 120.0,
        "carbs": 10.0,
        "fat": 5.0,
        # protein omitted
    }
    meta = _bridge_meta(payload)
    for key in MISMATCH_KEYS:
        assert key not in meta
    assert calorie_macro_mismatch_fields(meta) is None


def test_nonpositive_calories_are_unknown_not_false():
    payload = {
        "calories": 0,
        "protein": 18,
        "carbs": 1,
        "fat": 3,
        "serving_size_g": 56.0,
    }
    assert calorie_macro_mismatch_fields(payload) is None
    stamped = attach_calorie_macro_mismatch(payload)
    assert stamped is payload
    for key in MISMATCH_KEYS:
        assert key not in stamped


def test_clean_row_is_explicitly_false_not_absent():
    """NIDO GDSN: Atwater 507.1 vs stored 500 is 1.4%, under the threshold."""
    meta = _bridge_meta(NIDO_2688156_GDSN)
    assert CALORIE_MACRO_MISMATCH_KEY in meta
    assert meta[CALORIE_MACRO_MISMATCH_KEY] is False
    assert meta[CALORIE_MACRO_MISMATCH_REL_KEY] < CALORIE_MACRO_MISMATCH_REL_THRESHOLD


def test_bridge_does_not_mutate_source_payload():
    original = dict(KIRKLAND_1279267)
    _bridge_meta(KIRKLAND_1279267)
    assert KIRKLAND_1279267 == original
    for key in MISMATCH_KEYS:
        assert key not in KIRKLAND_1279267


def test_residual_is_computed_after_normalize_not_from_raw_euromonitor():
    """Raw Euromonitor 2756921 is 80/12/8/8; the marker must use per-100g
    numbers (rel is scale-invariant, but kcal delta is taken at serving size
    on the normalized basis, which still equals 72 kcal at the cup).
    """
    raw_fields = calorie_macro_mismatch_fields(DANNON_2756921)
    normalized = normalize_nutrients_to_per_100g(DANNON_2756921)
    norm_fields = calorie_macro_mismatch_fields(normalized)
    bridged = _mismatch_only(_bridge_meta(DANNON_2756921))
    assert raw_fields is not None and norm_fields is not None
    assert raw_fields[CALORIE_MACRO_MISMATCH_REL_KEY] == pytest.approx(
        norm_fields[CALORIE_MACRO_MISMATCH_REL_KEY]
    )
    assert bridged[CALORIE_MACRO_MISMATCH_KEY] is norm_fields[
        CALORIE_MACRO_MISMATCH_KEY
    ]
    assert bridged[CALORIE_MACRO_MISMATCH_REL_KEY] == pytest.approx(
        norm_fields[CALORIE_MACRO_MISMATCH_REL_KEY]
    )
    assert bridged[CALORIE_MACRO_MISMATCH_KCAL_KEY] == pytest.approx(
        norm_fields[CALORIE_MACRO_MISMATCH_KCAL_KEY]
    )
    # Raw per-serving Atwater kcal delta is also 72; the important guard is
    # that the bridge did not skip normalize (calories are no longer 80).
    assert _bridge_meta(DANNON_2756921)["calories"] != DANNON_2756921["calories"]


def test_flag_does_not_change_rerank_phantom_or_calorie_pick():
    """Scoring consumers ignore the mismatch keys — order and pick are identical."""
    matches = _qdrant_results_to_matches(
        [
            SimpleNamespace(payload=DANNON_2756921, score=0.84),
            SimpleNamespace(payload=DANNON_2756149, score=0.83),
            SimpleNamespace(payload=KIRKLAND_1279267, score=0.40),
        ]
    )
    stripped = []
    for match in matches:
        meta = {
            k: v for k, v in match["metadata"].items() if k not in MISMATCH_KEYS
        }
        stripped.append({**match, "metadata": meta})

    query = "dannon light and fit yogurt"
    assert [m["id"] for m in rerank_matches_by_query(query, matches)] == [
        m["id"] for m in rerank_matches_by_query(query, stripped)
    ]
    assert [m["id"] for m in filter_phantom_matches(matches)] == [
        m["id"] for m in filter_phantom_matches(stripped)
    ]
    picked_flagged = _pick_match_with_usable_calories(query, matches)
    picked_stripped = _pick_match_with_usable_calories(query, stripped)
    assert picked_flagged is not None and picked_stripped is not None
    assert picked_flagged["id"] == picked_stripped["id"]
