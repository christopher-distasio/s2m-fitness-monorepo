"""
Before assuming the 7,743 'missing' SR Legacy records need a fresh embed --
check whether they're actually sitting somewhere in the collection already,
under a WRONG source label (same class of bug already found in FNDDS).
Searches for a sample of missing fdc_ids with NO source filter at all,
across the whole ~2M+ collection.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

missing_df = pd.read_csv("diagnostic/missing_sr_legacy_fdc_ids.csv")
sample_ids = [str(f) for f in missing_df["fdc_id"].head(30).tolist()]

print(f"Checking {len(sample_ids)} 'missing' SR Legacy fdc_ids -- searching the WHOLE "
      f"collection, no source filter, to see if they exist under a different label.\n")

# No source filter at all -- just qdrant_id
result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
    ),
    limit=len(sample_ids),
    with_payload=["qdrant_id", "source", "description"],
)

print(f"Found {len(result)}/{len(sample_ids)} of these fdc_ids SOMEWHERE in the collection.\n")

if result:
    print("Where they're actually labeled:")
    for p in result:
        print(f"  qdrant_id={p.payload.get('qdrant_id')}  source={p.payload.get('source')}  "
              f"description={p.payload.get('description')}")
else:
    print("None of these fdc_ids exist ANYWHERE in the collection, under any label.")
    print("This means they were genuinely never embedded at all -- a real re-embed is needed,")
    print("not a relabeling fix.")
