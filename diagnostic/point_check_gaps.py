"""
Tier-aware re-ranking logic -- Qdrant-native rewrite.

Replaces the earlier MongoDB/Pinecone-style {"$and": [...]} filter syntax
(invalid against Qdrant) with native qdrant_client.models.Filter objects.

Also incorporates the three-state allergen model built during the allergen
extraction work (CONTAINS / FREE / UNKNOWN + severity + may_contain), which
didn't exist when the original filter logic was first written.

Tier 1 (hard constraints):
  - Allergens (9 FDA majors): three-state + severity-aware filtering
  - Non-allergen hard constraints (vegan, gluten_free, kosher, etc.): simple
    match against modifier-name-as-value, same as extraction scripts store them

Tier 2 (soft preferences): multiplicative score boost, capped, applied
post-retrieval -- not part of the Qdrant filter at all.
"""

from qdrant_client.http import models
from typing import Optional


# ============================================================================
# ALLERGEN FIELDS (three-state, severity-aware)
# ============================================================================

FDA_ALLERGENS = [
    "milk", "egg", "fish", "shellfish", "tree_nut",
    "peanut", "wheat", "soy", "sesame",
]

# Non-allergen Tier 1 constraints -- stored as modifier-name-as-value
# (e.g. payload has {"vegan": "vegan"} when true, {"vegan": "NONE"} otherwise)
NON_ALLERGEN_TIER_1 = [
    "vegan", "vegetarian", "kosher", "halal", "gluten_free", "lactose_free",
]


def build_allergen_condition(allergen: str, severity: str) -> list:
    """
    Build the Qdrant FieldCondition(s) for one allergen at a given severity.

    Severe: must be FREE, and must_not have a may_contain flag set.
      (UNKNOWN is excluded -- can't verify, so treat as unsafe for severe allergies)
    Moderate: must_not be CONTAINS. UNKNOWN is allowed through (shown with a
      spoken caveat at the application layer, not filtered here).
      may_contain (cross-contamination) is ignored at moderate severity.

    Returns a list of conditions to be combined into the caller's must/must_not.
    """
    if severity == "severe":
        return {
            "must": [
                models.FieldCondition(key=allergen, match=models.MatchValue(value="FREE"))
            ],
            "must_not": [
                models.FieldCondition(key=f"{allergen}_may_contain", match=models.MatchValue(value=True))
            ],
        }
    else:  # moderate
        return {
            "must": [],
            "must_not": [
                models.FieldCondition(key=allergen, match=models.MatchValue(value="CONTAINS"))
            ],
        }


def build_non_allergen_condition(constraint_name: str) -> models.FieldCondition:
    """
    Non-allergen Tier 1 constraints (vegan, kosher, etc.) are stored as
    modifier-name-as-value, same convention as the extraction scripts.
    """
    return models.FieldCondition(key=constraint_name, match=models.MatchValue(value=constraint_name))


def build_tier_1_filter(
    enabled_allergens: dict,       # {"peanut": "severe", "milk": "moderate"}
    enabled_non_allergen: list,    # ["vegan", "gluten_free"]
) -> models.Filter:
    """
    Build the complete native Qdrant Filter for all Tier 1 hard constraints.

    Args:
        enabled_allergens: dict of allergen_name -> severity ("severe" | "moderate")
        enabled_non_allergen: list of enabled non-allergen Tier 1 constraint names

    Returns:
        A models.Filter ready to pass as query_filter / scroll_filter.

    Example:
        build_tier_1_filter(
            enabled_allergens={"peanut": "severe"},
            enabled_non_allergen=["vegan"],
        )
        -> Filter(
             must=[FieldCondition(peanut == FREE), FieldCondition(vegan == vegan)],
             must_not=[FieldCondition(peanut_may_contain == True)],
           )
    """
    must = []
    must_not = []

    for allergen, severity in enabled_allergens.items():
        conditions = build_allergen_condition(allergen, severity)
        must.extend(conditions["must"])
        must_not.extend(conditions["must_not"])

    for constraint in enabled_non_allergen:
        must.append(build_non_allergen_condition(constraint))

    return models.Filter(
        must=must if must else None,
        must_not=must_not if must_not else None,
    )


# ============================================================================
# TIER 2: SOFT BOOSTING (multiplicative, capped -- unchanged logic, applied
# post-retrieval, not part of the Qdrant filter)
# ============================================================================

def apply_tier_2_boosts(
    results: list,
    tier_2_preferences: dict,
    weight_per_match: float = 0.05,
    max_boost: float = 0.15,
) -> list:
    """
    Multiplicative boost per multi-AI review synthesis (2026-08-03):
    final_score = base_score * (1 + min(matches * weight_per_match, max_boost))

    Preserves semantic ranking as the primary signal -- an additive boost
    was flagged by two reviewers as capable of overwhelming embedding
    similarity entirely (e.g. an irrelevant-but-tagged-organic result
    outranking a highly relevant untagged one).
    """
    if not tier_2_preferences:
        return results

    for result in results:
        payload = result.get("payload", {})
        matches = sum(1 for pref in tier_2_preferences if payload.get(pref) == pref)
        boost_factor = min(matches * weight_per_match, max_boost)

        base_score = result.get("score", 0.0)
        result["final_score"] = base_score * (1.0 + boost_factor)

    results.sort(key=lambda x: x.get("final_score", x.get("score", 0.0)), reverse=True)
    return results


# ============================================================================
# FALLBACK LOGIC
#
# Per multi-AI review: allergens are NON_NEGOTIABLE and must never be
# auto-relaxed, regardless of severity. Only non-allergen Tier 1 constraints
# (vegan, kosher, etc.) may be relaxed, in priority order, quality-adjacent
# constraints dropped before ethical ones.
# ============================================================================

NON_ALLERGEN_FALLBACK_PRIORITY = [
    "kosher", "halal",       # religious -- drop first
    "vegan", "vegetarian",   # ethical
    "gluten_free",           # medical, but has FREE/UNKNOWN alternative path via allergen wheat field
    "lactose_free",          # medical
]


def relax_non_allergen_constraints(enabled_non_allergen: list) -> Optional[list]:
    """
    Drop one non-allergen Tier 1 constraint at a time, in fallback-priority
    order, for use when the primary search returns 0 results.

    Allergens are NEVER passed to this function -- they are excluded from
    all fallback relaxation. If the caller's enabled_allergens produced 0
    results, the correct response is to tell the user no safe options were
    found, not to relax the allergen filter.

    Returns None when nothing is left to relax.
    """
    if not enabled_non_allergen:
        return None

    relaxed = list(enabled_non_allergen)
    for constraint in NON_ALLERGEN_FALLBACK_PRIORITY:
        if constraint in relaxed:
            relaxed.remove(constraint)
            return relaxed

    return None


# ============================================================================
# EXAMPLE INTEGRATION
# ============================================================================

"""
async def lookup_food(
    food_query: str,
    user_id: str,
    query_modifiers: dict = None,
    top_k: int = 10,
) -> dict:

    user_prefs = await get_user_dietary_preferences(user_id)

    # Build allergen severity map from user's AllergyConstraint objects
    enabled_allergens = {
        name: constraint.severity
        for name, constraint in user_prefs.tier_1.allergens.items()
        if constraint.enabled
    }
    enabled_non_allergen = [
        name for name in NON_ALLERGEN_TIER_1
        if getattr(user_prefs.tier_1, name, False)
    ]

    tier_1_filter = build_tier_1_filter(enabled_allergens, enabled_non_allergen)

    embedded_query = openai_client.embeddings.create(
        model="text-embedding-3-large", input=food_query
    ).data[0].embedding

    results = qdrant_client.search(
        collection_name="food-vectors",
        query_vector=embedded_query,
        query_filter=tier_1_filter,
        limit=50,
    )

    if not results:
        if enabled_allergens:
            # NEVER relax allergens -- tell the user directly
            return {
                "results": [],
                "message": "I couldn't find any options matching your allergy requirements. "
                           "I've withheld unsafe options for your safety.",
            }
        relaxed_non_allergen = relax_non_allergen_constraints(enabled_non_allergen)
        if relaxed_non_allergen is not None:
            relaxed_filter = build_tier_1_filter(enabled_allergens, relaxed_non_allergen)
            results = qdrant_client.search(
                collection_name="food-vectors",
                query_vector=embedded_query,
                query_filter=relaxed_filter,
                limit=50,
            )
            for r in results:
                r["is_fallback"] = True

    tier_2_prefs = extract_tier_2_boosts(user_prefs.tier_2)
    results = apply_tier_2_boosts(results, tier_2_prefs)

    return {"results": results[:top_k]}
"""