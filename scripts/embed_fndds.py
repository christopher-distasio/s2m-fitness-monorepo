"""
Embed FNDDS survey foods into Pinecone (food-index), mirroring the
existing SR Legacy / Branded pipeline in embed_foods.py.

Key files used (from FoodData_Central_survey_food_csv_2024-10-31/):
  - survey_fndds_food.csv   -> food_code, description (this is the "food" table)
  - food_nutrient.csv       -> nutrient values per food_code
  - nutrient.csv            -> nutrient_id -> name/unit lookup
  - food_portion.csv        -> gram weights per portion (serving_size_g equivalent)
  - wweia_food_category.csv -> category grouping (stored in metadata)

Resume support included (same pattern as branded embed).
"""

import json
import os
import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from pathlib import Path

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
print(f"Looking for .env at: {dotenv_path}")
print(f"Exists: {dotenv_path.exists()}")
load_dotenv(dotenv_path=dotenv_path)
print(f"PINECONE_API_KEY loaded: {'PINECONE_API_KEY' in os.environ}")

FNDDS_DIR = "scripts/FoodData_Central_survey_food_csv_2024-10-31"
RESUME_OFFSET = 0  # bump this if the job dies partway through
TEST_MODE = False  # set to False to run the full dataset
TEST_LIMIT = 50

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")
client = OpenAI()

# --- Load and join tables -----------------------------------------------

# survey_fndds_food.csv is just a mapping table: fdc_id, food_code,
# wweia_category_number, start_date, end_date — no description here.
# Descriptions live in the standard food.csv, joined on fdc_id.
survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")

nutrients = pd.read_csv(f"{FNDDS_DIR}/nutrient.csv")
food_nutrient = pd.read_csv(f"{FNDDS_DIR}/food_nutrient.csv")
portions = pd.read_csv(f"{FNDDS_DIR}/food_portion.csv")
categories = pd.read_csv(f"{FNDDS_DIR}/wweia_food_category.csv")
# columns: wweia_food_category, wweia_food_category_description
category_lookup = dict(
    zip(categories["wweia_food_category"], categories["wweia_food_category_description"])
)

# Build a lookup: food_code -> list of {nutrient_id, amount}
nutrient_lookup = (
    food_nutrient.merge(nutrients, left_on="nutrient_id", right_on="id", how="left")
    .groupby("fdc_id")
    .apply(lambda g: dict(zip(g["nutrient_id"], g["amount"])))
    .to_dict()
)

# Build a lookup: food_code -> default gram weight (first portion, or 100g fallback)
portion_lookup = (
    portions.sort_values("seq_num")
    .groupby("fdc_id")["gram_weight"]
    .first()
    .to_dict()
)


def build_metadata(row):
    fdc_id = row["fdc_id"]
    nutrient_vals = nutrient_lookup.get(fdc_id, {})
    serving_size_g = portion_lookup.get(fdc_id, 100.0)

    return {
        "fdc_id": int(fdc_id),
        "description": row["description"],
        "data_type": "fndds",
        "category": category_lookup.get(row["wweia_category_number"], "unknown"),
        "serving_size_g": float(serving_size_g),
        **{f"nutrient_{k}": v for k, v in nutrient_vals.items()},
    }


def embed_batch(rows, start_idx):
    vectors = []
    for i, row in enumerate(rows):
        text = row["description"]
        resp = client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
        )
        embedding = resp.data[0].embedding
        vectors.append(
            {
                "id": f"fndds-{row['fdc_id']}",
                "values": embedding,
                "metadata": build_metadata(row),
            }
        )
    index.upsert(vectors=vectors, namespace="fndds")
    print(f"Upserted batch starting at offset {start_idx}, size {len(vectors)}")


def main():
    records = foods.to_dict("records")[RESUME_OFFSET:]
    if TEST_MODE:
        records = records[:TEST_LIMIT]
        print(f"TEST_MODE on — running {len(records)} records only")
    batch_size = 100
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        embed_batch(batch, RESUME_OFFSET + i)


if __name__ == "__main__":
    main()
