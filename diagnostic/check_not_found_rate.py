"""
Check the not-found rate at different points in the CSV file --
start, middle, and end -- to see if the earlier 15% not-found rate
was specific to the beginning of the file or holds throughout.
"""
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"
SAMPLE_SIZE = 200

client = QdrantClient(url=QDRANT_URL)

total_rows = sum(1 for _ in open(CSV_PATH)) - 1  # minus header
print(f"Total rows in CSV: {total_rows:,}\n")

positions = {
    "start (row 0)": 0,
    "25% through": total_rows // 4,
    "middle (50%)": total_rows // 2,
    "75% through": (total_rows * 3) // 4,
    "near end": max(0, total_rows - SAMPLE_SIZE - 10),
}

for label, skip_rows in positions.items():
    df = pd.read_csv(
        CSV_PATH, usecols=["fdc_id"], low_memory=False,
        skiprows=range(1, skip_rows + 1) if skip_rows > 0 else None,
        nrows=SAMPLE_SIZE,
    )
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
    not_found = len(fdc_ids) - len(found_ids)

    print(f"{label}: {not_found}/{len(fdc_ids)} not found ({100*not_found/len(fdc_ids):.1f}%)")
