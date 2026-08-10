"""
Full inventory across all three datasets you've actually downloaded:
SR Legacy, Survey/FNDDS, Branded Foods.

Part 1: List every CSV file present in each dataset's folder, and every
column name in each file -- so you can see everything yourself, not just
what I assumed was there.

Part 2: Cross-reference nutrient_id usage across all three datasets' own
food_nutrient.csv files against the nutrient.csv reference tables --
confirms whether the three datasets use nutrient IDs consistently, and
specifically re-checks folate/folic acid/DFE presence in each dataset
individually (defined in a reference table is not the same as actually
used with real values in a given dataset).
"""
import pandas as pd
import os

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04",
    "FNDDS/Survey": "data/raw/FoodData_Central_survey_food_csv_2024-10-31",
    "Branded Foods": "data/raw/FoodData_Central_branded_food_csv_2026-04-30",
}

# ============================================================================
# PART 1: Full file + column inventory, no assumptions
# ============================================================================
print("=" * 100)
print("PART 1: EVERY CSV FILE AND EVERY COLUMN, ACROSS ALL THREE DATASETS")
print("=" * 100)

for label, folder in DATASETS.items():
    print(f"\n{'#'*100}")
    print(f"# {label}  --  {folder}")
    print(f"{'#'*100}")
    if not os.path.isdir(folder):
        print("  FOLDER NOT FOUND")
        continue
    csv_files = sorted(f for f in os.listdir(folder) if f.endswith(".csv"))
    print(f"  {len(csv_files)} CSV files found:\n")
    for fname in csv_files:
        path = os.path.join(folder, fname)
        try:
            df = pd.read_csv(path, nrows=2, low_memory=False)
            print(f"  --- {fname} ---")
            print(f"      columns: {list(df.columns)}")
        except Exception as e:
            print(f"  --- {fname} ---")
            print(f"      COULD NOT READ: {e}")
    print()

# ============================================================================
# PART 2: Cross-dataset nutrient_id comparison
# ============================================================================
print("\n" + "=" * 100)
print("PART 2: NUTRIENT_ID USAGE -- COMPARED ACROSS ALL THREE DATASETS")
print("=" * 100)

# Load both reference tables for name lookup
ref_tables = {}
for label, path in [
    ("Survey (2024-10-31)", "data/raw/FoodData_Central_survey_food_csv_2024-10-31/nutrient.csv"),
    ("SR Legacy (2018-04)", "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/nutrient.csv"),
]:
    if os.path.exists(path):
        ref_tables[label] = pd.read_csv(path, low_memory=False)

# Figure out id/name columns from whichever loaded first
sample_ref = next(iter(ref_tables.values()))
id_col = "id" if "id" in sample_ref.columns else "nutrient_id"
name_col = "name" if "name" in sample_ref.columns else "nutrient_name"

def get_nutrient_name(nid):
    for df in ref_tables.values():
        match = df[df[id_col] == nid][name_col]
        if len(match):
            return match.values[0]
    return "(unknown -- not in either reference table)"

# Get nutrient_id usage from each dataset's own food_nutrient.csv
FOOD_NUTRIENT_PATHS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04/food_nutrient.csv",
    "FNDDS/Survey": "data/raw/FoodData_Central_survey_food_csv_2024-10-31/food_nutrient.csv",
    "Branded Foods": "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food_nutrient.csv",
}

nutrient_id_sets = {}
for label, path in FOOD_NUTRIENT_PATHS.items():
    if not os.path.exists(path):
        print(f"\n{label}: food_nutrient.csv NOT FOUND at {path}")
        continue
    df = pd.read_csv(path, usecols=["nutrient_id"], low_memory=False)
    counts = df["nutrient_id"].value_counts()
    nutrient_id_sets[label] = counts
    print(f"\n{label}: {len(counts)} distinct nutrient_ids used, {len(df):,} total nutrient rows")

# Build a comparison table across all datasets that have data
all_ids = set()
for counts in nutrient_id_sets.values():
    all_ids.update(counts.index.tolist())

print(f"\nTotal distinct nutrient_ids across ALL THREE datasets combined: {len(all_ids)}")
print("\nFull comparison table (sorted by total usage across all datasets):")
print(f"{'nutrient_id':>12} {'name':40} {'SR Legacy':>12} {'FNDDS':>12} {'Branded':>12}")

rows = []
for nid in all_ids:
    name = get_nutrient_name(nid)
    sr = nutrient_id_sets.get("SR Legacy", pd.Series(dtype=int)).get(nid, 0)
    fndds = nutrient_id_sets.get("FNDDS/Survey", pd.Series(dtype=int)).get(nid, 0)
    branded = nutrient_id_sets.get("Branded Foods", pd.Series(dtype=int)).get(nid, 0)
    total = sr + fndds + branded
    rows.append((total, nid, name, sr, fndds, branded))

rows.sort(reverse=True)
for total, nid, name, sr, fndds, branded in rows:
    print(f"{nid:>12} {name[:40]:40} {sr:>12,} {fndds:>12,} {branded:>12,}")

# ============================================================================
# PART 3: Folate/folic acid specifically, per dataset
# ============================================================================
print("\n" + "=" * 100)
print("PART 3: FOLATE / FOLIC ACID / DFE -- ACTUAL USAGE PER DATASET")
print("=" * 100)
for total, nid, name, sr, fndds, branded in rows:
    if "folate" in name.lower() or "folic" in name.lower():
        print(f"  id={nid:6}  {name:40}  SR Legacy={sr:>10,}  FNDDS={fndds:>10,}  Branded={branded:>10,}")