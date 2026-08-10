"""
Analyze all "NS as to X" (Not Specified) patterns in FNDDS descriptions.

For each unique NS phrase found, this script:
1. Counts how often it occurs
2. Finds the "base" description with the NS clause stripped out
3. Looks for sibling descriptions that share the same base but specify
   a concrete value instead of NS
4. Prints calories/fat for the NS version vs. its concrete siblings, so
   we can see whether USDA's NS default matches the higher-calorie,
   lower-calorie, or some blended value.

Run from repo root: poetry run python scripts/analyze_ns_patterns.py
"""

import re
import pandas as pd
from pathlib import Path

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"

# --- Load and join tables (same pattern as embed_fndds.py) ---------------

survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")

food_nutrient = pd.read_csv(f"{FNDDS_DIR}/food_nutrient.csv")

# IMPORTANT: food_nutrient.csv's nutrient_id column ALREADY uses the
# classic USDA nutrient number scheme (208=Energy, 204=Fat) -- this is
# NOT the same as nutrient.csv's "id" column (which is the modern FDC
# scheme, e.g. 1008=Energy). No conversion/lookup is needed here; we can
# use food_nutrient["nutrient_id"] directly as the classic number.
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

# --- Step 1: find all unique "NS as to X" phrases ------------------------

ns_pattern = re.compile(r"ns as to [a-z/ ]+?(?=,|$)")

ns_phrase_counts = {}
for desc in foods["description"].dropna():
    for match in ns_pattern.findall(desc.lower()):
        ns_phrase_counts[match.strip()] = ns_phrase_counts.get(match.strip(), 0) + 1

print("=" * 70)
print("ALL UNIQUE 'NS AS TO' PHRASES FOUND (sorted by frequency)")
print("=" * 70)
for phrase, count in sorted(ns_phrase_counts.items(), key=lambda x: -x[1]):
    print(f"  {count:4d}  {phrase}")

# --- Step 2: for each NS phrase, find sibling comparisons -----------------

print("\n" + "=" * 70)
print("SIBLING COMPARISONS (NS version vs. concrete-value versions)")
print("=" * 70)

def get_base(desc, ns_phrase):
    """Strip the NS clause out of a description to get its 'base' form."""
    return re.sub(re.escape(ns_phrase), "<<VALUE>>", desc.lower()).strip()

for ns_phrase in ns_phrase_counts:
    # Find all descriptions containing this NS phrase
    ns_rows = foods[foods["description"].str.lower().str.contains(re.escape(ns_phrase), na=False)]
    if ns_rows.empty:
        continue

    print(f"\n--- NS phrase: '{ns_phrase}' ({len(ns_rows)} matching rows) ---")

    # Just take the first example and try to find its siblings
    example_row = ns_rows.iloc[0]
    base = get_base(example_row["description"], ns_phrase)

    # Extract the "slot" prefix/suffix around <<VALUE>> to search for siblings
    prefix, _, suffix = base.partition("<<value>>")

    # Search all descriptions that share this prefix+suffix pattern but
    # have a different (non-NS) value in the slot
    candidates = foods[
        foods["description"].str.lower().str.startswith(prefix.strip(), na=False)
    ]

    print(f"  NS example: {example_row['description']}")
    ns_cal = calories_lookup.get(example_row["fdc_id"])
    ns_fat = fat_lookup.get(example_row["fdc_id"])
    print(f"    -> calories: {ns_cal}, fat: {ns_fat}")

    shown = 0
    for _, row in candidates.iterrows():
        if row["fdc_id"] == example_row["fdc_id"]:
            continue
        if ns_phrase in row["description"].lower():
            continue  # skip other NS variants, we want concrete siblings
        if shown >= 4:
            break
        cal = calories_lookup.get(row["fdc_id"])
        fat = fat_lookup.get(row["fdc_id"])
        print(f"  Sibling: {row['description']}")
        print(f"    -> calories: {cal}, fat: {fat}")
        shown += 1

    if shown == 0:
        print("  (no clear siblings found via prefix match -- may need manual lookup)")