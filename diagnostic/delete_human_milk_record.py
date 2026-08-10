"""
Remove fdc_id 2705383 ("Milk, human") from Qdrant.

This is legitimate USDA FNDDS reference data (national nutrition surveys
track infant feeding, including breastfeeding), but it has no place in
S2M's searchable food index -- an adult voice-logging their own food
intake has no legitimate reason to match this record, and the risk of a
"milk" query accidentally surfacing it is a real, avoidable problem for
a voice-first app.

Confirmed via direct search of food.csv: this is the only FNDDS record
with "human" in its description. One-off deletion, not a pattern --
no broader denylist needed for this dataset.

DELETES the point entirely (not a payload edit) -- this removes it from
search results and from getting any future nutrition backfill.
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
TARGET_FDC_ID = "2705383"

client = QdrantClient(url=QDRANT_URL, timeout=60)

# Resolve the real point ID first, so we can confirm what we're about to delete.
result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="qdrant_id", match=models.MatchValue(value=TARGET_FDC_ID))]
    ),
    limit=5,
    with_payload=True,
)

if not result:
    print(f"No point found for qdrant_id={TARGET_FDC_ID} -- nothing to delete.")
elif len(result) > 1:
    print(f"WARNING: found {len(result)} points for qdrant_id={TARGET_FDC_ID}, expected 1. Aborting -- investigate before deleting.")
else:
    point = result[0]
    print(f"Found: point_id={point.id}, description={point.payload.get('description')!r}, source={point.payload.get('source')}")
    confirm = input("Type DELETE to remove this point: ")
    if confirm == "DELETE":
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(points=[point.id]),
        )
        print("Deleted.")
    else:
        print("Not confirmed -- no changes made.")
