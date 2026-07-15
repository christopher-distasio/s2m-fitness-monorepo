"""
Broader verification of the singular/plural retrieval mismatch found with
"banana" vs "bananas". Checks a few more plural-typical foods to confirm
the pattern generalizes before building a fix around it.

Usage:
    poetry run python3 verify_plural_generalization.py
"""

import asyncio

from nutrition_service import openai_client, index, EMBEDDING_MODEL

# (singular query, plural query, what we expect the canonical SR Legacy
# name to look like) — picked foods where SR Legacy likely stores the
# plural form, same pattern as "Bananas, raw"
TEST_PAIRS = [
    ("egg", "eggs"),
    ("grape", "grapes"),
    ("strawberry", "strawberries"),
    ("carrot", "carrots"),
    ("almond", "almonds"),
]


async def get_top_match(query: str):
    response = await openai_client.embeddings.create(model=EMBEDDING_MODEL, input=query)
    vector = response.data[0].embedding
    results = index.query(vector=vector, top_k=5, include_metadata=True)
    if not results["matches"]:
        return None, None
    top = results["matches"][0]
    return top["score"], top["metadata"].get("name")


async def main():
    print("Checking singular vs plural query for several foods...\n")
    for singular, plural in TEST_PAIRS:
        sing_score, sing_name = await get_top_match(singular)
        plur_score, plur_name = await get_top_match(plural)

        print(f"'{singular}' vs '{plural}':")
        print(f"  singular query -> score={sing_score:.4f}  top='{sing_name}'")
        print(f"  plural query   -> score={plur_score:.4f}  top='{plur_name}'")
        diff = plur_score - sing_score
        direction = "PLURAL WINS" if diff > 0.01 else ("SINGULAR WINS" if diff < -0.01 else "ROUGHLY TIED")
        print(f"  -> {direction} (diff: {diff:+.4f})")
        print()


if __name__ == "__main__":
    asyncio.run(main())