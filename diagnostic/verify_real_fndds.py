"""
Spot-check the newly (correctly) embedded FNDDS test records -- confirm
they're real, distinct FNDDS content, not another SR Legacy duplicate.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchValue(value="fndds"))]
    ),
    limit=20,
    with_payload=True,
)

print(f"Pulled {len(result)} records now labeled source='fndds'.\n")

sr_legacy = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id", "description"], low_memory=False,
)
sr_legacy_lookup = dict(zip(sr_legacy["fdc_id"].astype(str), sr_legacy["description"]))

print("Checking whether these match SR Legacy (should be NO this time):\n")
matches = 0
for p in result:
    qid = p.payload.get("qdrant_id")
    desc = p.payload.get("description")
    in_sr_legacy = qid in sr_legacy_lookup
    if in_sr_legacy:
        matches += 1
    print(f"  qdrant_id={qid}: {desc}")
    print(f"    Found in SR Legacy: {in_sr_legacy}\n")

print(f"\n{matches}/{len(result)} match SR Legacy (should be 0 this time)")
