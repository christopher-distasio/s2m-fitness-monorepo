"""
Verify what values are actually stored in the 'source' payload field in
Qdrant, rather than trusting memory of the embedding script. Directly
affects whether SOURCE_GROUPS in nutrition_service.py will match anything.
"""
from qdrant_client import QdrantClient

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL)

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=20,
    with_payload=["source", "qdrant_id"],
)

print("Sample 'source' values actually in Qdrant:\n")
seen_sources = set()
for point in result:
    src = point.payload.get("source")
    seen_sources.add(src)
    print(f"  qdrant_id={point.payload.get('qdrant_id')}, source={src!r}")

print(f"\nDistinct source values seen in this sample: {seen_sources}")
