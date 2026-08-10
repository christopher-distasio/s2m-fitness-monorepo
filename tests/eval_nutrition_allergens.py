"""Live Qdrant fixtures for nutrition backfill + retrieval regressions.

Marked @pytest.mark.live — skip in default CI. Requires local Qdrant at
http://localhost:6333 with collection food-vectors populated.

Run: poetry run pytest tests/eval_nutrition_allergens.py -v -m live
"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION = "food-vectors"


@pytest.fixture(scope="module")
def qdrant():
    client = QdrantClient(url=QDRANT_URL, timeout=30)
    try:
        client.get_collection(COLLECTION)
    except Exception as exc:
        pytest.skip(f"Qdrant not available at {QDRANT_URL}: {exc}")
    return client


def _payload_for(client: QdrantClient, qdrant_id: str) -> dict:
    pts, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="qdrant_id", match=models.MatchValue(value=str(qdrant_id))
                )
            ]
        ),
        limit=3,
        with_payload=True,
        with_vectors=False,
    )
    assert pts, f"expected at least one point for qdrant_id={qdrant_id}"
    return pts[0].payload or {}


def _all_payloads(client: QdrantClient, qdrant_id: str) -> list[dict]:
    pts, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="qdrant_id", match=models.MatchValue(value=str(qdrant_id))
                )
            ]
        ),
        limit=10,
        with_payload=True,
        with_vectors=False,
    )
    return [p.payload or {} for p in pts]


# ---------------------------------------------------------------------------
# Nutrition correctness (sugar-bug class)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_hershey_bar_sugar_populated(qdrant):
    """fdc 1847371 — regression guard for sugar ID 2000 vs 1063."""
    p = _payload_for(qdrant, "1847371")
    assert p.get("sugar") is not None
    assert 50 <= float(p["sugar"]) <= 65, p.get("sugar")
    assert p.get("calories") is not None


@pytest.mark.live
def test_peppermint_candy_high_sugar(qdrant):
    p = _payload_for(qdrant, "1107490")
    assert p.get("sugar") is not None
    assert float(p["sugar"]) >= 90


@pytest.mark.live
def test_fndds_milk_nfs_macros_present(qdrant):
    p = _payload_for(qdrant, "2705384")
    assert p.get("calories") is not None
    assert p.get("protein") is not None
    assert p.get("sugar") is not None
    assert float(p["calories"]) > 0


# ---------------------------------------------------------------------------
# Provenance tags
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_moose_tracks_vitamin_a_unsupported_and_d_converted(qdrant):
    p = _payload_for(qdrant, "1106143")
    assert p.get("vitamin_a_source") == "unsupported_conversion"
    assert p.get("vitamin_a_rae_mcg") is None
    assert p.get("vitamin_a_iu") is not None
    assert float(p["vitamin_a_iu"]) > 0
    assert p.get("vitamin_d_source") == "converted_from_iu"
    assert p.get("vitamin_d_iu") is not None
    expected = round(float(p["vitamin_d_iu"]) / 40.0, 2)
    assert p.get("vitamin_d_mcg") == expected


@pytest.mark.live
def test_almond_crackers_folate_fallback_from_total(qdrant):
    p = _payload_for(qdrant, "1106101")
    assert p.get("folate_source") == "fallback_from_total"
    assert p.get("folate") is not None
    assert p.get("folate_dfe_mcg") == p.get("folate")


@pytest.mark.live
def test_hershey_vitamin_d_measured_mcg(qdrant):
    p = _payload_for(qdrant, "1847371")
    assert p.get("vitamin_d_source") == "measured_mcg"
    assert p.get("vitamin_d_mcg") is not None


@pytest.mark.live
def test_fndds_milk_vitamin_a_measured_rae(qdrant):
    p = _payload_for(qdrant, "2705385")
    assert p.get("vitamin_a_source") == "measured_rae"
    assert p.get("vitamin_a_rae_mcg") is not None


# ---------------------------------------------------------------------------
# FNDDS metadata + search hygiene
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_fndds_wweia_and_additional_description(qdrant):
    p = _payload_for(qdrant, "2705385")
    assert p.get("wweia_food_category") == "Milk, whole"
    assert p.get("wweia_category_number") in ("1002", 1002)
    addl = p.get("additional_description") or ""
    assert "leche fresca" in addl.lower()


@pytest.mark.live
def test_fndds_kefir_additional_description_multi_value(qdrant):
    p = _payload_for(qdrant, "2705394")
    assert p.get("wweia_food_category")
    addl = p.get("additional_description") or ""
    assert "fermented milk drink" in addl.lower()


@pytest.mark.live
def test_human_milk_record_absent_from_index(qdrant):
    """fdc 2705383 (Milk, human) was intentionally deleted from search."""
    pts, _ = qdrant.scroll(
        collection_name=COLLECTION,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="qdrant_id", match=models.MatchValue(value="2705383")
                )
            ]
        ),
        limit=5,
        with_payload=["qdrant_id", "description"],
        with_vectors=False,
    )
    assert pts == [], f"human milk should be absent, found: {pts}"


@pytest.mark.live
def test_allergen_fields_intact_on_nutrition_record(qdrant):
    """Nutrition backfill must not wipe allergen payload keys."""
    p = _payload_for(qdrant, "1847371")
    assert p.get("milk") in ("CONTAINS", "FREE", "UNKNOWN")
    assert "milk_may_contain" in p
