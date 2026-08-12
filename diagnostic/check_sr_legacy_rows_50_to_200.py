"""
Every previous SR Legacy check used independent 50-record samples, never
a continuous range beyond row 50. Checking specifically rows 50-200
(the exact slice never directly tested before) to see if this is simply
a real, previously-unexamined gap rather than a new bug class.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

df = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id"], low_memory=False,
)

# Check in clean 50-record chunks across rows 0-200, to see exactly where
# the gap starts
for chunk_start in [0, 50, 100, 150]:
    chunk_ids = [str(f) for f in df["fdc_id"].iloc[chunk_start:chunk_start+50].tolist()]
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=chunk_ids))]
        ),
        limit=50,
        with_payload=["qdrant_id"],
    )
    found = len(result)
    print(f"Rows {chunk_start}-{chunk_start+50}: {found}/50 found")
