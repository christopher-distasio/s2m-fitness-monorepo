"""Spec 2 decision policy: (band × consequence_tier) → SILENT | CONFIRM | ASK.

Single lookup table. Spec 3/4 should extend this structure, not scatter
if/else through handlers. Every band × tier cell is explicit — none fall
through to a default.
"""

from __future__ import annotations

from typing import Literal

from backend.models.food_event import CONFIDENCE_FIELD_KEYS

Band = Literal["high", "medium", "low"]
ConsequenceTier = Literal["high", "medium", "low"]
PolicyAction = Literal["SILENT", "CONFIRM", "ASK"]

# Explicit per-field consequence. Do not infer at runtime.
CONSEQUENCE_TIER: dict[str, ConsequenceTier] = {
    "allergen_match": "high",
    "negation": "high",
    "food": "medium",
    "amount": "medium",
    "unit": "medium",
    "brand": "low",
    "variant": "low",
    "preparation": "low",
}

# (band, consequence_tier) → action. All 9 cells are required.
POLICY_TABLE: dict[tuple[Band, ConsequenceTier], PolicyAction] = {
    ("high", "high"): "SILENT",
    ("high", "medium"): "SILENT",
    ("high", "low"): "SILENT",
    ("medium", "high"): "ASK",
    ("medium", "medium"): "CONFIRM",
    ("medium", "low"): "SILENT",
    ("low", "high"): "ASK",
    ("low", "medium"): "ASK",
    ("low", "low"): "CONFIRM",
}

assert set(CONSEQUENCE_TIER) == set(CONFIDENCE_FIELD_KEYS)
assert len(POLICY_TABLE) == 9
assert set(POLICY_TABLE) == {
    (band, tier)
    for band in ("high", "medium", "low")
    for tier in ("high", "medium", "low")
}


def policy_action(band: Band, field: str) -> PolicyAction:
    """Look up the action for one field. Raises if the cell is missing."""
    tier = CONSEQUENCE_TIER[field]
    try:
        return POLICY_TABLE[(band, tier)]
    except KeyError as exc:
        raise KeyError(f"No policy for band={band!r} tier={tier!r} field={field}") from exc
