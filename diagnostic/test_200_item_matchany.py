"""
Every previous 'SR Legacy is clean' test used 50-100 combined ids -- never
enough to trigger QDRANT_BATCH_SIZE=200 mid-loop in the real script. This
is the first time a 200-item MatchAny batch has actually been sent. Testing
directly with a batch of 200 known-real SR Legacy ids (from a range already
confirmed present in earlier checks) to see if scale itself is the issue.
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

for test_size in [50, 100, 150, 200, 250]:
    sample_ids = [str(f) for f in df["fdc_id"].head(test_size).tolist()]
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
        ),
        limit=len(sample_ids),
        with_payload=["qdrant_id"],
    )
    found = len(result)
    print(f"Batch size {test_size}: {found}/{test_size} found ({100*found/test_size:.0f}%)")
