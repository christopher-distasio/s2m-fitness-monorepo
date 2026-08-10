"""
Discovery scan: how often do various dietary/certification claim terms
actually appear in Branded Foods descriptions?

This does NOT assume any particular set of flags matters -- it checks a
broad candidate list drawn from common food-labeling categories, so we can
see real frequency data before deciding what's worth building extraction
for. Anything with negligible hits gets dropped; anything with real
volume becomes a candidate for extraction.

Run from repo root: poetry run python scripts/scan_branded_dietary_terms.py
"""

import re
import pandas as pd
from pathlib import Path

BRANDED_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_branded_food_csv_2026-04-30"

branded_extra = pd.read_csv(f"{BRANDED_DIR}/branded_food.csv")
us_mask = branded_extra["market_country"].astype(str).str.strip() == "United States"
us_fdc_ids = set(branded_extra.loc[us_mask, "fdc_id"].astype(str))

food_desc_all = pd.read_csv(f"{BRANDED_DIR}/food.csv")
food_desc = food_desc_all[food_desc_all["fdc_id"].astype(str).isin(us_fdc_ids)][["fdc_id", "description"]]

# Broad candidate list -- common food-labeling/dietary-claim categories,
# not assumed to all be relevant. This is a starting net, not a final list.
CANDIDATE_TERMS = [
    "organic", "gluten free", "gluten-free", "non gmo", "non-gmo",
    "sugar free", "sugar-free", "no sugar added", "unsweetened",
    "reduced fat", "low fat", "fat free", "fat-free", "nonfat",
    "vegan", "vegetarian", "kosher", "halal",
    "dairy free", "dairy-free", "lactose free", "lactose-free",
    "low sodium", "reduced sodium", "no salt added", "unsalted",
    "keto", "paleo", "whole30",
    "high protein", "low carb", "low-carb",
    "no artificial", "all natural", "natural flavor",
    "made with real", "no preservatives",
    "cage free", "cage-free", "grass fed", "grass-fed",
    "free range", "free-range",
    "non dairy", "non-dairy", "plant based", "plant-based",
]


def phrase_match(term, text):
    """Whole-word/phrase match, same approach as the modifier extraction scripts."""
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


print("=" * 70)
print("DIETARY/CERTIFICATION CLAIM TERM FREQUENCY (US Branded Foods)")
print("=" * 70)
print(f"Total US records scanned: {len(food_desc):,}\n")

results = {}
for term in CANDIDATE_TERMS:
    count = sum(
        1 for desc in food_desc["description"].dropna()
        if phrase_match(term, desc.lower())
    )
    results[term] = count

for term, count in sorted(results.items(), key=lambda x: -x[1]):
    pct = 100 * count / len(food_desc)
    print(f"  {count:7,d}  ({pct:5.2f}%)  {term}")

# Also check the not_a_significant_source_of field, which per
# process_branded.py already contains structured USDA data about nutrient
# claims -- this might make some extraction unnecessary if it's already
# structured rather than free text.
print("\n" + "=" * 70)
print("SAMPLE OF 'not_a_significant_source_of' FIELD (already-structured data)")
print("=" * 70)
sample = branded_extra.loc[us_mask, "not_a_significant_source_of"].dropna()
sample = sample[sample.str.strip() != ""]
print(f"Non-empty values: {len(sample):,} out of {us_mask.sum():,} US records\n")
for val in sample.head(10):
    print(f"    {val}")