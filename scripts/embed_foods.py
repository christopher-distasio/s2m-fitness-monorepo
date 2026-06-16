"""
Embed USDA SR Legacy foods and upsert to Pinecone.
Run once from the project root:
    poetry run python scripts/embed_foods.py

Requires in .env:
    OPENAI_API_KEY=...
    PINECONE_API_KEY=...
"""

import json
import os
import time
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "food-index"
EMBEDDING_MODEL = "text-embedding-3-large"
BATCH_SIZE = 100  # OpenAI embedding batch size
UPSERT_BATCH_SIZE = 100  # Pinecone upsert batch size

# Load clean food data
DATA_PATH = os.path.join(os.path.dirname(__file__), "branded_clean.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    foods = json.load(f)

print(f"Loaded {len(foods)} foods")

# Init clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

def embed_batch(texts: list[str]) -> list[list[float]]:
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]

def upsert_batch(records: list[dict]):
    index.upsert(vectors=records)

total = len(foods)
processed = 0
errors = 0

print(f"Starting embedding and upsert of {total} foods...")
print(f"Batch size: {BATCH_SIZE}")

for i in range(0, total, BATCH_SIZE):
    batch = foods[i:i + BATCH_SIZE]
    texts = [food["name"] for food in batch]

    try:
        embeddings = embed_batch(texts)
    except Exception as e:
        print(f"Embedding error at batch {i}: {e}")
        errors += 1
        time.sleep(5)
        continue

    records = []
    for food, embedding in zip(batch, embeddings):
        records.append({
            "id": str(food["fdc_id"]),
            "values": embedding,
            "metadata": {
                "name": food["name"],
                "calories": food["calories"] or 0,
                "protein": food["protein"] or 0,
                "fat": food["fat"] or 0,
                "carbs": food["carbs"] or 0,
                "source": "usda_sr_legacy",
            }
        })

    try:
        upsert_batch(records)
    except Exception as e:
        print(f"Upsert error at batch {i}: {e}")
        errors += 1
        time.sleep(5)
        continue

    processed += len(batch)
    pct = round(processed / total * 100)
    print(f"Progress: {processed}/{total} ({pct}%) — errors: {errors}")

    # Rate limit buffer
    time.sleep(0.5)

print(f"\nDone. Processed: {processed}, Errors: {errors}")
print(f"Check your Pinecone dashboard — food-index should have {processed} records.")