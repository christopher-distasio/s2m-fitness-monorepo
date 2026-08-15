"""
FNDDS records exist in Qdrant (confirmed via source filter) but querying by
qdrant_id using fdc_id values from food.csv finds NONE of them, at any
position in the file. This pulls real FNDDS records directly by source
filter, shows their actual qdrant_id values, and checks whether those values
match fdc_id in food.csv, food_code in survey_fndds_food.csv, or neither --
to find out what ID scheme was actually used at embed time.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

# Pull real FNDDS records directly, no ID guessing involved
result, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchValue(value="fndds"))]
    ),
    limit=20,
    with_payload=True,
)

print(f"Pulled {len(result)} real FNDDS records directly from Qdrant.\n")
real_qdrant_ids = [p.payload.get("qdrant_id") for p in result]
print("Their actual qdrant_id values:")
for qid in real_qdrant_ids:
    print(f"  {qid}")

# Now check these against food.csv's fdc_id column
food_csv = pd.read_csv(
    "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
    usecols=["fdc_id", "description"], low_memory=False,
)
food_csv_ids = set(food_csv["fdc_id"].astype(str))

print(f"\nDo these qdrant_ids appear in food.csv's fdc_id column?")
for qid in real_qdrant_ids:
    match = qid in food_csv_ids
    print(f"  {qid}: {'YES -- found in food.csv' if match else 'NOT FOUND in food.csv'}")

# Also check survey_fndds_food.csv's food_code, in case that's the real key
try:
    survey_csv = pd.read_csv(
        "data/raw/FoodData_Central_survey_food_csv_2024-10-31/survey_fndds_food.csv",
        low_memory=False,
    )
    print(f"\nsurvey_fndds_food.csv columns: {list(survey_csv.columns)}")
    if "food_code" in survey_csv.columns:
        food_codes = set(survey_csv["food_code"].astype(str))
        print(f"\nDo these qdrant_ids appear in survey_fndds_food.csv's food_code column?")
        for qid in real_qdrant_ids:
            match = qid in food_codes
            print(f"  {qid}: {'YES -- found in food_code' if match else 'not found'}")
    if "fdc_id" in survey_csv.columns:
        survey_fdc_ids = set(survey_csv["fdc_id"].astype(str))
        print(f"\nDo these qdrant_ids appear in survey_fndds_food.csv's fdc_id column?")
        for qid in real_qdrant_ids:
            match = qid in survey_fdc_ids
            print(f"  {qid}: {'YES' if match else 'not found'}")
except FileNotFoundError:
    print("\nsurvey_fndds_food.csv not found at expected path")

# Show the actual descriptions from Qdrant for these records too, might help
# spot the pattern by eye
print(f"\nDescriptions of these real Qdrant FNDDS records (for context):")
for p in result[:10]:
    print(f"  qdrant_id={p.payload.get('qdrant_id')}: {p.payload.get('description')}")
