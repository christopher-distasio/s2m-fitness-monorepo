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
    "1079": "fiber",
    "1063": "sugar",
    "1258": "saturated_fat",
    "1257": "trans_fat",
    "1093": "sodium",
    "1253": "cholesterol",
    "1087": "calcium",
    "1089": "iron",
    "1090": "magnesium",
    "1092": "potassium",
    "1095": "zinc",
    "1104": "vitamin_a_iu",
    "1106": "vitamin_a_rae_mcg",
    "1162": "vitamin_c",
    "1114": "vitamin_d_mcg",
    "1109": "vitamin_e_mg",
    "1185": "vitamin_k",
    "1165": "vitamin_b1",
    "1166": "vitamin_b2",
    "1167": "vitamin_b3",
    "1175": "vitamin_b6",
    "1177": "folate",              # verified via SR Legacy nutrient.csv: 'Folate, total' (UG)
    "1186": "folic_acid_mcg",      # verified: 'Folic acid' (UG) — corrected from mislabeled folate_food_mcg
    "1190": "folate_dfe_mcg",      # verified: 'Folate, DFE' (UG) — corrected from mislabeled folic_acid_mcg
    "1170": "pantothenic_acid",
    "1178": "vitamin_b12",
    "1235": "added_sugars",
    "1292": "monounsaturated_fat",
    "1293": "polyunsaturated_fat",
    "1057": "caffeine",
    "1091": "phosphorus",
    "1098": "copper",
    "1101": "manganese",
    "1103": "selenium",
    "1180": "choline",
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

# Step 1 - Load US-only food IDs + metadata from branded_food.csv
print("Step 1: Loading US branded food IDs...")
us_fdc_ids = set()
branded_meta = {}

skipped_unit_counts = {}


def serving_size_unit_skipped(unit_value):
    key = unit_value if unit_value else "(empty)"
    skipped_unit_counts[key] = skipped_unit_counts.get(key, 0) + 1


with open(get_file("branded_food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        country = row.get("market_country", "").strip()
        if country != "United States":
            continue
        fdc_id = row["fdc_id"]
        us_fdc_ids.add(fdc_id)

        brand_name = (row.get("brand_name") or "").strip()
        brand_owner = (row.get("brand_owner") or "").strip()
        # Consumer-facing brand for name-building. Do NOT fall back to
        # brand_owner here — manufacturer strings like "Wal-Mart Stores, Inc."
        # are absent from descriptions that already start with "GREAT VALUE",
        # so owner-fallback would prepend and later live brand+name concat
        # would double again.
        brand = brand_name

        serving_size_unit = (row.get("serving_size_unit") or "").strip().lower()
        serving_size_raw = (row.get("serving_size") or "").strip()
        serving_size_g = None
        if serving_size_raw:
            try:
                serving_size = float(serving_size_raw)
                # Real unit codes found in branded_food.csv: g, gm, grm (gram
                # variants), ml, mlt (milliliter variants), mg (milligram),
                # mc (microgram, essentially never a real serving size), oz
                # (not seen in this dataset but harmless to keep), iu
                # (International Units — not a mass/volume unit, can't convert),
                # and '' (missing).
                if serving_size_unit in ("g", "gm", "grm"):
                    serving_size_g = serving_size
                elif serving_size_unit in ("ml", "mlt"):
                    # approximation for liquids close to water density;
                    # good enough for a serving-size scalar, not exact science
                    serving_size_g = serving_size
                elif serving_size_unit == "mg":
                    serving_size_g = serving_size / 1000
                elif serving_size_unit == "mc":
                    serving_size_g = serving_size / 1_000_000
                elif serving_size_unit == "oz":
                    serving_size_g = serving_size * 28.3495
                elif serving_size_unit == "iu":
                    # Not a mass/volume unit — can't convert to grams.
                    # Leave as None; nutrition_service falls back to
                    # per-100g/serving_size_g=100 for these.
                    serving_size_unit_skipped(serving_size_unit)
                else:
                    serving_size_unit_skipped(serving_size_unit)
            except ValueError:
                serving_size_g = None

        branded_meta[fdc_id] = {
            "brand_name": brand_name,
            "brand_owner": brand_owner,
            "brand": brand,
            "subbrand_name": (row.get("subbrand_name") or "").strip(),
            "gtin_upc": (row.get("gtin_upc") or "").strip(),
            "ingredients": (row.get("ingredients") or "").strip(),
            "not_a_significant_source_of": (row.get("not_a_significant_source_of") or "").strip(),
            "data_source": (row.get("data_source") or "").strip(),
            "household_serving_fulltext": (row.get("household_serving_fulltext") or "").strip(),
            "branded_food_category": (row.get("branded_food_category") or "").strip(),
            "package_weight": (row.get("package_weight") or "").strip(),
            "preparation_state_code": (row.get("preparation_state_code") or "").strip(),
            "discontinued_date": (row.get("discontinued_date") or "").strip(),
            "short_description": (row.get("short_description") or "").strip(),
            "available_date": (row.get("available_date") or "").strip(),
            "trade_channel": (row.get("trade_channel") or "").strip(),
            "material_code": (row.get("material_code") or "").strip(),
            "modified_date": row.get("modified_date", ""),
            "serving_size_g": serving_size_g,
        }

print(f"Found {len(us_fdc_ids):,} US branded food IDs")
if skipped_unit_counts:
    print("Serving sizes NOT converted to grams (unit not convertible or unrecognized):")
    for unit, count in sorted(skipped_unit_counts.items(), key=lambda x: -x[1]):
        print(f"  {unit!r}: {count:,} foods")

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

        # Case-insensitive: skip prepend when description already contains
        # the brand (e.g. description "GREAT VALUE POTATO CHIPS").
        if brand and brand.lower() not in description.lower():
            search_name = f"{brand} {description}"
        else:
            search_name = description

        food_entry = {
            "fdc_id": fdc_id,
            "name": search_name,
            "description": description,
            "modified_date": meta.get("modified_date", ""),
            "serving_size_g": meta.get("serving_size_g"),
            "brand_name": meta.get("brand_name", ""),
            "brand_owner": meta.get("brand_owner", ""),
            "subbrand_name": meta.get("subbrand_name", ""),
            "gtin_upc": meta.get("gtin_upc", ""),
            "ingredients": meta.get("ingredients", ""),
            "not_a_significant_source_of": meta.get("not_a_significant_source_of", ""),
            "data_source": meta.get("data_source", ""),
            "household_serving_fulltext": meta.get("household_serving_fulltext", ""),
            "branded_food_category": meta.get("branded_food_category", ""),
            "package_weight": meta.get("package_weight", ""),
            "preparation_state_code": meta.get("preparation_state_code", ""),
            "discontinued_date": meta.get("discontinued_date", ""),
            "short_description": meta.get("short_description", ""),
            "available_date": meta.get("available_date", ""),
            "trade_channel": meta.get("trade_channel", ""),
            "material_code": meta.get("material_code", ""),
        }
        # nutrient fields, all start as None
        for field in NUTRIENT_IDS.values():
            food_entry[field] = None

        foods[fdc_id] = food_entry

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

# Step 6 - Remove internal-only fields before saving (keep description now — useful metadata)
for food in clean:
    food.pop("modified_date", None)

# Step 7 - Save
print(f"Saving to {OUTPUT_PATH}...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(clean, f)

print(f"\nDone. {len(clean):,} US branded foods saved to {OUTPUT_PATH}")
print("\nSample foods:")
for food in clean[:5]:
    print(f"  {food['name']}: {food['calories']} kcal, {food['protein']}g protein, "
          f"serving_size_g={food['serving_size_g']}, ingredients={food['ingredients'][:40]!r}...")