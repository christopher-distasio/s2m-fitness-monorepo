"""
The 'fndds'-labeled records in Qdrant have descriptions written in SR
Legacy's style, not FNDDS's. Checking directly whether these qdrant_id
values actually belong to SR Legacy's food.csv instead.
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

real_qdrant_ids = [p.payload.get("qdrant_id") for p in result]
real_descriptions = {p.payload.get("qdrant_id"): p.payload.get("description") for p in result}

sr_legacy = pd.read_csv(
    "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    usecols=["fdc_id", "description"], low_memory=False,
)
sr_legacy_lookup = dict(zip(sr_legacy["fdc_id"].astype(str), sr_legacy["description"]))

print("Checking whether 'fndds'-labeled qdrant_ids actually belong to SR Legacy:\n")
matches = 0
for qid in real_qdrant_ids:
    if qid in sr_legacy_lookup:
        matches += 1
        sr_desc = sr_legacy_lookup[qid]
        qdrant_desc = real_descriptions[qid]
        exact_match = sr_desc.strip() == (qdrant_desc or "").strip()
        print(f"  qdrant_id={qid}: FOUND in SR Legacy")
        print(f"    SR Legacy description: {sr_desc}")
        print(f"    Qdrant 'fndds' description: {qdrant_desc}")
        print(f"    Descriptions match exactly: {exact_match}\n")
    else:
        print(f"  qdrant_id={qid}: not in SR Legacy either\n")

print(f"\n{matches}/{len(real_qdrant_ids)} 'fndds'-labeled records' IDs found in SR Legacy's food.csv")
