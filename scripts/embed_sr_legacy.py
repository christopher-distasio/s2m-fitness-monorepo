"""
Embed USDA SR Legacy foods (from sr_legacy_full_clean.json) into Pinecone.
Uses the SAME food-index as branded foods — SR Legacy foods just carry a
different, smaller set of metadata fields (no brand/ingredients data, but
DO carry portions_json, which branded foods don't have).

Run once from the project root:
    poetry run python scripts/embed_sr_legacy.py

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
BATCH_SIZE = 100

# Set >0 only if resuming a previously interrupted run (same pattern as
# embed_foods.py) — check the last "Progress: X/Y" line from your terminal.
START_OFFSET = 0

# Same 39 nutrient IDs as branded foods — USDA nutrient IDs are universal
# across all FDC datasets, confirmed against nutrient.csv during processing.
NUTRIENT_FIELDS = [
    "calories", "protein", "fat", "carbs", "fiber", "sugar",
    "saturated_fat", "trans_fat", "sodium", "cholesterol",
    "calcium", "iron", "magnesium", "potassium", "zinc",
    "vitamin_a_iu", "vitamin_a_rae_mcg", "vitamin_c", "vitamin_d_mcg", "vitamin_e_mg", "vitamin_k",
    "vitamin_b1", "vitamin_b2", "vitamin_b3", "vitamin_b6",
    "folate", "folic_acid_mcg", "folate_dfe_mcg", "pantothenic_acid", "vitamin_b12", "added_sugars",
    "monounsaturated_fat", "polyunsaturated_fat", "caffeine",
    "phosphorus", "copper", "manganese", "selenium", "choline",
]


def truncate_text(field, value, cap=3000):
    if len(value) > cap:
        return value[:cap].rstrip() + "..."
    return value


def build_metadata(food: dict) -> dict:
    metadata = {
        "fdc_id": str(food.get("fdc_id", "")),
        "name": food.get("name", ""),
        "description": food.get("description", ""),
        "source": "usda_sr_legacy",
        # portions_json already a JSON string from process_sr_legacy.py —
        # SR Legacy has no single serving_size_g like branded does, since
        # each food can have multiple valid portion options.
        "portions_json": truncate_text("portions_json", food.get("portions_json", "[]"), cap=3000),
    }
    for field in NUTRIENT_FIELDS:
        metadata[field] = food.get(field) if food.get(field) is not None else 0
    return metadata


def main():
    data_path = os.path.join(os.path.dirname(__file__), "sr_legacy_full_clean.json")
    with open(data_path, "r", encoding="utf-8") as f:
        foods = json.load(f)
    print(f"Loaded {len(foods)} SR Legacy foods")

    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(INDEX_NAME)

    total = len(foods)
    processed = START_OFFSET
    errors = 0
    skipped_empty_names = 0

    print(f"Starting embedding and upsert of {total} SR Legacy foods...")
    print(f"Resuming from offset {START_OFFSET}")

    for i in range(START_OFFSET, total, BATCH_SIZE):
        batch = foods[i:i + BATCH_SIZE]
        valid_batch = [food for food in batch if (food.get("name") or "").strip()]
        skipped_this_batch = len(batch) - len(valid_batch)
        if skipped_this_batch:
            skipped_empty_names += skipped_this_batch
            print(f"  Skipping {skipped_this_batch} food(s) with empty names in batch {i}")
        if not valid_batch:
            continue

        texts = [food["name"] for food in valid_batch]

        try:
            response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            embeddings = [item.embedding for item in response.data]
        except Exception as e:
            print(f"Embedding error at batch {i}: {e}")
            errors += 1
            time.sleep(5)
            continue

        records = []
        for food, embedding in zip(valid_batch, embeddings):
            records.append({
                "id": f"sr_{food['fdc_id']}",  # prefixed to avoid any fdc_id collision with branded foods
                "values": embedding,
                "metadata": build_metadata(food),
            })

        try:
            index.upsert(vectors=records)
        except Exception as e:
            error_str = str(e)
            if "write unit limit" in error_str.lower() or "429" in error_str:
                print(f"\nSTOPPED at batch {i}: write-unit quota hit ({error_str})")
                print(f"Update START_OFFSET to {i} and re-run once unblocked.")
                break
            print(f"Upsert error at batch {i}: {e}")
            errors += 1
            time.sleep(5)
            continue

        processed += len(valid_batch)
        pct = round(processed / total * 100)
        print(f"Progress: {processed}/{total} ({pct}%) — errors: {errors}")
        time.sleep(0.5)

    print(f"\nDone. Processed: {processed}, Errors: {errors}")
    print(f"Skipped (empty name): {skipped_empty_names}")
    print(f"Check your Pinecone dashboard — food-index vector count should have increased by ~{processed}.")


if __name__ == "__main__":
    main()