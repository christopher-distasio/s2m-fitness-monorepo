"""
Verify the TEST_MODE run actually wrote allergen payloads by scrolling
the first 200 branded records and checking a few for the new fields.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

df = pd.read_csv(CSV_PATH, low_memory=False, usecols=["fdc_id", "ingredients"], nrows=200)
client = QdrantClient(url=QDRANT_URL)

checked = 0
found_with_allergen_data = 0

for _, row in df.iterrows():
    fdc_id = str(row["fdc_id"])
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchValue(value=fdc_id))]
        ),
        limit=1,
        with_payload=True,
    )
    checked += 1
    if result:
        payload = result[0].payload
        has_allergen_fields = "milk" in payload and "peanut_may_contain" in payload
        if has_allergen_fields:
            found_with_allergen_data += 1
        if checked <= 5:
            print(f"\nfdc_id {fdc_id}:")
            print(f"  ingredients: {row['ingredients'][:70] if pd.notna(row['ingredients']) else '(blank)'}")
            print(f"  milk={payload.get('milk')}, egg={payload.get('egg')}, "
                  f"peanut={payload.get('peanut')}, peanut_may_contain={payload.get('peanut_may_contain')}")
    else:
        print(f"fdc_id {fdc_id}: NO MATCHING POINT FOUND IN QDRANT")

print(f"\n\n{found_with_allergen_data} / {checked} checked records have allergen payload fields.")