"""
Shared allergy block / warn helpers for food create and edit routes.

Severe allergen matches refuse the write (HTTP 403). Moderate matches allow
the write; callers should attach ``allergy_warning`` on the response.
"""

from __future__ import annotations

from backend.models import DietaryPreferences
from backend.services.dietary_filters import FDA_ALLERGENS


def _present_allergens(food_item: dict) -> list[str]:
    """Allergens known to be present on a food / parse payload."""
    allergens = food_item.get("allergens")
    if isinstance(allergens, list) and allergens:
        return [str(a) for a in allergens]

    present: list[str] = []
    for name in FDA_ALLERGENS:
        if food_item.get(name) == "CONTAINS":
            present.append(name)
    return present


def _enabled_constraint(user_prefs: DietaryPreferences, allergen: str):
    constraint = user_prefs.tier_1.allergens.get(allergen)
    if constraint is None or not constraint.enabled:
        return None
    return constraint


def check_allergy_block(
    food_item: dict,
    user_prefs: DietaryPreferences | None = None,
) -> tuple[bool, str | None]:
    """
    Returns (is_blocked, reason).

    Severe match -> block. Moderate match -> allow; caller should surface a
    warning via ``moderate_allergy_warnings``.

    Also honors the lookup/parse refusal shape already used by POST /food:
    ``confidence == "blocked"`` / ``blocked_by_allergy`` (zero safe Qdrant
    hits under a severe allergen filter).
    """
    if food_item.get("confidence") == "blocked" or food_item.get("blocked_by_allergy"):
        return True, (
            food_item.get("reasoning")
            or food_item.get("message")
            or "Blocked by dietary safety filter"
        )

    if user_prefs is None:
        return False, None

    for allergen in _present_allergens(food_item):
        constraint = _enabled_constraint(user_prefs, allergen)
        if constraint is not None and constraint.severity == "severe":
            return True, f"Contains {allergen} (severe)"
    return False, None


def moderate_allergy_warnings(
    food_item: dict,
    user_prefs: DietaryPreferences | None = None,
) -> list[str]:
    """Moderate-severity allergen hits: allow the write, but warn the caller.

    Warns on explicit CONTAINS / allergens-list hits, and on UNKNOWN state
    (the application-layer caveat for moderate filters that let UNKNOWN pass).
    """
    if user_prefs is None:
        return []

    flagged = set(_present_allergens(food_item))
    for name in FDA_ALLERGENS:
        if food_item.get(name) == "UNKNOWN":
            flagged.add(name)

    warnings: list[str] = []
    for allergen in flagged:
        constraint = _enabled_constraint(user_prefs, allergen)
        if constraint is not None and constraint.severity == "moderate":
            warnings.append(f"Contains {allergen} (moderate)")
    return warnings
