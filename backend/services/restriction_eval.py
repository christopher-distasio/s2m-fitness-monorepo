"""Pure restriction / allergen evaluation (Spec 1 hard rule 14).

Decoupled from logging: POST/PATCH is one caller among several. Barcode
scan-to-verdict and voice allergen queries must be able to call this without
writing a food log.

Report, never assert safety — reasons state what the record shows, never
that a food "is safe."
"""

from __future__ import annotations

from typing import Any

from backend.models import DietaryPreferences, UserProfile
from backend.models.food_event import (
    RestrictionHit,
    RestrictionVerdict,
)
from backend.services.dietary_filters import FDA_ALLERGENS, NON_ALLERGEN_TIER_1

# Hard rule 4: advisory / facility language is UNKNOWN, never free, never contains.
# "May contain X" / "made in a facility with X" → unknown.
ADVISORY_LANGUAGE_MAPS_TO: str = "unknown"


def _normalize_state(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"contains", "free", "unknown"}:
        return text
    return None


def _allergen_states(food_record: Any) -> dict[str, str]:
    if food_record is None:
        return {}
    data = food_record if isinstance(food_record, dict) else food_record.model_dump()
    states: dict[str, str] = {}

    nested = data.get("allergen_state") or {}
    if isinstance(nested, dict):
        for name, value in nested.items():
            normalized = _normalize_state(value)
            if normalized:
                states[str(name)] = normalized

    for name in FDA_ALLERGENS:
        if name in states:
            continue
        normalized = _normalize_state(data.get(name))
        if normalized:
            states[name] = normalized

    listed = data.get("allergens")
    if isinstance(listed, list):
        for name in listed:
            states.setdefault(str(name), "contains")
    return states


def _restriction_tags(food_record: Any) -> dict[str, str]:
    if food_record is None:
        return {}
    data = food_record if isinstance(food_record, dict) else food_record.model_dump()
    tags = data.get("restriction_tags") or {}
    return dict(tags) if isinstance(tags, dict) else {}


def _evidence(food_record: Any, key: str) -> str:
    if food_record is None:
        return "not_assessed"
    data = food_record if isinstance(food_record, dict) else food_record.model_dump()
    basis = (data.get("evidence_basis") or {}).get(key)
    if basis in {
        "declared_ingredient",
        "advisory_label_present",
        "certified",
        "not_assessed",
    }:
        return basis
    state = _allergen_states(food_record).get(key)
    if state == "unknown":
        return "advisory_label_present" if basis == "advisory_label_present" else "not_assessed"
    if state == "contains":
        return "declared_ingredient"
    return "not_assessed"


def _prefs_from_profile(user_profile: Any) -> DietaryPreferences | None:
    if user_profile is None:
        return None
    if isinstance(user_profile, DietaryPreferences):
        return user_profile
    if isinstance(user_profile, UserProfile):
        return user_profile.dietary_preferences
    if isinstance(user_profile, dict):
        nested = user_profile.get("dietary_preferences")
        if isinstance(nested, DietaryPreferences):
            return nested
        if nested:
            return DietaryPreferences.model_validate(nested)
        try:
            return DietaryPreferences.model_validate(user_profile)
        except Exception:
            return None
    return getattr(user_profile, "dietary_preferences", None)


def evaluate_restrictions(
    food_record: Any,
    user_profile: Any = None,
) -> RestrictionVerdict:
    """Return allowed / warn / block plus which tags fired.

    Does not write logs. Does not call an LLM.
    """
    data = food_record if isinstance(food_record, dict) else (
        food_record.model_dump() if food_record is not None else {}
    )
    if data.get("confidence") == "blocked" or data.get("blocked_by_allergy"):
        reason = (
            data.get("reasoning")
            or data.get("message")
            or "No matching options under the current allergen filter"
        )
        return RestrictionVerdict(
            verdict="block",
            hits=[],
            reasons=[reason],
        )

    prefs = _prefs_from_profile(user_profile)
    if prefs is None:
        return RestrictionVerdict(verdict="allowed")

    hits: list[RestrictionHit] = []
    block_reasons: list[str] = []
    warn_reasons: list[str] = []

    states = _allergen_states(food_record)
    for allergen, state in states.items():
        constraint = prefs.tier_1.allergens.get(allergen)
        if constraint is None or not constraint.enabled:
            continue
        evidence = _evidence(food_record, allergen)
        if state == "contains" and constraint.severity == "severe":
            hits.append(
                RestrictionHit(
                    tag=allergen,
                    state=state,
                    evidence_basis=evidence,
                    severity="severe",
                    kind="allergen",
                )
            )
            block_reasons.append(f"Contains {allergen} (severe)")
        elif state == "contains" and constraint.severity == "moderate":
            hits.append(
                RestrictionHit(
                    tag=allergen,
                    state=state,
                    evidence_basis=evidence,
                    severity="moderate",
                    kind="allergen",
                )
            )
            warn_reasons.append(f"Contains {allergen} (moderate)")
        elif state == "unknown" and constraint.severity == "moderate":
            hits.append(
                RestrictionHit(
                    tag=allergen,
                    state=state,
                    evidence_basis=evidence,
                    severity="moderate",
                    kind="allergen",
                )
            )
            warn_reasons.append(f"Contains {allergen} (moderate)")

    tags = _restriction_tags(food_record)
    for name in NON_ALLERGEN_TIER_1:
        if not getattr(prefs.tier_1, name, False):
            continue
        state = str(tags.get(name) or "").lower()
        if state in {"contains", "incompatible", "not_met"}:
            hits.append(
                RestrictionHit(
                    tag=name,
                    state=state,
                    evidence_basis=_evidence(food_record, name),
                    kind="restriction",
                )
            )
            block_reasons.append(f"Record is incompatible with {name.replace('_', ' ')}")

    if block_reasons:
        return RestrictionVerdict(verdict="block", hits=hits, reasons=block_reasons)
    if warn_reasons:
        return RestrictionVerdict(verdict="warn", hits=hits, reasons=warn_reasons)
    return RestrictionVerdict(verdict="allowed", hits=hits, reasons=[])
