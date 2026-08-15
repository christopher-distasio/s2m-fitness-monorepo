"""
Theory: embed_real_fndds.py was run twice (TEST_MODE, then full run), and
since it uses uuid4() for point IDs (not deterministic), the first 50
records may now have TWO points each sharing the same qdrant_id -- which
would explain resolve_point_ids()'s limit-based cutoff silently dropping
some genuinely-present records. Checking directly for duplicates.
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models
from collections import Counter

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

# Pull ALL fndds-labeled points (only ~5,432 -- small enough to fully scan)
all_qdrant_ids = []
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
    all_qdrant_ids.extend(p.payload.get("qdrant_id") for p in result)
    if next_offset is None:
        break

print(f"Total points labeled source='fndds': {len(all_qdrant_ids):,}")

counts = Counter(all_qdrant_ids)
duplicates = {qid: count for qid, count in counts.items() if count > 1}

print(f"Distinct qdrant_id values: {len(counts):,}")
print(f"qdrant_id values with MORE than one point: {len(duplicates)}")

if duplicates:
    print(f"\nSample duplicates (first 20):")
    for qid, count in list(duplicates.items())[:20]:
        print(f"  qdrant_id={qid}: {count} points")
