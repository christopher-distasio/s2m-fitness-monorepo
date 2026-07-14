"""
Process USDA SR Legacy foods into clean JSON for embedding.
Captures full nutrient panel (same field list as branded foods, verified
against nutrient.csv) plus ALL portion/serving options per food (SR Legacy
foods can have multiple named portions, unlike branded's single label serving).

Run from your scripts/ folder (adjust EXTRACT_DIR to your actual folder name):
    python3 process_sr_legacy.py
"""

import csv
import json
import os

EXTRACT_DIR = "./FoodData_Central_sr_legacy_food_csv_2018-04"
OUTPUT_PATH = "./sr_legacy_full_clean.json"

# Same nutrient IDs as process_branded.py — USDA nutrient IDs are universal
# across all FDC datasets (confirmed via nutrient.csv), so this list is
# proven-correct, not re-guessed.
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
    "1177": "folate",              # verified: 'Folate, total' (UG)
    "1186": "folic_acid_mcg",      # verified: 'Folic acid' (UG) — was mislabeled folate_food_mcg
    "1190": "folate_dfe_mcg",      # verified: 'Folate, DFE' (UG) — was mislabeled folic_acid_mcg
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
    return os.path.join(EXTRACT_DIR, filename)


# Step 0 - Verify our NUTRIENT_IDS against nutrient.csv (real names/units,
# not guessed). Prints any mismatches so we catch a wrong ID before using it.
print("Step 0: Verifying nutrient IDs against nutrient.csv...")
nutrient_reference = {}
with open(get_file("nutrient.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        nutrient_reference[row["id"]] = {
            "name": row.get("name", ""),
            "unit_name": row.get("unit_name", ""),
        }

for nid, field_name in NUTRIENT_IDS.items():
    ref = nutrient_reference.get(nid)
    if ref is None:
        print(f"  WARNING: nutrient_id {nid} ({field_name}) not found in nutrient.csv at all")
    else:
        print(f"  {nid} -> {field_name}: confirmed as {ref['name']!r} ({ref['unit_name']})")

# Step 1 - Load SR Legacy fdc_ids
print("\nStep 1: Loading SR Legacy food IDs...")
sr_legacy_ids = set()
with open(get_file("sr_legacy_food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        sr_legacy_ids.add(row["fdc_id"])
print(f"Found {len(sr_legacy_ids):,} SR Legacy food IDs")

# Step 2 - Load food names/descriptions
print("Step 2: Loading food names...")
foods = {}
with open(get_file("food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        fdc_id = row["fdc_id"]
        if fdc_id not in sr_legacy_ids:
            continue
        description = row.get("description", "").strip()
        food_entry = {
            "fdc_id": fdc_id,
            "name": description,
            "description": description,
            "portions": [],  # filled in Step 3
        }
        for field in NUTRIENT_IDS.values():
            food_entry[field] = None
        foods[fdc_id] = food_entry
print(f"Loaded {len(foods):,} SR Legacy food names")

# Step 3 - Load measure unit names (id -> name, e.g. "cup", "tbsp")
print("Step 3: Loading measure units...")
measure_units = {}
with open(get_file("measure_unit.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        measure_units[row["id"]] = row.get("name", "")
print(f"Loaded {len(measure_units):,} measure units")

# Step 4 - Load ALL portion options per food (not just one default)
print("Step 4: Loading food portions (all options per food)...")
portion_count = 0
with open(get_file("food_portion.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        fdc_id = row["fdc_id"]
        if fdc_id not in foods:
            continue
        try:
            gram_weight = float(row.get("gram_weight") or 0)
        except ValueError:
            gram_weight = None
        try:
            amount = float(row.get("amount") or 0)
        except ValueError:
            amount = None

        unit_name = measure_units.get(row.get("measure_unit_id", ""), "")
        description = (row.get("portion_description") or "").strip()
        modifier = (row.get("modifier") or "").strip()
        try:
            seq_num = int(row.get("seq_num") or 0)
        except ValueError:
            seq_num = 0

        foods[fdc_id]["portions"].append({
            "amount": amount,
            "unit": unit_name,
            "description": description,
            "modifier": modifier,
            "gram_weight": gram_weight,
            "seq_num": seq_num,
        })
        portion_count += 1

print(f"Loaded {portion_count:,} total portion entries")

# Step 4b - Explicitly sort each food's portions by seq_num. USDA's own
# ordering tends to list the typical/sensible serving first and larger
# "whole item" measures later, but relying on raw CSV row order for this
# is a coincidence, not a guarantee. Sorting explicitly makes "first
# portion = sensible default" a real, reliable property of this data.
for food in foods.values():
    food["portions"].sort(key=lambda p: p["seq_num"])

# Step 5 - Load nutrients
print("Step 5: Loading nutrients (this will take a while)...")
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
        if i % 500_000 == 0 and i > 0:
            print(f"  Processed {i:,} nutrient rows...")
print(f"Loaded {nutrient_count:,} nutrient values")

# Step 6 - Filter to foods with at least calorie data
with_calories = [f for f in foods.values() if f["calories"] is not None]
print(f"Foods with calorie data: {len(with_calories):,}")

# Step 7 - Serialize portions as JSON string (Pinecone metadata can't hold
# nested objects/lists of numbers — only strings, numbers, booleans, and
# lists of strings). App must json.loads() this field after fetching.
print("Step 7: Serializing portions for Pinecone-compatible storage...")
for food in with_calories:
    food["portions_json"] = json.dumps(food["portions"])
    del food["portions"]  # remove the raw nested version, keep only the string

# Step 8 - Save
print(f"Saving to {OUTPUT_PATH}...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(with_calories, f)

print(f"\nDone. {len(with_calories):,} SR Legacy foods saved to {OUTPUT_PATH}")
print("\nSample foods:")
for food in with_calories[:3]:
    print(f"  {food['name']}: {food['calories']} kcal, portions_json={food['portions_json'][:100]}...")