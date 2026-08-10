"""
Look up the full ingredients text for a specific fdc_id.
Used to manually verify a specific extraction result before trusting the full run.
"""

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from allergen_extraction_logic import extract_allergen_states

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
TARGET_FDC_ID = 2545188

def lookup_single_record():
    print(f"Loading {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH, low_memory=False, usecols=["fdc_id", "ingredients"])
    row = df[df["fdc_id"] == TARGET_FDC_ID]

    if row.empty:
        print(f"fdc_id {TARGET_FDC_ID} not found.")
        return

    ingredients = row.iloc[0]["ingredients"]

    print("=" * 80)
    print(f"fdc_id: {TARGET_FDC_ID}")
    print("=" * 80)
    print(f"\nFULL INGREDIENTS TEXT:\n{ingredients}\n")

    states = extract_allergen_states(ingredients)
    print("=" * 80)
    print("EXTRACTION RESULT (all 9 allergens)")
    print("=" * 80)
    for allergen, state in states.items():
        print(f"  {allergen}: {state}")

    print("\n" + "=" * 80)
    print("MANUAL SHELLFISH TERM CHECK")
    print("=" * 80)
    shellfish_terms = ["crab", "shrimp", "lobster", "surimi", "imitation crab",
                        "clam", "oyster", "mussel", "scallop", "prawn"]
    text_lower = ingredients.lower()
    found_any = False
    for term in shellfish_terms:
        if term in text_lower:
            print(f"  FOUND: '{term}'")
            found_any = True
    if not found_any:
        print("  No shellfish-related terms found anywhere in the text.")
        print("  -> shellfish result appears correct for this product.")

if __name__ == "__main__":
    lookup_single_record()
