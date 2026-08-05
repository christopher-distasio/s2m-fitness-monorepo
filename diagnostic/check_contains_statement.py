"""
Check how often ingredients text contains an inline "CONTAINS:" allergen statement.
This determines whether we can reliably extract FREE (verified-safe) states.
"""

import pandas as pd
import re

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"

def check_contains_statement():
    print(f"Loading {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH, low_memory=False, usecols=["fdc_id", "ingredients"])
    
    ingredients = df["ingredients"].dropna()
    
    # Pattern: "CONTAINS:" followed directly by allergen names —
    # explicitly excludes "CONTAINS LESS THAN X%" which is a quantity disclaimer, not an allergen statement
    contains_pattern = re.compile(r'CONTAINS:?\s+(?!LESS THAN)[A-Z]', re.IGNORECASE)
    
    matches = ingredients[ingredients.str.contains(contains_pattern, regex=True, na=False)]
    
    print("=" * 80)
    print("INLINE 'CONTAINS:' STATEMENT CHECK")
    print("=" * 80)
    print(f"\nTotal ingredients records: {len(ingredients):,}")
    print(f"Records with 'CONTAINS' pattern: {len(matches):,} ({100*len(matches)/len(ingredients):.1f}%)")
    
    print(f"\nSample matches (showing the CONTAINS portion):\n")
    count = 0
    for idx, text in matches.items():
        # Find and show just the CONTAINS clause + some context
        match = contains_pattern.search(text)
        if match:
            start = match.start()
            snippet = text[start:start+120]
            print(f"  {count+1}. ...{snippet}...")
            count += 1
        if count >= 10:
            break
    
    # Also check "may contain" separately -- different confidence level
    may_contain_pattern = re.compile(r'MAY CONTAIN', re.IGNORECASE)
    may_matches = ingredients[ingredients.str.contains(may_contain_pattern, regex=True, na=False)]
    print(f"\n\nRecords with 'MAY CONTAIN' (cross-contamination warning): {len(may_matches):,} ({100*len(may_matches)/len(ingredients):.1f}%)")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    check_contains_statement()