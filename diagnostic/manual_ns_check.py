"""
Manual targeted sibling comparison for specific NS categories.

Run from repo root: poetry run python scripts/manual_ns_check.py
"""

import pandas as pd
from pathlib import Path

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"

survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")

food_nutrient = pd.read_csv(f"{FNDDS_DIR}/food_nutrient.csv")

calories_lookup = (
    food_nutrient[food_nutrient["nutrient_id"] == 208]
    .drop_duplicates(subset="fdc_id")
    .set_index("fdc_id")["amount"]
    .to_dict()
)
fat_lookup = (
    food_nutrient[food_nutrient["nutrient_id"] == 204]
    .drop_duplicates(subset="fdc_id")
    .set_index("fdc_id")["amount"]
    .to_dict()
)


def show_family(search_term):
    print(f"\n{'='*70}")
    print(f"FAMILY: descriptions containing '{search_term}'")
    print(f"{'='*70}")
    matches = foods[foods["description"].str.lower().str.contains(search_term.lower(), na=False)]
    for _, row in matches.iterrows():
        cal = calories_lookup.get(row["fdc_id"])
        fat = fat_lookup.get(row["fdc_id"])
        print(f"  {row['description']}")
        print(f"    -> calories: {cal}, fat: {fat}")


# --- ns as to fat type: Egg, whole, fried family --------------------------
show_family("egg, whole, fried")

# --- ns as to fat: Milk, evaporated family --------------------------------
show_family("milk, evaporated")

# --- ns as to cooking method: Chicken breast family -----------------------
show_family("chicken breast")

# --- ns as to fat eaten / type of meat: Steak family ----------------------
show_family("steak,")