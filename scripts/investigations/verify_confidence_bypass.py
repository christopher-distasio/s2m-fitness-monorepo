"""
Verify: does "banana" (and similar simple, single-word foods) reliably get
classified as "high" confidence by the parser, which causes it to auto-log
immediately and skip the candidates/portion_options disambiguation UI
entirely, regardless of whether the RAG match underneath is actually good?

Run several times since temperature=0.2 isn't fully deterministic.

Usage:
    poetry run python3 verify_confidence_bypass.py
"""

import asyncio

from backend.services.food_parser import parse_food_input

TEST_INPUTS = ["banana", "a banana", "milk", "chicken", "an egg"]
RUNS_PER_INPUT = 5


async def main():
    for food_input in TEST_INPUTS:
        print(f"\nInput: {food_input!r} (running {RUNS_PER_INPUT}x)")
        confidences = []
        for _ in range(RUNS_PER_INPUT):
            result = await parse_food_input(food_input)
            conf = result.get("confidence")
            confidences.append(conf)
            has_candidates = bool(result.get("candidates"))
            print(f"  confidence={conf!r}  candidates_present={has_candidates}  calories={result.get('calories')}")

        high_count = confidences.count("high")
        print(f"  -> {high_count}/{RUNS_PER_INPUT} runs returned 'high' (bypasses disambiguation UI)")


if __name__ == "__main__":
    asyncio.run(main())