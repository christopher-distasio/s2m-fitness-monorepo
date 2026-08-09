"""
Embed the 7,743 genuinely-missing SR Legacy records (confirmed absent from
the entire collection, not just mislabeled -- see check_sr_legacy_hiding_elsewhere.py).
Scoped to exactly the missing list from find_all_missing_sr_legacy.py, so the
50 already-correct records are never touched or duplicated.

Same safe pattern as embed_real_fndds.py: uuid4() point IDs, qdrant_id in
payload as the permanent lookup key.
"""
import pandas as pd
import uuid
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models
import os
from dotenv import load_dotenv

load_dotenv()

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "food-vectors"
EMBEDDING_MODEL = "text-embedding-3-large"
MISSING_LIST_PATH = "diagnostic/missing_sr_legacy_fdc_ids.csv"

BATCH_SIZE = 100
TEST_MODE = False
TEST_LIMIT = 50

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
qdrant_client = QdrantClient(url=QDRANT_URL, timeout=60)


def main():
    print(f"Loading missing SR Legacy records from: {MISSING_LIST_PATH}")
    df = pd.read_csv(MISSING_LIST_PATH)
    print(f"Total missing records: {len(df):,}")

    if TEST_MODE:
        df = df.head(TEST_LIMIT)
        print(f"TEST_MODE: limited to {len(df)} records")

    total_embedded = 0

    for start in range(0, len(df), BATCH_SIZE):
        chunk = df.iloc[start:start + BATCH_SIZE]
        descriptions = [d if pd.notna(d) else "" for d in chunk["description"].tolist()]

        response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=descriptions)

        points_batch = []
        for i, (_, row) in enumerate(chunk.iterrows()):
            embedding = response.data[i].embedding
            point = models.PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "qdrant_id": str(row["fdc_id"]),
                    "description": row["description"] if pd.notna(row["description"]) else "",
                    "source": "sr_legacy",
                },
            )
            points_batch.append(point)

        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points_batch, wait=False)
        total_embedded += len(points_batch)
        print(f"Embedded {total_embedded:,} / {len(df):,}", end="\r")

    print(f"\n\n✅ Missing SR Legacy embedding complete. Total: {total_embedded:,}")

    if TEST_MODE:
        print(f"\nTEST_MODE was on. Verify results, then set TEST_MODE = False for the full run.")


if __name__ == "__main__":
    main()
