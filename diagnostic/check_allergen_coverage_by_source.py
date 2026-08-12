"""
Queue item 5: confirm whether allergen fields are missing from SR Legacy
and FNDDS entirely, not just absent from one lucky 2-record sample.

SR Legacy + FNDDS combined are only ~13k records (small enough to check
directly via a source filter, rather than relying on random sampling from
the full ~2.02M collection where they're only ~0.6%).
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

ALLERGEN_FIELDS = [
    "milk", "egg", "fish", "shellfish", "tree_nut",
    "peanut", "wheat", "soy", "sesame",
]

client = QdrantClient(url=QDRANT_URL)

for source_value in ["sr_legacy", "fndds", "branded_foods"]:
    print("=" * 90)
    print(f"SOURCE: {source_value}")
    print("=" * 90)

    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="source", match=models.MatchValue(value=source_value))]
        ),
        limit=500,
        with_payload=True,
    )

    print(f"Records retrieved for this source: {len(result)}")
    if not result:
        print("  (none found -- check the source value spelling)")
        continue

    for field in ALLERGEN_FIELDS:
        present = sum(1 for p in result if field in p.payload)
        pct = 100 * present / len(result)
        print(f"  {field:12} present on {present}/{len(result)} ({pct:.1f}%)")

    # Show one full example payload for this source
    print(f"\n  Example full payload keys: {sorted(result[0].payload.keys())}")
    print()
