"""
The real extraction script combines SR Legacy + FNDDS ids into ONE MatchAny
filter (100 mixed ids) at the final flush step, under TEST_MODE. Standalone
checks always queried each dataset separately. Testing directly whether
combining them into one mixed batch is what's causing the discrepancy.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

sr_legacy = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id"], low_memory=False,
).head(50)
fndds = pd.read_csv(
    "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
    usecols=["fdc_id"], low_memory=False,
).head(50)

sr_ids = [str(f) for f in sr_legacy["fdc_id"].tolist()]
fndds_ids = [str(f) for f in fndds["fdc_id"].tolist()]

# Check for any overlapping fdc_id strings between the two datasets --
# would explain a collision if the combined dict overwrites one with another
overlap = set(sr_ids) & set(fndds_ids)
print(f"Overlapping fdc_id values between SR Legacy and FNDDS samples: {overlap if overlap else 'none'}\n")

def check(label, ids):
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=ids))]
        ),
        limit=len(ids),
        with_payload=["qdrant_id"],
    )
    found = len(result)
    print(f"{label}: {found}/{len(ids)} found")
    return result

print("--- Separate queries (matches the standalone check scripts) ---")
sr_result = check("SR Legacy alone", sr_ids)
fndds_result = check("FNDDS alone", fndds_ids)

print("\n--- Combined query (matches what the real extraction script does under TEST_MODE) ---")
combined_ids = sr_ids + fndds_ids
combined_result = check("SR Legacy + FNDDS combined", combined_ids)

print(f"\nSeparate total found: {len(sr_result) + len(fndds_result)}/100")
print(f"Combined total found: {len(combined_result)}/100")
