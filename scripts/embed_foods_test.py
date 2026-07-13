"""
SMALL-BATCH TEST VERSION — embeds only the 500 foods from branded_clean_test.json.
Uses the same Pinecone index as production (food-index) — this is safe:
these records will simply be overwritten when the full embed_foods.py run
happens later, since they share the same fdc_id-based vector IDs.

Run once from the project root:
    poetry run python scripts/embed_foods_test.py

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
DATA_PATH = os.path.join(os.path.dirname(__file__), "branded_clean_test.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    foods = json.load(f)

print(f"Loaded {len(foods)} foods")

# Init clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

# These MUST match the keys process_branded.py actually writes into branded_clean.json.
# Kept as an explicit list (not retyped by hand elsewhere) so a rename in one file
# doesn't silently break the other — that mismatch is what caused the last bug.
NUTRIENT_FIELDS = [
    "calories", "protein", "fat", "carbs", "fiber", "sugar",
    "saturated_fat", "trans_fat", "sodium", "cholesterol",
    "calcium", "iron", "magnesium", "potassium", "zinc",
    "vitamin_a_iu", "vitamin_a_rae_mcg", "vitamin_c", "vitamin_d_mcg", "vitamin_e_mg", "vitamin_k",
    "vitamin_b1", "vitamin_b2", "vitamin_b3", "vitamin_b6",
    "folate", "folate_food_mcg", "folic_acid_mcg", "pantothenic_acid", "vitamin_b12", "added_sugars",
    "monounsaturated_fat", "polyunsaturated_fat", "caffeine",
    "phosphorus", "copper", "manganese", "selenium", "choline",
]

TEXT_METADATA_FIELDS = [
    "description", "brand_name", "brand_owner", "subbrand_name", "gtin_upc",
    "ingredients", "not_a_significant_source_of", "data_source",
    "household_serving_fulltext", "branded_food_category", "package_weight",
    "preparation_state_code", "discontinued_date", "short_description",
    "available_date", "trade_channel", "material_code",
]

# Per-field character caps. "ingredients" gets generous room since it's the
# most information-rich field and the main reason we're capping at all —
# a handful of complex processed foods have very long ingredient lists.
# Everything else is normally short (brand names, category codes, etc.),
# so a lower cap is just a defensive ceiling in case of a surprise outlier.
FIELD_CHAR_CAPS = {
    "ingredients": 3000,
}
DEFAULT_TEXT_CAP = 500

truncated_field_count = 0


def truncate_text(field: str, value: str) -> str:
    global truncated_field_count
    cap = FIELD_CHAR_CAPS.get(field, DEFAULT_TEXT_CAP)
    if len(value) > cap:
        truncated_field_count += 1
        return value[:cap].rstrip() + "..."
    return value


def embed_batch(texts: list[str]) -> list[list[float]]:
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def upsert_batch(records: list[dict]):
    index.upsert(vectors=records)


def build_metadata(food: dict) -> dict:
    metadata = {
        "fdc_id": str(food.get("fdc_id", "")),
        "name": food.get("name", ""),
        "serving_size_g": food.get("serving_size_g") or 100,
        "source": "usda_branded_foods",
    }
    for field in NUTRIENT_FIELDS:
        metadata[field] = food.get(field) if food.get(field) is not None else 0
    for field in TEXT_METADATA_FIELDS:
        raw_value = food.get(field, "") or ""
        metadata[field] = truncate_text(field, raw_value)
    return metadata


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
            "metadata": build_metadata(food),
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
print(f"Fields truncated for length: {truncated_field_count}")
print(
    f"TEST BATCH — check your Pinecone dashboard, food-index should have {processed} new/updated records.")