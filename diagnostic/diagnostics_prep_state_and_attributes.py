"""
Two independent diagnostics, run together since both are pure inspection:

PART A (Queue item 6): preparation_state_code in branded_food.csv --
confirm what values exist, coverage, and real examples, before deciding
whether/how to use it to avoid dry-mix-vs-prepared calorie errors.

PART B (Queue item 10): food_attribute.csv (SR Legacy + FNDDS) --
confirm what it actually contains before deciding relevance, using
food_attribute_type.csv to resolve attribute type IDs to real names.
"""
import pandas as pd

# ============================================================================
# PART A: preparation_state_code
# ============================================================================
print("=" * 90)
print("PART A: preparation_state_code (branded_food.csv)")
print("=" * 90)

BRANDED_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
branded = pd.read_csv(
    BRANDED_PATH,
    usecols=["fdc_id", "preparation_state_code", "description" if False else "short_description", "branded_food_category"],
    low_memory=False,
)

total = len(branded)
non_null = branded["preparation_state_code"].notna().sum()
print(f"\nTotal Branded Foods records: {total:,}")
print(f"Records with preparation_state_code populated: {non_null:,} ({100*non_null/total:.1f}%)")

print(f"\nDistinct values and counts:")
value_counts = branded["preparation_state_code"].value_counts(dropna=False)
for val, count in value_counts.items():
    pct = 100 * count / total
    print(f"  {str(val):20} {count:>10,}  ({pct:5.1f}%)")

print(f"\nSample real products for each code (first 3 each):")
for val in branded["preparation_state_code"].dropna().unique():
    subset = branded[branded["preparation_state_code"] == val].head(3)
    print(f"\n  --- code: {val} ---")
    for _, row in subset.iterrows():
        desc = row.get("short_description", "")
        cat = row.get("branded_food_category", "")
        print(f"    fdc_id={row['fdc_id']}  category={cat}  desc={str(desc)[:60]}")

# ============================================================================
# PART B: food_attribute.csv
# ============================================================================
print("\n\n" + "=" * 90)
print("PART B: food_attribute.csv (SR Legacy + FNDDS)")
print("=" * 90)

DATASETS = {
    "SR Legacy": "data/raw/FoodData_Central_sr_legacy_food_csv_2018-04",
    "FNDDS/Survey": "data/raw/FoodData_Central_survey_food_csv_2024-10-31",
}

for label, folder in DATASETS.items():
    print(f"\n{'#'*90}")
    print(f"# {label}")
    print(f"{'#'*90}")

    attr_path = f"{folder}/food_attribute.csv"
    attr_type_path = f"{folder}/food_attribute_type.csv"

    attrs = pd.read_csv(attr_path, low_memory=False)
    attr_types = pd.read_csv(attr_type_path, low_memory=False)

    print(f"\nTotal food_attribute rows: {len(attrs):,}")
    print(f"\nAttribute types defined in food_attribute_type.csv:")
    for _, row in attr_types.iterrows():
        print(f"  id={row['id']:4}  name={row['name']:30}  description={str(row.get('description', ''))[:50]}")

    print(f"\nActual usage counts per attribute_type_id in food_attribute.csv:")
    type_counts = attrs["food_attribute_type_id"].value_counts()
    for type_id, count in type_counts.items():
        type_name_match = attr_types[attr_types["id"] == type_id]["name"]
        type_name = type_name_match.values[0] if len(type_name_match) else "(unknown type)"
        print(f"  type_id={type_id:4}  count={count:>10,}  name={type_name}")

        # Show a few real name/value examples for this type
        sample = attrs[attrs["food_attribute_type_id"] == type_id].head(3)
        for _, row in sample.iterrows():
            print(f"      example: name={row.get('name', '')!r}  value={str(row.get('value', ''))[:60]!r}")
