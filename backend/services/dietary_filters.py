"""
Dietary preference / allergen filtering for food search.

Builds Qdrant filters from a user's DietaryPreferences (backend.models) and
applies Tier 2 soft-preference boosts post-retrieval.

Design (validated via multi-AI review + real-data extraction, 2026-08-04):
  - Tier 1 allergens: three-state (CONTAINS/FREE/UNKNOWN), severity-aware.
    severe   -> must be FREE, must not have a may_contain flag. UNKNOWN is
                excluded (can't verify -> treat as unsafe).
    moderate -> must not be CONTAINS. UNKNOWN passes through (caveat at the
                voice/UI layer, not filtered here).
  - Tier 1 non-allergen (vegan, kosher, gluten_free, etc.): simple hard match
    against modifier-name-as-value, same convention as the 13 query modifiers.
  - Allergens are NEVER auto-relaxed on zero results. Non-allergen Tier 1
    constraints may be relaxed, one at a time, in priority order.
  - Tier 2 preferences never filter -- they only boost ranking, multiplicative
    and capped, applied after retrieval.
"""

from qdrant_client.http import models as qmodels
from backend.models import DietaryPreferences, Tier1Preferences, Tier2Preferences

FDA_ALLERGENS = [
    "milk", "egg", "fish", "shellfish", "tree_nut",
    "peanut", "wheat", "soy", "sesame",
]

NON_ALLERGEN_TIER_1 = [
    "gluten_free", "lactose_free", "vegan", "vegetarian", "kosher", "halal",
]

# Drop order when a non-allergen Tier 1 constraint needs to be relaxed after
# a zero-result search. Religious/ethical drop before medical; allergens are
# not in this list at all -- they are structurally excluded from relaxation.
NON_ALLERGEN_FALLBACK_PRIORITY = [
    "kosher", "halal",
    "vegan", "vegetarian",
    "gluten_free",
    "lactose_free",
]


def build_tier_1_filter(tier_1: Tier1Preferences | None) -> qmodels.Filter | None:
    """
    Build the complete Qdrant hard-constraint filter from a user's Tier 1
    preferences. Returns None when nothing is enabled (unrestricted search).
    """
    if tier_1 is None:
        return None

    must: list = []
    must_not: list = []

    for allergen_name, constraint in tier_1.allergens.items():
        if not constraint.enabled:
            continue
        if constraint.severity == "severe":
            must.append(
                qmodels.FieldCondition(key=allergen_name, match=qmodels.MatchValue(value="FREE"))
            )
            must_not.append(
                qmodels.FieldCondition(
                    key=f"{allergen_name}_may_contain", match=qmodels.MatchValue(value=True)
                )
            )
        else:  # moderate
            must_not.append(
                qmodels.FieldCondition(key=allergen_name, match=qmodels.MatchValue(value="CONTAINS"))
            )

    for constraint_name in NON_ALLERGEN_TIER_1:
        if getattr(tier_1, constraint_name, False):
            must.append(
                qmodels.FieldCondition(key=constraint_name, match=qmodels.MatchValue(value=constraint_name))
            )

    if not must and not must_not:
        return None

    return qmodels.Filter(
        must=must if must else None,
        must_not=must_not if must_not else None,
    )


def has_active_allergen_constraint(tier_1: Tier1Preferences | None) -> bool:
    """True if any allergen is enabled -- used to decide whether a zero-result
    search is allowed to fall back (never, if an allergen is active) or not."""
    if tier_1 is None:
        return False
    return any(c.enabled for c in tier_1.allergens.values())


def relax_non_allergen_constraints(tier_1: Tier1Preferences) -> Tier1Preferences | None:
    """
    Return a COPY of tier_1 with one non-allergen constraint dropped, in
    fallback-priority order. Allergen settings are untouched -- this function
    only ever modifies the non-allergen booleans. Returns None when nothing
    is left to relax.

    Caller is responsible for checking has_active_allergen_constraint() first
    and refusing to call this at all if an allergen is active with zero
    results -- that case should never reach fallback.
    """
    relaxed = tier_1.model_copy(deep=True)
    for constraint_name in NON_ALLERGEN_FALLBACK_PRIORITY:
        if getattr(relaxed, constraint_name, False):
            setattr(relaxed, constraint_name, False)
            return relaxed
    return None


def apply_tier_2_boosts(
    matches: list[dict],
    tier_2: Tier2Preferences | None,
    weight_per_match: float = 0.05,
    max_boost: float = 0.15,
) -> list[dict]:
    """
    Multiplicative, capped re-rank by Tier 2 soft preferences. Operates on
    the {id, score, metadata} dict shape already used throughout
    nutrition_service.py -- not Qdrant's raw ScoredPoint objects.

    final_score = score * (1 + min(matches_count * weight_per_match, max_boost))

    Multiplicative (not additive) so semantic relevance stays the primary
    signal -- an additive boost was flagged in review as capable of ranking
    an irrelevant-but-tagged-organic result above a highly relevant one.
    """
    if tier_2 is None:
        return matches

    enabled_prefs = [
        name for name in Tier2Preferences.model_fields.keys()
        if getattr(tier_2, name, False)
    ]
    if not enabled_prefs:
        return matches

    for m in matches:
        metadata = m.get("metadata", {})
        hit_count = sum(1 for pref in enabled_prefs if metadata.get(pref) == pref)
        boost_factor = min(hit_count * weight_per_match, max_boost)
        m["final_score"] = m.get("score", 0.0) * (1.0 + boost_factor)

    matches.sort(key=lambda m: m.get("final_score", m.get("score", 0.0)), reverse=True)
    return matches
