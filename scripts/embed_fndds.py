"""
Embed FNDDS survey foods into Pinecone (food-index), mirroring the
existing SR Legacy / Branded pipeline in embed_foods.py.

Key files used (from data/raw/FoodData_Central_survey_food_csv_2024-10-31/):
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

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"
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

    # IMPORTANT: FNDDS's food_nutrient.csv uses the CLASSIC USDA nutrient
    # number scheme (e.g. 203=protein, 208=energy), which is DIFFERENT from
    # the modern FDC nutrient IDs (e.g. 1003=protein, 1008=calories) used
    # in SR Legacy/Branded's process scripts. Do NOT reuse that ID dict here
    # - the numbers don't correspond to the same nutrients. Instead, match
    # by the nutrient's official USDA name (from FNDDS's own nutrient.csv),
    # which is scheme-independent and self-verifying.
    NUTRIENT_NAME_TO_FRIENDLY = {
        "Protein": "protein",
        "Total lipid (fat)": "fat",
        "Carbohydrate, by difference": "carbs",
        "Energy": "calories",
        "Fiber, total dietary": "fiber",
        "Sugars, total including NLEA": "sugar",
        "Sugars, total": "sugar",
        "Sodium, Na": "sodium",
        "Calcium, Ca": "calcium",
        "Iron, Fe": "iron",
        "Magnesium, Mg": "magnesium",
        "Potassium, K": "potassium",
        "Zinc, Zn": "zinc",
        "Phosphorus, P": "phosphorus",
        "Copper, Cu": "copper",
        "Manganese, Mn": "manganese",
        "Selenium, Se": "selenium",
        "Vitamin A, IU": "vitamin_a_iu",
        "Vitamin A, RAE": "vitamin_a_rae_mcg",
        "Vitamin C, total ascorbic acid": "vitamin_c",
        "Vitamin D (D2 + D3)": "vitamin_d_mcg",
        "Vitamin E (alpha-tocopherol)": "vitamin_e_mg",
        "Vitamin K (phylloquinone)": "vitamin_k",
        "Thiamin": "vitamin_b1",
        "Riboflavin": "vitamin_b2",
        "Niacin": "vitamin_b3",
        "Vitamin B-6": "vitamin_b6",
        "Folate, total": "folate",
        "Folic acid": "folic_acid_mcg",
        "Folate, DFE": "folate_dfe_mcg",
        "Pantothenic acid": "pantothenic_acid",
        "Vitamin B-12": "vitamin_b12",
        "Sugars, added": "added_sugars",
        "Fatty acids, total monounsaturated": "monounsaturated_fat",
        "Fatty acids, total polyunsaturated": "polyunsaturated_fat",
        "Fatty acids, total saturated": "saturated_fat",
        "Fatty acids, total trans": "trans_fat",
        "Caffeine": "caffeine",
        "Choline, total": "choline",
        "Cholesterol": "cholesterol",
    }

    # Build nutrient_id -> friendly_name by matching official names.
    # IMPORTANT: nutrient.csv's "id" column uses the MODERN FDC scheme
    # (e.g. 1008=Energy), but food_nutrient.csv's "nutrient_id" column
    # for actual foods uses the CLASSIC scheme (e.g. 208=Energy) - these
    # don't match directly. The correct join key is nutrient.csv's
    # "nutrient_nbr" column, which holds the classic-scheme number.
    global NUTRIENT_ID_TO_FRIENDLY
    if "NUTRIENT_ID_TO_FRIENDLY" not in globals():
        NUTRIENT_ID_TO_FRIENDLY = {}
        for _, nrow in nutrients.iterrows():
            official_name = nrow["name"]
            if official_name == "Energy" and nrow["unit_name"] != "KCAL":
                continue  # skip the kJ variant, only want kcal
            if official_name in NUTRIENT_NAME_TO_FRIENDLY:
                # nutrient_nbr may be stored as a string like "203" or "203.0"
                try:
                    classic_id = int(float(nrow["nutrient_nbr"]))
                except (ValueError, TypeError):
                    continue
                NUTRIENT_ID_TO_FRIENDLY[classic_id] = NUTRIENT_NAME_TO_FRIENDLY[official_name]
        print(f"Matched {len(NUTRIENT_ID_TO_FRIENDLY)} of {len(NUTRIENT_NAME_TO_FRIENDLY)} "
              f"expected nutrient names against nutrient.csv (via nutrient_nbr)")

    friendly_nutrients = {
        friendly_name: nutrient_vals[nid]
        for nid, friendly_name in NUTRIENT_ID_TO_FRIENDLY.items()
        if nid in nutrient_vals
    }

    return {
        "fdc_id": int(fdc_id),
        "description": row["description"],
        "name": row["description"],
        "source": "usda_fndds",
        "category": category_lookup.get(row["wweia_category_number"], "unknown"),
        "serving_size_g": float(serving_size_g),
        **friendly_nutrients,
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
    index.upsert(vectors=vectors)
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