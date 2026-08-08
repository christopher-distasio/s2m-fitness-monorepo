"""
Queue item 1: FNDDS nutrient_nbr validation.

FNDDS's food_nutrient.csv uses legacy pre-FoodData-Central nutrient numbers
(203=Protein, 204=Fat, etc.) instead of the modern surrogate IDs (1003, 1004)
used by SR Legacy and Branded Foods. All three multi-AI reviews confirmed the
mechanism (join against nutrient.nutrient_nbr, not nutrient.id) -- but one
reviewer explicitly said don't hard-code this until every one of the 63 IDs
is individually validated, since a wrong mapping here would silently corrupt
FNDDS nutrition data across the board.

This script:
1. Joins all 63 legacy IDs against nutrient.csv via nutrient_nbr
2. Cross-checks each resolved name/unit against the equivalent modern ID
   (where we can identify one), to confirm they're not just similarly-named
   but actually the SAME nutrient in the SAME unit
3. Flags anything that doesn't resolve cleanly, rather than assuming success
"""
import pandas as pd

NUTRIENT_REF_PATH = "data/raw/FoodData_Central_survey_food_csv_2024-10-31/nutrient.csv"
FNDDS_FOOD_NUTRIENT_PATH = "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food_nutrient.csv"

# The 63 legacy IDs found in FNDDS's food_nutrient.csv (from the earlier audit)
FNDDS_LEGACY_IDS = [
    646, 645, 631, 630, 629, 628, 627, 626, 621, 620, 619, 618, 617, 614, 613,
    612, 611, 610, 609, 608, 607, 606, 601, 578, 573, 435, 432, 431, 430, 421,
    418, 417, 415, 406, 405, 404, 401, 338, 337, 334, 328, 323, 322, 321, 320,
    319, 317, 312, 309, 307, 306, 305, 304, 303, 301, 291, 269, 263, 262, 255,
    221, 208, 205, 204, 203,
]

# Known modern-ID equivalents for the core nutrients we most need to confirm
# (from the earlier cross-dataset comparison table) -- used to cross-check
# that the legacy resolution isn't just a plausible-looking name, but the
# actual same nutrient/unit as what SR Legacy and Branded Foods use.
KNOWN_MODERN_EQUIVALENTS = {
    203: (1003, "Protein"),
    204: (1004, "Total lipid (fat)"),
    205: (1005, "Carbohydrate, by difference"),
    208: (1008, "Energy"),
    255: (1051, "Water"),
    269: (2000, "Total Sugars"),
    291: (1079, "Fiber, total dietary"),
    301: (1087, "Calcium, Ca"),
    303: (1089, "Iron, Fe"),
    307: (1093, "Sodium, Na"),
    306: (1092, "Potassium, K"),
    304: (1090, "Magnesium, Mg"),
    305: (1091, "Phosphorus, P"),
    309: (1095, "Zinc, Zn"),
    312: (1098, "Copper, Cu"),
    317: (1103, "Selenium, Se"),
    319: (1105, "Retinol"),
    320: (1106, "Vitamin A, RAE"),
    321: (1107, "Carotene, beta"),
    401: (1162, "Vitamin C, total ascorbic acid"),
    404: (1165, "Thiamin"),
    405: (1166, "Riboflavin"),
    406: (1167, "Niacin"),
    415: (1175, "Vitamin B-6"),
    417: (1177, "Folate, total"),
    418: (1178, "Vitamin B-12"),
    421: (1180, "Choline, total"),
    430: (1185, "Vitamin K (phylloquinone)"),
    431: (1186, "Folic acid"),
    432: (1187, "Folate, food"),
    435: (1190, "Folate, DFE"),
    573: (1242, "Vitamin E, added"),
    601: (1253, "Cholesterol"),
    606: (1258, "Fatty acids, total saturated"),
}

nutrient_ref = pd.read_csv(NUTRIENT_REF_PATH, low_memory=False)
print(f"Loaded nutrient.csv reference: {len(nutrient_ref)} definitions\n")

# Confirm actual counts in FNDDS food_nutrient.csv for each legacy ID (so we
# know this list is complete and matches what's really there)
fndds_nutrients = pd.read_csv(FNDDS_FOOD_NUTRIENT_PATH, usecols=["nutrient_id"], low_memory=False)
real_counts = fndds_nutrients["nutrient_id"].value_counts()

print("=" * 100)
print("VALIDATION TABLE: all 63 FNDDS legacy nutrient IDs")
print("=" * 100)
print(f"{'Legacy ID':>10} {'Real count':>12} {'Resolved name (via nutrient_nbr)':40} {'Unit':>6} {'Modern ID':>10} {'Modern name':30} {'Match?'}")
print("-" * 140)

unresolved = []
mismatches = []

for legacy_id in FNDDS_LEGACY_IDS:
    real_count = real_counts.get(legacy_id, 0)

    # Try to resolve via nutrient_nbr (may need type coercion -- nutrient_nbr
    # sometimes stored as string like "203.0" or "203")
    match = nutrient_ref[
        nutrient_ref["nutrient_nbr"].astype(str).str.strip().str.rstrip(".0") == str(legacy_id)
    ]
    if match.empty:
        # Try exact numeric match as a fallback in case of formatting differences
        try:
            match = nutrient_ref[
                pd.to_numeric(nutrient_ref["nutrient_nbr"], errors="coerce") == float(legacy_id)
            ]
        except ValueError:
            pass

    if match.empty:
        print(f"{legacy_id:>10} {real_count:>12,} {'*** DID NOT RESOLVE ***':40}")
        unresolved.append(legacy_id)
        continue

    resolved_name = match.iloc[0]["name"]
    resolved_unit = match.iloc[0]["unit_name"]

    modern_id, expected_name = KNOWN_MODERN_EQUIVALENTS.get(legacy_id, (None, None))
    if modern_id:
        modern_match = nutrient_ref[nutrient_ref["id"] == modern_id]
        modern_unit = modern_match.iloc[0]["unit_name"] if len(modern_match) else "?"
        name_matches = resolved_name.strip().lower() == expected_name.strip().lower()
        unit_matches = resolved_unit == modern_unit
        status = "OK" if (name_matches and unit_matches) else "CHECK"
        if status == "CHECK":
            mismatches.append((legacy_id, resolved_name, resolved_unit, modern_id, expected_name, modern_unit))
        print(f"{legacy_id:>10} {real_count:>12,} {resolved_name:40} {resolved_unit:>6} {modern_id:>10} {expected_name:30} {status}")
    else:
        print(f"{legacy_id:>10} {real_count:>12,} {resolved_name:40} {resolved_unit:>6} {'(none)':>10} {'(not cross-checked)':30} ?")

print("\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)
print(f"Total legacy IDs checked: {len(FNDDS_LEGACY_IDS)}")
print(f"Failed to resolve at all: {len(unresolved)}  {unresolved if unresolved else ''}")
print(f"Resolved but name/unit mismatch vs known modern equivalent: {len(mismatches)}")
for m in mismatches:
    print(f"  legacy_id={m[0]}: resolved to '{m[1]}' ({m[2]}) -- expected '{m[4]}' ({m[5]}) matching modern id {m[3]}")

resolved_no_crosscheck = len(FNDDS_LEGACY_IDS) - len(unresolved) - len(KNOWN_MODERN_EQUIVALENTS)
print(f"\nResolved via nutrient_nbr but not in our known-equivalents cross-check list: "
      f"{len([i for i in FNDDS_LEGACY_IDS if i not in KNOWN_MODERN_EQUIVALENTS and i not in unresolved])}")
print("(these still resolved to a real nutrient name -- just not ones in our core Tier 1/2 list, lower priority to verify further)")
