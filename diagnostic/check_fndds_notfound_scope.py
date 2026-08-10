"""
14/50 missing in FNDDS's first 50 records, scattered not contiguous. Before
assuming this is scattered-write-hiccup (like the original Branded Foods
gap) rather than something systematic, check scope across the whole real
FNDDS dataset -- same 5-position sampling used for Branded Foods earlier.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 100

client = QdrantClient(url=QDRANT_URL, timeout=60)

df = pd.read_csv(
    "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
    usecols=["fdc_id"], low_memory=False,
)
total_rows = len(df)
print(f"Total FNDDS rows: {total_rows:,}\n")

positions = {
    "start (0)": 0,
    "25%": total_rows // 4,
    "middle (50%)": total_rows // 2,
    "75%": (total_rows * 3) // 4,
    "near end": max(0, total_rows - SAMPLE_SIZE - 5),
}

overall_missing = 0
overall_checked = 0

for label, offset in positions.items():
    sample_ids = df["fdc_id"].iloc[offset:offset + SAMPLE_SIZE].astype(str).tolist()
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
        ),
        limit=len(sample_ids),
        with_payload=["qdrant_id"],
    )
    found = len(result)
    missing = len(sample_ids) - found
    overall_missing += missing
    overall_checked += len(sample_ids)
    print(f"  {label:15}: {missing}/{len(sample_ids)} missing ({100*missing/len(sample_ids):.0f}%)")

print(f"\nOverall across all sampled positions: {overall_missing}/{overall_checked} missing "
      f"({100*overall_missing/overall_checked:.1f}%)")
