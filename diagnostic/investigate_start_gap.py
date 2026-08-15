"""
Identify exactly which fdc_ids from the first 200 rows of branded_food.csv
are missing from Qdrant, and check a few things they might have in common:
- Are they contiguous (a block) or scattered?
- Does the source-of-truth food.csv (used for embedding) even contain them?
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
FOOD_CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv"
QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL)

df = pd.read_csv(CSV_PATH, usecols=["fdc_id"], low_memory=False, nrows=200)
fdc_ids = [str(f) for f in df["fdc_id"].tolist()]

result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=fdc_ids))]
    ),
    limit=len(fdc_ids),
    with_payload=["qdrant_id"],
)
found_ids = {p.payload["qdrant_id"] for p in result}
missing_ids = [f for f in fdc_ids if f not in found_ids]

print(f"Missing {len(missing_ids)} of {len(fdc_ids)} fdc_ids from Qdrant:")
print(missing_ids)

# Check if these are contiguous (a block) or scattered across the 200
positions = [fdc_ids.index(m) for m in missing_ids]
print(f"\nPositions within the 200-row sample: {positions}")
is_contiguous = positions == list(range(min(positions), max(positions) + 1)) if positions else False
print(f"Contiguous block? {is_contiguous}")

# Check if food.csv (the file the ORIGINAL embed script read from) even has these
try:
    food_df = pd.read_csv(FOOD_CSV_PATH, usecols=["fdc_id"], low_memory=False)
    food_fdc_ids = set(food_df["fdc_id"].astype(str))
    in_food_csv = [m for m in missing_ids if m in food_fdc_ids]
    print(f"\nOf the missing ids, {len(in_food_csv)}/{len(missing_ids)} DO exist in food.csv")
    print("(the file the original embedding script read from)")
except FileNotFoundError:
    print(f"\nfood.csv not found at expected path, skipping this check")
