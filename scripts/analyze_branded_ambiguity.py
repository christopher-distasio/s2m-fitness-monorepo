"""
Analyze Branded Foods descriptions for:
1. Overall landscape -- top brand owners, top food categories -- since
   Branded Foods is structurally different from SR Legacy/FNDDS (commercial
   product names like "Chobani Greek Yogurt, Strawberry" rather than USDA's
   structured modifier vocabulary like "grilled, skin eaten, trimmed to
   1/4in fat"). This tells us upfront how much the existing modifier
   ontology even applies here, before writing any extraction code.
2. The same risky collision words that caused real bugs in SR Legacy/FNDDS
   (hot, iced, light, whole, sweet, plain, coated, flavored, diet, fresh,
   diced, sliced) -- to see whether Branded Foods has its own version of
   these false-positive patterns, or different ones entirely.

Path and column names confirmed against process_branded.py:
  - BRANDED_DIR matches process_branded.py's EXTRACT_DIR
    (FoodData_Central_branded_food_csv_2026-04-30)
  - branded_food.csv has brand_owner and branded_food_category columns,
    confirmed directly in process_branded.py's own field mapping

US-ONLY FILTERING: process_branded.py filters to market_country ==
"United States" before doing anything else with the data (non-US entries
never make it into your actual embedded/processed dataset). This script
applies the same filter first, so the word-frequency and brand/category
breakdown below reflects the same subset that'll actually get modifier-
tagged -- not skewed by foreign-market entries that won't be used anyway.

Run from repo root: poetry run python scripts/analyze_branded_ambiguity.py
"""

import re
import pandas as pd
from pathlib import Path

BRANDED_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_branded_food_csv_2026-04-30"

# ============================================================================
# Load + filter to US-only, matching process_branded.py's behavior exactly
# ============================================================================

branded_extra = pd.read_csv(f"{BRANDED_DIR}/branded_food.csv")
us_mask = branded_extra["market_country"].astype(str).str.strip() == "United States"
us_fdc_ids = set(branded_extra.loc[us_mask, "fdc_id"].astype(str))
branded_extra_us = branded_extra.loc[us_mask]

print(f"Total branded_food.csv rows: {len(branded_extra):,}")
print(f"US-market rows: {len(branded_extra_us):,}")

food_desc_all = pd.read_csv(f"{BRANDED_DIR}/food.csv")
food_desc = food_desc_all[food_desc_all["fdc_id"].astype(str).isin(us_fdc_ids)][["fdc_id", "description"]]

# ============================================================================
# PART 1: Landscape overview -- how different is this dataset, structurally?
# ============================================================================

print("\n" + "=" * 70)
print("PART 1: BRANDED FOODS LANDSCAPE OVERVIEW (US-market only)")
print("=" * 70)

print(f"\nTotal US records: {len(food_desc)}")
print("\nSample descriptions (first 15):")
for desc in food_desc["description"].head(15):
    print(f"    {desc}")

print("\n" + "-" * 70)
print("TOP 20 BRAND OWNERS (by record count)")
print("-" * 70)
print(branded_extra_us["brand_owner"].value_counts().head(20))

print("\n" + "-" * 70)
print("TOP 20 FOOD CATEGORIES (by record count)")
print("-" * 70)
print(branded_extra_us["branded_food_category"].value_counts().head(20))

# ============================================================================
# PART 2: Word frequency in descriptions (mirrors the original SR
# Legacy/FNDDS frequency-list approach from the start of this project)
# ============================================================================

print("\n" + "=" * 70)
print("PART 2: TOP 300 MOST FREQUENT WORDS IN DESCRIPTIONS")
print("=" * 70)
print("(Helps gauge how much this looks like USDA modifier vocabulary")
print(" vs. brand/product-line language)\n")

word_counts = {}
for desc in food_desc["description"].dropna():
    words = re.findall(r"[a-z']+", desc.lower())
    for w in words:
        if len(w) < 3:
            continue
        word_counts[w] = word_counts.get(w, 0) + 1

for word, count in sorted(word_counts.items(), key=lambda x: -x[1])[:300]:
    print(f"  {count:6d}  {word}")

# ============================================================================
# PART 3: Known risky collision words -- check Branded Foods context
# ============================================================================

RISKY_WORDS = [
    "whole", "sweet", "light", "raw", "hot", "iced", "plain",
    "coated", "flavored", "diet", "fresh", "diced", "sliced",
]


def word_match(term, text):
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


print("\n" + "=" * 70)
print("PART 3: RISKY WORD CONTEXT CHECK (word-boundary matches only)")
print("=" * 70)

for word in RISKY_WORDS:
    matched_descs = [
        desc for desc in food_desc["description"].dropna()
        if word_match(word, desc.lower())
    ]
    print(f"\n'{word}': {len(matched_descs)} word-boundary matches (sample below)")
    for desc in matched_descs[:8]:
        print(f"    {desc}")
