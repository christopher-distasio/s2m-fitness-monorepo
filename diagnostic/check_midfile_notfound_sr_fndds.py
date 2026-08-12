"""
Before running the full SR Legacy/FNDDS allergen job: check whether the high
not-found rate seen in TEST_MODE (which always samples the FIRST 50 rows of
each file) is a file-edge artifact -- same pattern found earlier in Branded
Foods -- or a real, broader problem. Samples from start, middle, and end of
each file's fdc_id list and checks presence in Qdrant via the qdrant_id filter.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 50

client = QdrantClient(url=QDRANT_URL, timeout=60)

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    "FNDDS": "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
}

for label, path in DATASETS.items():
    print(f"\n{'='*80}\n{label}\n{'='*80}")
    df = pd.read_csv(path, usecols=["fdc_id"], low_memory=False)
    total_rows = len(df)
    print(f"Total rows: {total_rows:,}")

    positions = {
        "start": 0,
        "25%": total_rows // 4,
        "middle": total_rows // 2,
        "75%": (total_rows * 3) // 4,
        "near end": max(0, total_rows - SAMPLE_SIZE - 5),
    }

    for pos_label, offset in positions.items():
        sample_ids = df["fdc_id"].iloc[offset:offset + SAMPLE_SIZE].astype(str).tolist()
        result, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=sample_ids))]
            ),
            limit=len(sample_ids),
            with_payload=["qdrant_id"],
        )
        found_count = len(result)
        missing = len(sample_ids) - found_count
        print(f"  {pos_label:10}: {missing}/{len(sample_ids)} missing ({100*missing/len(sample_ids):.0f}%)")
