"""
Two identical test runs both showed 14/100 not-found -- rules out a timing
artifact. Identify exactly which fdc_ids are failing to resolve, for both
SR Legacy and FNDDS's first 50 records, and inspect their raw CSV values
directly rather than continuing to guess at a cause.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"

client = QdrantClient(url=QDRANT_URL, timeout=60)

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food.csv",
    "FNDDS": "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv",
}

for label, path in DATASETS.items():
    print(f"\n{'='*80}\n{label}\n{'='*80}")

    # Load WITHOUT specifying dtype, same as the real extraction script does,
    # to reproduce the exact same fdc_id formatting it would produce
    df = pd.read_csv(path, usecols=["fdc_id", "description"], low_memory=False)
    first_50 = df.head(50)

    print(f"dtype of fdc_id column: {first_50['fdc_id'].dtype}")
    print(f"First 5 raw fdc_id values as read by pandas: {first_50['fdc_id'].head(5).tolist()}")
    print(f"First 5 as str() (what the extraction script actually sends to Qdrant): "
          f"{[str(x) for x in first_50['fdc_id'].head(5).tolist()]}")

    str_ids = [str(f) for f in first_50["fdc_id"].tolist()]
    result, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="qdrant_id", match=models.MatchAny(any=str_ids))]
        ),
        limit=len(str_ids),
        with_payload=["qdrant_id"],
    )
    found_ids = {p.payload["qdrant_id"] for p in result}
    missing = [sid for sid in str_ids if sid not in found_ids]

    print(f"\nFound: {len(found_ids)}/{len(str_ids)}")
    print(f"Missing fdc_ids (as sent to Qdrant): {missing}")

    if missing:
        # Show the raw row for each missing one
        print(f"\nRaw CSV rows for the missing ones:")
        for missing_id in missing:
            # Try matching against both string and float representations
            row = df[df["fdc_id"].astype(str) == missing_id]
            if not row.empty:
                print(f"  fdc_id={missing_id}: description={row.iloc[0]['description']!r}")
            else:
                print(f"  fdc_id={missing_id}: NOT FOUND in source CSV at all (unexpected)")
