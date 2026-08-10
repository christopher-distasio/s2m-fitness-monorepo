"""
Schema diff for FoodData_Central_branded_food_csv — inspect structure.

Confirms presence of critical columns and shows sample data.
"""

import pandas as pd
import os
from pathlib import Path

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"

def schema_diff():
    if not os.path.exists(CSV_PATH):
        print(f"❌ File not found: {CSV_PATH}")
        return
    
    print(f"Loading {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH, low_memory=False)
    
    print("=" * 80)
    print("SCHEMA DIFF: branded_food.csv")
    print("=" * 80)
    
    # Basic info
    print(f"\nTotal records: {len(df):,}")
    print(f"Total columns: {len(df.columns)}")
    
    # All columns
    print("\n" + "=" * 80)
    print("ALL COLUMNS")
    print("=" * 80)
    for i, col in enumerate(df.columns, 1):
        print(f"{i:2d}. {col}")
    
    # Critical columns check
    print("\n" + "=" * 80)
    print("CRITICAL COLUMNS FOR ALLERGEN EXTRACTION")
    print("=" * 80)
    
    critical = ["fdc_id", "ingredients", "not_a_significant_source_of"]
    for col in critical:
        if col in df.columns:
            print(f"✅ {col}")
        else:
            print(f"❌ {col} — NOT FOUND")
    
    # Data quality: fdc_id
    print("\n" + "=" * 80)
    print("fdc_id (join key)")
    print("=" * 80)
    print(f"Nulls: {df['fdc_id'].isna().sum():,}")
    print(f"Unique: {df['fdc_id'].nunique():,}")
    print(f"Sample values:")
    for val in df['fdc_id'].head(3):
        print(f"  {val}")
    
    # Data quality: ingredients
    if "ingredients" in df.columns:
        print("\n" + "=" * 80)
        print("ingredients (free text — PRIMARY SOURCE)")
        print("=" * 80)
        print(f"Nulls: {df['ingredients'].isna().sum():,}")
        print(f"Blank strings: {(df['ingredients'].fillna('').str.strip() == '').sum():,}")
        print(f"Non-null: {df['ingredients'].notna().sum():,}")
        print(f"Avg length: {df['ingredients'].str.len().mean():.0f} chars")
        print(f"\nSample ingredients (first 5 non-null):")
        for i, ing in enumerate(df[df['ingredients'].notna()]['ingredients'].head(5), 1):
            # Truncate to 100 chars for readability
            ing_short = ing[:100] + "..." if len(ing) > 100 else ing
            print(f"  {i}. {ing_short}")
    else:
        print("\n❌ ingredients column not found")
    
    # Data quality: not_a_significant_source_of
    if "not_a_significant_source_of" in df.columns:
        print("\n" + "=" * 80)
        print("not_a_significant_source_of (negative claims)")
        print("=" * 80)
        print(f"Nulls: {df['not_a_significant_source_of'].isna().sum():,}")
        print(f"Blank strings: {(df['not_a_significant_source_of'].fillna('').str.strip() == '').sum():,}")
        print(f"Non-null: {df['not_a_significant_source_of'].notna().sum():,}")
        print(f"Unique values: {df['not_a_significant_source_of'].nunique()}")
        print(f"\nSample values (first 5 non-null):")
        for i, val in enumerate(df[df['not_a_significant_source_of'].notna()]['not_a_significant_source_of'].head(5), 1):
            val_short = val[:80] + "..." if len(val) > 80 else val
            print(f"  {i}. {val_short}")
    else:
        print("\n❌ not_a_significant_source_of column not found")
    
    # Check for allergen-related columns
    print("\n" + "=" * 80)
    print("ALLERGEN-RELATED COLUMNS (if any)")
    print("=" * 80)
    allergen_keywords = ["allergen", "contains", "may contain", "free", "gluten", "dairy", "peanut", "nut"]
    found_allergen_cols = [col for col in df.columns if any(kw in col.lower() for kw in allergen_keywords)]
    
    if found_allergen_cols:
        for col in found_allergen_cols:
            print(f"  {col}")
    else:
        print("  (None found)")
    
    # Data completeness summary
    print("\n" + "=" * 80)
    print("DATA COMPLETENESS")
    print("=" * 80)
    print(f"Records with ingredients data: {df['ingredients'].notna().sum():,} ({100 * df['ingredients'].notna().sum() / len(df):.1f}%)")
    if "not_a_significant_source_of" in df.columns:
        print(f"Records with not_a_significant_source_of: {df['not_a_significant_source_of'].notna().sum():,} ({100 * df['not_a_significant_source_of'].notna().sum() / len(df):.1f}%)")
    
    print("\n" + "=" * 80)
    print("END SCHEMA DIFF")
    print("=" * 80)

if __name__ == "__main__":
    schema_diff()