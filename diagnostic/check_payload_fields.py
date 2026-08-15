"""
Inspect exactly what fields exist in a real Qdrant payload record --
the E2E test showed food_name/calories as None/0.0 across every result,
suggesting the payload may be missing nutrition metadata entirely, not
just an allergen-filter issue.
"""
from qdrant_client import QdrantClient

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL)

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=3,
    with_payload=True,
)

for point in result:
    print(f"\n{'='*80}")
    print(f"Point ID: {point.id}")
    print(f"Payload keys: {sorted(point.payload.keys())}")
    print(f"Full payload:")
    for k, v in point.payload.items():
        v_str = str(v)[:100]
        print(f"  {k}: {v_str}")
