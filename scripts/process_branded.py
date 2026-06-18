"""
Process USDA Branded Foods CSV into clean JSON for embedding.
Filters: US market only, complete nutrition data, deduplicates by name.
Output: branded_clean.json

Run from your scripts/ folder:
    python3 process_branded.py

Expects the zip file at: ./FoodData_Central_branded_food_csv_2026-04-30.zip
Or extracted files in: ./FoodData_Central_branded_food_csv_2026-04-30/
"""

import csv
import json
import os
import zipfile

ZIP_PATH = "./FoodData_Central_branded_food_csv_2026-04-30.zip"
EXTRACT_DIR = "./FoodData_Central_branded_food_csv_2026-04-30"
OUTPUT_PATH = "./branded_clean.json"

NUTRIENT_IDS = {
    "1008": "calories",
    "1003": "protein",
    "1004": "fat",
    "1005": "carbs",
}

def get_file(filename):
    full_path = os.path.join(EXTRACT_DIR, filename)
    if os.path.exists(full_path):
        return full_path
    print(f"Extracting {filename} from zip...")
    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        target = f"FoodData_Central_branded_food_csv_2026-04-30/{filename}"
        z.extract(target, ".")
    return full_path

# Step 1 - Load US-only food IDs from branded_food.csv
print("Step 1: Loading US branded food IDs...")
us_fdc_ids = set()
branded_meta = {}

with open(get_file("branded_food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        country = row.get("market_country", "").strip()
        if country != "United States":
            continue
        fdc_id = row["fdc_id"]
        us_fdc_ids.add(fdc_id)
        brand = (row.get("brand_name") or row.get("brand_owner") or "").strip()

        serving_size_unit = (row.get("serving_size_unit") or "").strip().lower()
        serving_size_raw = (row.get("serving_size") or "").strip()
        serving_size_g = None
        if serving_size_raw:
            try:
                serving_size = float(serving_size_raw)
                if serving_size_unit == "g":
                    serving_size_g = serving_size
                elif serving_size_unit == "oz":
                    serving_size_g = serving_size * 28.3495
            except ValueError:
                serving_size_g = None

        branded_meta[fdc_id] = {
            "brand": brand,
            "modified_date": row.get("modified_date", ""),
            "serving_size_g": serving_size_g,
        }

print(f"Found {len(us_fdc_ids):,} US branded food IDs")

# Step 2 - Load food names for US IDs only
print("Step 2: Loading food names...")
foods = {}
with open(get_file("food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        fdc_id = row["fdc_id"]
        if fdc_id not in us_fdc_ids:
            continue
        description = row["description"].strip()
        meta = branded_meta.get(fdc_id, {})
        brand = meta.get("brand", "")

        if brand and brand.lower() not in description.lower():
            search_name = f"{brand} {description}"
        else:
            search_name = description

        foods[fdc_id] = {
            "fdc_id": fdc_id,
            "name": search_name,
            "description": description,
            "modified_date": meta.get("modified_date", ""),
            "serving_size_g": meta.get("serving_size_g"),
            "calories": None,
            "protein": None,
            "fat": None,
            "carbs": None,
        }

print(f"Loaded {len(foods):,} US food names")

# Step 3 - Load nutrients
print("Step 3: Loading nutrients (this will take several minutes)...")
nutrient_count = 0
with open(get_file("food_nutrient.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        fdc_id = row["fdc_id"]
        nutrient_id = row["nutrient_id"]
        if fdc_id in foods and nutrient_id in NUTRIENT_IDS:
            field = NUTRIENT_IDS[nutrient_id]
            try:
                value = float(row["amount"])
                if foods[fdc_id][field] is None:
                    foods[fdc_id][field] = round(value, 2)
                    nutrient_count += 1
            except (ValueError, KeyError):
                pass
        if i % 1_000_000 == 0 and i > 0:
            print(f"  Processed {i:,} nutrient rows...")

print(f"Loaded {nutrient_count:,} nutrient values")

# Step 4 - Filter to foods with calorie data
with_calories = [f for f in foods.values() if f["calories"] is not None]
print(f"Foods with calorie data: {len(with_calories):,}")

# Step 5 - Deduplicate by normalized name, keep most recently modified
print("Step 5: Deduplicating by name...")
seen = {}
for food in with_calories:
    key = food["description"].lower().strip()
    if key not in seen:
        seen[key] = food
    else:
        if food["modified_date"] > seen[key]["modified_date"]:
            seen[key] = food

clean = list(seen.values())
print(f"After deduplication: {len(clean):,} foods")

# Step 6 - Remove internal fields before saving
for food in clean:
    food.pop("description", None)
    food.pop("modified_date", None)

# Step 7 - Save
print(f"Saving to {OUTPUT_PATH}...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(clean, f)

print(f"\nDone. {len(clean):,} US branded foods saved to {OUTPUT_PATH}")
print("\nSample foods:")
for food in clean[:5]:
    print(f"  {food['name']}: {food['calories']} kcal, {food['protein']}g protein")