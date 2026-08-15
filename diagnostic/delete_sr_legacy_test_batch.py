"""
Delete the 50 test-mode SR Legacy points just embedded, so the upcoming
full run (which will reprocess these same first 50 rows) doesn't create
duplicates -- same class of bug already found and fixed in FNDDS.
Scoped specifically to these 50 fdc_ids, nothing else touched.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

missing_df = pd.read_csv("diagnostic/missing_sr_legacy_fdc_ids.csv")
test_batch_ids = [str(f) for f in missing_df["fdc_id"].head(50).tolist()]

filter_ = models.Filter(
    must=[
        models.FieldCondition(key="source", match=models.MatchValue(value="sr_legacy")),
        models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=test_batch_ids)),
    ]
)

count_result = client.count(collection_name=COLLECTION_NAME, count_filter=filter_)
print(f"Found {count_result.count} test-batch SR Legacy points to remove.")

confirm = input(f"\nType DELETE to permanently remove these {count_result.count} test points: ")
if confirm.strip() != "DELETE":
    print("Not confirmed -- no changes made.")
else:
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(filter=filter_),
    )
    print("Deleted.")

    verify = client.count(collection_name=COLLECTION_NAME, count_filter=filter_)
    print(f"Remaining: {verify.count} (should be 0)")
