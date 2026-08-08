"""
First end-to-end test of the allergen-safety pipeline built tonight (Aug 3-5).

Exercises the real chain: DietaryPreferences -> build_tier_1_filter -> Qdrant
search -> allergen severity logic -> Tier 2 boost -- using the actual
lookup_food() from nutrition_service.py, not a mock.

Does NOT touch MongoDB/UserProfile (would need your DB connection details) --
constructs dietary preferences directly in Python instead. This tests the
part that actually changed tonight: the Qdrant + dietary-filter chain, which
matters more right now than the (simpler, lower-risk) Mongo fetch step.

Four cases:
  1. No restrictions -- sanity baseline, confirm normal search still works
  2. Severe peanut allergy -- query something likely peanut-heavy, confirm
     either zero/blocked results or genuinely peanut-free results
  3. Moderate milk allergy -- confirm CONTAINS excluded, UNKNOWN passes through
  4. Vegan (non-allergen Tier 1) + organic (Tier 2) -- confirm hard filter +
     soft boost both apply
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import (
    DietaryPreferences, Tier1Preferences, Tier2Preferences, AllergyConstraint,
)
from backend.services.nutrition_service import lookup_food


def print_result(label: str, result: dict | None):
    print(f"\n{'='*80}\n{label}\n{'='*80}")
    if result is None:
        print("  No result (score below threshold or no matches).")
        return
    if result.get("blocked_by_allergy"):
        print(f"  BLOCKED BY ALLERGY: {result.get('message')}")
        return
    print(f"  food_name: {result.get('food_name')}")
    print(f"  brand: {result.get('brand')}")
    print(f"  calories: {result.get('calories')}")
    print(f"  used_dietary_fallback: {result.get('used_dietary_fallback')}")
    candidates = result.get("candidates", [])
    print(f"  candidates ({len(candidates)}):")
    for c in candidates[:5]:
        print(f"    - {c.get('name')} | {c.get('brand')} | source={c.get('source')}")


async def main():
    # Case 1: no restrictions -- baseline
    result1 = await lookup_food("chicken breast", dietary_preferences=None)
    print_result("CASE 1: No dietary restrictions -- 'chicken breast'", result1)

    # Case 2: severe peanut allergy, query likely to surface peanut products
    severe_peanut = DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={
                "peanut": AllergyConstraint(enabled=True, severity="severe"),
            }
        )
    )
    result2 = await lookup_food(
        "peanut butter cookies", dietary_preferences=severe_peanut
    )
    print_result(
        "CASE 2: SEVERE peanut allergy -- 'peanut butter cookies' "
        "(expect blocked, or genuinely peanut-free results)",
        result2,
    )

    # Case 3: moderate milk allergy, query something dairy-adjacent
    moderate_milk = DietaryPreferences(
        tier_1=Tier1Preferences(
            allergens={
                "milk": AllergyConstraint(enabled=True, severity="moderate"),
            }
        )
    )
    result3 = await lookup_food("yogurt", dietary_preferences=moderate_milk)
    print_result(
        "CASE 3: MODERATE milk allergy -- 'yogurt' "
        "(expect CONTAINS excluded, UNKNOWN allowed through)",
        result3,
    )

    # Case 4: vegan (non-allergen Tier 1) + organic preference (Tier 2)
    vegan_organic = DietaryPreferences(
        tier_1=Tier1Preferences(vegan=True),
        tier_2=Tier2Preferences(organic=True),
    )
    result4 = await lookup_food("milk", dietary_preferences=vegan_organic)
    print_result(
        "CASE 4: Vegan + organic preference -- 'milk' "
        "(expect vegan-only results, organic boosted toward top if present)",
        result4,
    )

    print(f"\n{'='*80}\nEnd-to-end test complete.\n{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
