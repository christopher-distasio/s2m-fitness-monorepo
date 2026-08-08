"""
Schema diff on food_nutrient.csv and nutrient.csv -- confirming actual
structure before building the metadata-enrichment script. Nutrient data in
USDA FoodData Central lives in a separate long-format file (one row per
food+nutrient combo), not directly in branded_food.csv/food.csv.
"""
import pandas as pd
import os

CANDIDATE_PATHS = [
    "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food_nutrient.csv",
    "data/raw/FoodData_Central_branded_food_csv_2026-04-30/nutrient.csv",
]

for path in CANDIDATE_PATHS:
    print("=" * 80)
    print(f"Checking: {path}")
    print("=" * 80)
    if not os.path.exists(path):
        print("  NOT FOUND at this path.")
        continue
    df = pd.read_csv(path, nrows=1000, low_memory=False)
    print(f"  Columns: {list(df.columns)}")
    print(f"  Sample rows:")
    print(df.head(5).to_string())
    print()

# Also check for serving_size / brand fields already confirmed present in
# branded_food.csv from the earlier schema diff, just re-confirming column
# names haven't drifted
BRANDED_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
print("=" * 80)
print(f"Re-confirming branded_food.csv serving/brand columns: {BRANDED_PATH}")
print("=" * 80)
if os.path.exists(BRANDED_PATH):
    df2 = pd.read_csv(BRANDED_PATH, nrows=5, low_memory=False)
    relevant = [c for c in df2.columns if any(
        kw in c.lower() for kw in ["serving", "brand", "household"]
    )]
    print(f"  Relevant columns found: {relevant}")
    print(df2[relevant].to_string() if relevant else "  None found")
