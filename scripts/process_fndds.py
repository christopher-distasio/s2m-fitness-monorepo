"""
Process USDA FNDDS (survey) foods into clean JSON for embedding/backfill.
Mirrors process_sr_legacy.py schema: fdc_id, name, description, 39 nutrient
fields, portions_json. No brand/label fields (FNDDS has none).

IMPORTANT: FNDDS food_nutrient.csv uses legacy nutrient numbers (203, 204,
208, …) as its nutrient_id column — NOT the modern FDC surrogate IDs
(1003, 1004, 1008, …) used by SR Legacy and Branded. Mapping is therefore
by nutrient_nbr (validated in diagnostic/validate_fndds_nutrient_mapping.py).

Five fields are included for schema parity but are expected to stay null
because FNDDS does not publish them: trans_fat, vitamin_a_iu,
pantothenic_acid, added_sugars, manganese.

Run from repo root:
    poetry run python scripts/process_fndds.py
"""

import csv
import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = str(
    _REPO_ROOT / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"
)
OUTPUT_PATH = str(_REPO_ROOT / "data" / "processed" / "fndds_clean.json")

# Legacy nutrient_nbr -> field name. Keys match food_nutrient.csv's
# nutrient_id values in the FNDDS survey dump (legacy numbers themselves).
# Same 39 field names as process_branded.py / process_sr_legacy.py.
NUTRIENT_IDS = {
    "208": "calories",
    "203": "protein",
    "204": "fat",
    "205": "carbs",
    "291": "fiber",
    "269": "sugar",  # FNDDS Total Sugars (modern id 2000); not 1063/269.3
    "606": "saturated_fat",
    "605": "trans_fat",  # expected null in FNDDS — included for schema parity
    "307": "sodium",
    "601": "cholesterol",
    "301": "calcium",
    "303": "iron",
    "304": "magnesium",
    "306": "potassium",
    "309": "zinc",
    "318": "vitamin_a_iu",  # expected null in FNDDS
    "320": "vitamin_a_rae_mcg",
    "401": "vitamin_c",
    "328": "vitamin_d_mcg",
    "323": "vitamin_e_mg",
    "430": "vitamin_k",
    "404": "vitamin_b1",
    "405": "vitamin_b2",
    "406": "vitamin_b3",
    "415": "vitamin_b6",
    "417": "folate",
    "431": "folic_acid_mcg",
    "435": "folate_dfe_mcg",
    "410": "pantothenic_acid",  # expected null in FNDDS
    "418": "vitamin_b12",
    "539": "added_sugars",  # expected null in FNDDS
    "645": "monounsaturated_fat",
    "646": "polyunsaturated_fat",
    "262": "caffeine",
    "305": "phosphorus",
    "312": "copper",
    "315": "manganese",  # expected null in FNDDS
    "317": "selenium",
    "421": "choline",
}

# Documented expected-null fields (absent from FNDDS food_nutrient.csv)
EXPECTED_NULL_FIELDS = {
    "trans_fat",
    "vitamin_a_iu",
    "pantothenic_acid",
    "added_sugars",
    "manganese",
}


def get_file(filename):
    return os.path.join(EXTRACT_DIR, filename)


def _normalize_nbr(raw) -> str | None:
    """Coerce nutrient_nbr / nutrient_id to a clean integer-string key."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return str(int(float(s)))
    except ValueError:
        return s


# Step 0 - Verify NUTRIENT_IDS against nutrient.csv via nutrient_nbr
print("Step 0: Verifying legacy nutrient_nbr mappings against nutrient.csv...")
nutrient_by_nbr = {}
with open(get_file("nutrient.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        nbr = _normalize_nbr(row.get("nutrient_nbr"))
        if nbr is None:
            continue
        # Prefer the first match; later duplicates are rare edge cases
        if nbr not in nutrient_by_nbr:
            nutrient_by_nbr[nbr] = {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "unit_name": row.get("unit_name", ""),
            }

for nid, field_name in NUTRIENT_IDS.items():
    ref = nutrient_by_nbr.get(nid)
    expected_null = field_name in EXPECTED_NULL_FIELDS
    tag = " [expected null in FNDDS]" if expected_null else ""
    if ref is None:
        print(f"  WARNING: nutrient_nbr {nid} ({field_name}) not found in nutrient.csv{tag}")
    else:
        print(
            f"  {nid} -> {field_name}: confirmed as {ref['name']!r} "
            f"({ref['unit_name']}, modern id={ref['id']}){tag}"
        )

# Step 1 - Load FNDDS fdc_ids from survey_fndds_food.csv
print("\nStep 1: Loading FNDDS food IDs...")
fndds_ids = set()
with open(get_file("survey_fndds_food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        fndds_ids.add(row["fdc_id"])
print(f"Found {len(fndds_ids):,} FNDDS food IDs")

# Step 2 - Load food names/descriptions
print("Step 2: Loading food names...")
foods = {}
with open(get_file("food.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        fdc_id = row["fdc_id"]
        if fdc_id not in fndds_ids:
            continue
        description = row.get("description", "").strip()
        food_entry = {
            "fdc_id": fdc_id,
            "name": description,
            "description": description,
            "portions": [],
        }
        for field in NUTRIENT_IDS.values():
            food_entry[field] = None
        foods[fdc_id] = food_entry
print(f"Loaded {len(foods):,} FNDDS food names")

# Step 3 - Load measure unit names
print("Step 3: Loading measure units...")
measure_units = {}
with open(get_file("measure_unit.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        measure_units[row["id"]] = row.get("name", "")
print(f"Loaded {len(measure_units):,} measure units")

# Step 4 - Load ALL portion options per food
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

# Step 4b - Sort portions by seq_num so first entry is the sensible default
for food in foods.values():
    food["portions"].sort(key=lambda p: p["seq_num"])

# Step 5 - Load nutrients (legacy nutrient_nbr as nutrient_id)
print("Step 5: Loading nutrients...")
nutrient_count = 0
with open(get_file("food_nutrient.csv"), newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        fdc_id = row["fdc_id"]
        nutrient_id = _normalize_nbr(row["nutrient_id"])
        if fdc_id in foods and nutrient_id in NUTRIENT_IDS:
            field = NUTRIENT_IDS[nutrient_id]
            try:
                value = float(row["amount"])
                if foods[fdc_id][field] is None:
                    foods[fdc_id][field] = round(value, 2)
                    nutrient_count += 1
            except (ValueError, KeyError):
                pass
        if i % 100_000 == 0 and i > 0:
            print(f"  Processed {i:,} nutrient rows...")
print(f"Loaded {nutrient_count:,} nutrient values")

# Step 6 - Filter to foods with at least calorie data
with_calories = [f for f in foods.values() if f["calories"] is not None]
print(f"Foods with calorie data: {len(with_calories):,}")

# Confirm expected-null fields stayed null across the whole set
print("\nExpected-null field check (should be 0 non-null counts):")
for field in sorted(EXPECTED_NULL_FIELDS):
    non_null = sum(1 for f in with_calories if f.get(field) is not None)
    status = "OK" if non_null == 0 else "UNEXPECTED"
    print(f"  {field}: {non_null:,} non-null  [{status}]")

# Step 7 - Serialize portions as JSON string (same as SR Legacy)
print("\nStep 7: Serializing portions...")
for food in with_calories:
    food["portions_json"] = json.dumps(food["portions"])
    del food["portions"]

# Step 8 - Save
print(f"Saving to {OUTPUT_PATH}...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(with_calories, f)

print(f"\nDone. {len(with_calories):,} FNDDS foods saved to {OUTPUT_PATH}")
print("\nSample foods:")
for food in with_calories[:3]:
    print(
        f"  {food['name']}: {food['calories']} kcal, "
        f"protein={food['protein']}, portions_json={food['portions_json'][:100]}..."
    )
