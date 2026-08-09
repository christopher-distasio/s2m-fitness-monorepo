"""
Fix confirmed: embed_real_fndds.py was run twice (TEST_MODE then full),
creating a duplicate point for the same 50 fdc_ids each time, since uuid4()
generates a new random point ID on every run rather than a stable one.
5,482 total points, 5,432 distinct qdrant_id values, exactly 50 duplicated.

For each duplicated qdrant_id, keep one point, delete the rest. Requires
explicit confirmation before deleting, same as the earlier mislabeled-fndds
cleanup.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models
from collections import defaultdict

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

# Pull all fndds points with their internal point IDs
all_points = []
next_offset = None
while True:
    result, next_offset = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="source", match=models.MatchValue(value="fndds"))]
        ),
        limit=500,
        offset=next_offset,
        with_payload=["qdrant_id"],
    )
    all_points.extend((p.id, p.payload.get("qdrant_id")) for p in result)
    if next_offset is None:
        break

print(f"Total fndds points: {len(all_points):,}")

by_qdrant_id = defaultdict(list)
for point_id, qdrant_id in all_points:
    by_qdrant_id[qdrant_id].append(point_id)

to_delete = []
for qdrant_id, point_ids in by_qdrant_id.items():
    if len(point_ids) > 1:
        # Keep the first, mark the rest for deletion
        to_delete.extend(point_ids[1:])

print(f"Distinct qdrant_id values: {len(by_qdrant_id):,}")
print(f"Duplicate points to remove: {len(to_delete)}")
print(f"Expected remaining total after cleanup: {len(all_points) - len(to_delete):,}")

if not to_delete:
    print("No duplicates found -- nothing to do.")
else:
    confirm = input(f"\nType DELETE to permanently remove these {len(to_delete)} duplicate points: ")
    if confirm.strip() != "DELETE":
        print("Not confirmed -- no changes made.")
    else:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(points=to_delete),
        )
        print("Deleted.")

        # Verify
        verify_count = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value="fndds"))]
            ),
        )
        print(f"\nRemaining fndds points: {verify_count.count:,} (should be 5,432)")
