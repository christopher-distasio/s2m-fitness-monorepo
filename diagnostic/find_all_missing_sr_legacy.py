"""
SR Legacy is small enough (~7,793 records) to check exhaustively rather than
sample. Pull every real sr_legacy-labeled qdrant_id from Qdrant (paginated,
same technique as check_duplicate_fndds_points.py), compare against the full
set of fdc_ids in the source CSV, and get the complete, definitive missing
list -- likely part of the original ~7,700-record gap from the very first
embedding run, never precisely located until now.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

# Pull ALL sr_legacy qdrant_id values, fully paginated
print("Pulling all sr_legacy points from Qdrant (paginated)...")
real_ids = set()
next_offset = None
while True:
    result, next_offset = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="source", match=models.MatchValue(value="sr_legacy"))]
        ),
        limit=500,
        offset=next_offset,
        with_payload=["qdrant_id"],
    )
    real_ids.update(p.payload.get("qdrant_id") for p in result)
    if next_offset is None:
        break

print(f"Total sr_legacy points actually in Qdrant: {len(real_ids):,}")

df = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id", "description"], low_memory=False,
)
csv_ids = set(df["fdc_id"].astype(str))
print(f"Total fdc_ids in source CSV: {len(csv_ids):,}")

missing = csv_ids - real_ids
print(f"\nGenuinely missing (in CSV, not in Qdrant): {len(missing):,} ({100*len(missing)/len(csv_ids):.1f}%)")

# Save the full missing list for the re-embed step
missing_df = df[df["fdc_id"].astype(str).isin(missing)]
missing_df.to_csv("diagnostic/missing_sr_legacy_fdc_ids.csv", index=False)
print(f"Saved full missing list to diagnostic/missing_sr_legacy_fdc_ids.csv")

print(f"\nSample of missing records:")
for _, row in missing_df.head(10).iterrows():
    print(f"  fdc_id={row['fdc_id']}: {row['description']}")
