"""
Spot-check sample for the SR Legacy + FNDDS allergen extraction run.

Pulls:
  1. A handful of records with obvious expected allergens (milk, wheat, egg)
     to sanity-check the text-scan baseline is working.
  2. A random sample of records where any *_may_contain-adjacent GPT signal
     fired, i.e. records with at least one CONTAINS -- to eyeball whether
     the flags look reasonable against the food description.

Read-only -- no writes.
"""

import random
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

ALLERGENS = ["milk", "egg", "wheat", "soy", "peanut", "tree_nut", "fish", "shellfish", "sesame"]

OBVIOUS_TERMS = ["milk", "wheat", "flour", "egg", "cheese", "tofu", "soy"]


def print_record(point):
    desc = point.payload.get("description") or point.payload.get("qdrant_id")
    print(f"\n[{point.payload.get('qdrant_id')}] {desc}")
    contains = [a for a in ALLERGENS if point.payload.get(a) == "CONTAINS"]
    print(f"  CONTAINS: {contains if contains else 'none'}")


def main():
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    source_filter = models.FieldCondition(
        key="source", match=models.MatchAny(any=["sr_legacy", "fndds"])
    )

    print("=== Obvious-case check (description contains an allergen word) ===")
    for term in OBVIOUS_TERMS:
        result, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[
                    source_filter,
                    models.FieldCondition(key="description", match=models.MatchText(text=term)),
                ]
            ),
            limit=2,
            with_payload=True,
        )
        for point in result:
            print_record(point)

    print("\n\n=== Random sample of SR Legacy/FNDDS records with at least one CONTAINS flag ===")
    should_conditions = [
        models.FieldCondition(key=a, match=models.MatchValue(value="CONTAINS"))
        for a in ALLERGENS
    ]
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(must=[source_filter], should=should_conditions),
        limit=200,
        with_payload=True,
    )
    sample = random.sample(result, min(15, len(result)))
    for point in sample:
        print_record(point)


if __name__ == "__main__":
    main()