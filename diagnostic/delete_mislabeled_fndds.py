"""
Delete the mislabeled 'fndds' records in Qdrant -- confirmed to actually be
duplicate SR Legacy data (20/20 sample matched exactly). Counts first,
requires explicit confirmation before deleting, since this is destructive.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

filter_ = models.Filter(
    must=[models.FieldCondition(key="source", match=models.MatchValue(value="fndds"))]
)

# Count first
count_result = client.count(collection_name=COLLECTION_NAME, count_filter=filter_)
print(f"Found {count_result.count:,} records labeled source='fndds' (confirmed mislabeled).")

confirm = input(f"\nType DELETE to permanently remove these {count_result.count:,} records: ")
if confirm.strip() != "DELETE":
    print("Not confirmed -- no changes made.")
else:
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(filter=filter_),
    )
    print("Deleted.")

    # Verify
    verify = client.count(collection_name=COLLECTION_NAME, count_filter=filter_)
    print(f"Records remaining with source='fndds': {verify.count:,} (should be 0)")
