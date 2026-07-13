"""
Quick manual check: query nutrition_service.lookup_food() for a food name
and print the full result, so you can confirm serving_size_g scaling is
producing sensible numbers (not raw per-100g values) after the small-batch
test embed.

Usage:
    python3 lookup_test.py "some food name from your test batch"

If no argument is given, it prompts you for one interactively.

NOTE: adjust the import line below to match where nutrition_service.py
actually lives in your project (e.g. "from backend.services.nutrition_service
import lookup_food" if it's nested under backend/services/).
"""

import asyncio
import sys

from nutrition_service import lookup_food  # <-- adjust this import path if needed


async def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Food name to look up (pick one from branded_clean_test.json): ").strip()

    print(f"\nLooking up: {query!r}\n")
    result = await lookup_food(query)

    if result is None:
        print("No match found (either no results, or below the score threshold).")
        return

    print("Result:")
    for key, value in result.items():
        print(f"  {key}: {value}")

    print()
    print("Sanity check: does 'calories' look like a per-SERVING number")
    print("(reasonable for one package/serving), not a per-100g number?")
    print(f"  serving_size_g used: {result.get('serving_size_g')}")


if __name__ == "__main__":
    asyncio.run(main())