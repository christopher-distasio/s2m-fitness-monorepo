"""
Embed the REAL FNDDS dataset correctly -- data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv,
confirmed to contain genuine, distinct FNDDS data (its food_nutrient.csv uses
legacy-style nutrient IDs different from SR Legacy's modern ones -- verified
in the earlier nutrient_nbr validation work).

Uses uuid4() for point IDs, not a hash of fdc_id -- avoids the exact class of
bug hit earlier this project (Python's hash() being randomized per-process,
making IDs unrecoverable across script runs). qdrant_id is stored in the
payload and is always the lookup key going forward, same pattern as every
other extraction script in this project -- the point ID itself never needs
to be recomputed.

Run delete_mislabeled_fndds.py FIRST to clear the junk duplicate data before
running this.
"""
import pandas as pd
import uuid
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models
import os
from dotenv import load_dotenv

load_dotenv()

QDRANT_URL = "http://192.168.1.227:6333"
COLLECTION_NAME = "food-vectors"
EMBEDDING_MODEL = "text-embedding-3-large"
FNDDS_PATH = "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food.csv"

BATCH_SIZE = 100
TEST_MODE = False
TEST_LIMIT = 50

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
qdrant_client = QdrantClient(url=QDRANT_URL, timeout=60)


def main():
    print(f"Loading real FNDDS data from: {FNDDS_PATH}")
    df = pd.read_csv(FNDDS_PATH, usecols=["fdc_id", "description"], low_memory=False)
    print(f"Total FNDDS records: {len(df):,}")

    if TEST_MODE:
        df = df.head(TEST_LIMIT)
        print(f"TEST_MODE: limited to {len(df)} records")

    total_embedded = 0
    points_batch = []

    for start in range(0, len(df), BATCH_SIZE):
        chunk = df.iloc[start:start + BATCH_SIZE]
        descriptions = [d if pd.notna(d) else "" for d in chunk["description"].tolist()]

        response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=descriptions)

        for i, (_, row) in enumerate(chunk.iterrows()):
            embedding = response.data[i].embedding
            point = models.PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "qdrant_id": str(row["fdc_id"]),
                    "description": row["description"] if pd.notna(row["description"]) else "",
                    "source": "fndds",
                },
            )
            points_batch.append(point)

        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points_batch, wait=False)
        total_embedded += len(points_batch)
        print(f"Embedded {total_embedded:,} / {len(df):,}", end="\r")
        points_batch = []

    print(f"\n\n✅ Real FNDDS embedding complete. Total: {total_embedded:,}")

    if TEST_MODE:
        print(f"\nTEST_MODE was on. Verify results look right, then set TEST_MODE = False for the full run.")


if __name__ == "__main__":
    main()
