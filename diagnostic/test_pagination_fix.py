"""
Testing whether proper pagination (looping with next_offset until exhausted,
same pattern already used correctly in check_duplicate_fndds_points.py)
recovers the results that a single unpaginated scroll() call was missing.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

df = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id"], low_memory=False,
)
sample_ids = [str(f) for f in df["fdc_id"].head(200).tolist()]

print("--- Single unpaginated call (the current, buggy behavior) ---")
result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
    ),
    limit=len(sample_ids),
    with_payload=["qdrant_id"],
)
print(f"Found: {len(result)}/200")

print("\n--- Paginated (looping until exhausted) ---")
all_found = []
next_offset = None
while True:
    page, next_offset = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
        ),
        limit=len(sample_ids),
        offset=next_offset,
        with_payload=["qdrant_id"],
    )
    all_found.extend(page)
    print(f"  page returned {len(page)}, next_offset={next_offset}")
    if next_offset is None:
        break

print(f"\nTotal found via pagination: {len(all_found)}/200")
