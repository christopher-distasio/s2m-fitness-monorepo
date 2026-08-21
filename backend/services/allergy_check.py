"""
Shared allergy block / warn helpers for food create and edit routes.

Severe allergen matches refuse the write (HTTP 403). Moderate matches allow
the write; callers should attach ``allergy_warning`` on the response.

The pure evaluation lives in ``restriction_eval.evaluate_restrictions``.
These helpers are thin adapters so existing route tests keep working.
"""

from __future__ import annotations

from backend.models import DietaryPreferences
from backend.services.restriction_eval import evaluate_restrictions


def check_allergy_block(
    food_item: dict,
    user_prefs: DietaryPreferences | None = None,
) -> tuple[bool, str | None]:
    """
    Returns (is_blocked, reason).

    Severe match -> block. Moderate match -> allow; caller should surface a
    warning via ``moderate_allergy_warnings``.
    """
    verdict = evaluate_restrictions(food_item, user_prefs)
    if verdict.verdict == "block":
        return True, (verdict.reasons[0] if verdict.reasons else "Blocked by dietary safety filter")
    return False, None


def moderate_allergy_warnings(
    food_item: dict,
    user_prefs: DietaryPreferences | None = None,
) -> list[str]:
    """Moderate-severity allergen hits: allow the write, but warn the caller.

    Copy stays report-only: states what the record shows, never that a food
    is safe.
    """
    verdict = evaluate_restrictions(food_item, user_prefs)
    if verdict.verdict == "block":
        return []
    return list(verdict.reasons)
