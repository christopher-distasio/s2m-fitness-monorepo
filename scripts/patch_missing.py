"""
Find the real gap between branded_clean.json and what's actually in Pinecone,
then re-embed only the missing foods. Safer than reconstructing batch numbers
from scrolled terminal output — this checks ground truth directly.

Run once from the project root:
    poetry run python scripts/patch_missing.py
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
BATCH_SIZE = 100

openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

# --- Import the same field lists + helpers from embed_foods.py so metadata
# stays byte-for-byte consistent with the main script. Adjust this import
# path if embed_foods.py lives somewhere else relative to this file.
from embed_foods import NUTRIENT_FIELDS, TEXT_METADATA_FIELDS, truncate_text, build_metadata  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "branded_clean.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    foods = json.load(f)

print(f"Loaded {len(foods)} foods from branded_clean.json")

# Step 1 - List every vector ID currently in Pinecone.
# index.list() paginates automatically via the SDK generator.
print("Step 1: Listing all vector IDs currently in Pinecone (this may take a minute)...")
existing_ids = set()
for id_batch in index.list():
    # Newer Pinecone SDK versions yield ListItem objects (with an .id
    # attribute), not raw ID strings, from index.list(). Handle both,
    # so this keeps working across SDK versions.
    for item in id_batch:
        existing_ids.add(item.id if hasattr(item, "id") else item)
print(f"Found {len(existing_ids):,} vectors currently in Pinecone")

# Step 2 - Find the real gap
all_expected_ids = {str(food["fdc_id"]) for food in foods}
missing_ids = all_expected_ids - existing_ids
print(f"Missing from Pinecone: {len(missing_ids):,} foods")

if not missing_ids:
    print("Nothing missing — you're fully up to date. No action needed.")
    exit()

missing_foods = [f for f in foods if str(f["fdc_id"]) in missing_ids and (f.get("name") or "").strip()]
skipped_empty = len(missing_ids) - len(missing_foods)
if skipped_empty:
    print(f"({skipped_empty} of the missing foods have empty names and will be skipped, same as before)")

print(f"Re-embedding {len(missing_foods)} missing foods...")

processed = 0
errors = 0

for i in range(0, len(missing_foods), BATCH_SIZE):
    batch = missing_foods[i:i + BATCH_SIZE]
    texts = [food["name"] for food in batch]

    try:
        response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        embeddings = [item.embedding for item in response.data]
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
            "metadata": build_metadata(food),
        })

    try:
        index.upsert(vectors=records)
    except Exception as e:
        error_str = str(e)
        if "write unit limit" in error_str.lower() or "429" in error_str:
            print(f"\nSTOPPED at batch {i}: write-unit quota hit ({error_str})")
            break
        print(f"Upsert error at batch {i}: {e}")
        errors += 1
        time.sleep(5)
        continue

    processed += len(batch)
    print(f"Progress: {processed}/{len(missing_foods)} — errors: {errors}")
    time.sleep(0.5)

print(f"\nDone patching. Processed: {processed}, Errors: {errors}")
print("Re-run this script's Step 1+2 afterward to confirm the gap is now zero.")