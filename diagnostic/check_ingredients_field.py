"""
Queue item 3: confirm whether 'ingredients' is actually present in the
Qdrant payload. The allergen extraction pipeline already depends on reading
this text from the source CSV -- this check confirms whether the raw text
itself made it into Qdrant, or only the allergen flags DERIVED from it.
"""
from qdrant_client import QdrantClient

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 200

client = QdrantClient(url=QDRANT_URL)

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=SAMPLE_SIZE,
    with_payload=True,
)

has_ingredients = sum(1 for p in result if "ingredients" in p.payload)
print(f"Sample size: {len(result)}")
print(f"Records with 'ingredients' field present: {has_ingredients} ({100*has_ingredients/len(result):.1f}%)")

if has_ingredients > 0:
    example = next(p for p in result if "ingredients" in p.payload)
    print(f"\nExample value: {str(example.payload['ingredients'])[:150]}")
else:
    print("\n'ingredients' field is NOT present in the sampled payload.")
    print("The allergen system reads this from the source CSV at extraction time,")
    print("but the raw text itself was never carried into Qdrant's payload.")
