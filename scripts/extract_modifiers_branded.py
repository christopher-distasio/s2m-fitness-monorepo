"""
Extract modifiers from Branded Foods descriptions and patch them into Pinecone.

Based on spot-check findings:
- Extract EXPLICIT claims (vegan, gluten-free, organic, keto, etc.)
- Skip INFERENTIAL allergen-free claims (sesame-free, shellfish-free) — brands don't label these
- User preferences will handle medical allergen tracking

This script:
1. Loads Branded Foods descriptions
2. Parses to identify canonical modifiers (vegan, vegetarian, kosher, halal, etc.)
3. Patches modifier metadata onto existing Pinecone records using index.update()

IMPORTANT:
Every record gets ALL modifier categories (NONE sentinel for non-matches).
This ensures clean overwrites instead of partial patches that leave stale values.

Pinecone metadata values must be strings, numbers, booleans, or lists of strings.
Each modifier category is a top-level metadata field (not nested under "modifiers").

Resume support: set RESUME_OFFSET if interrupted.
"""

import os
import re
import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone
from pathlib import Path

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

BRANDED_FOODS_CSV = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv"
RESUME_OFFSET = 0
TEST_MODE = False
TEST_LIMIT = 50

NONE_VALUE = "NONE"

# ============================================================================
# MODIFIER MAPPINGS (Refined from spot-check)
# ============================================================================

# Tier 1: Hard Constraints (explicit claims only)
DIETARY_RESTRICTIONS_MAP = {
    "vegan": ["vegan"],
    "vegetarian": ["vegetarian"],
    "kosher": ["kosher"],
    "halal": ["halal"],
}

ALLERGEN_CLAIMS_MAP = {
    "gluten_free": ["gluten-?free", "gluten free"],
    "dairy_free": ["dairy-?free", "dairy free", "milk-?free", "milk free"],
    "soy_free": ["soy-?free", "soy free"],
    "nut_free": ["nut-?free", "nut free", "tree.{0,5}nut-?free"],
}

# Tier 2: Preferences (explicit claims)
NUTRITIONAL_CLAIMS_MAP = {
    "keto": ["keto", "keto-?friendly"],
    "low_carb": ["low-?carb", "low carb"],
    "paleo": ["paleo"],
    "organic": ["organic"],
    "non_gmo": ["non-?gmo", "gmo-?free"],
    "sugar_free": ["sugar-?free", "sugar free", "no sugar", "unsweetened"],
    "low_sodium": ["low sodium", "unsalted", "no salt", "salt-?free", "reduced sodium"],
    "low_fat": ["fat-?free", "low fat", "low-?fat", "nonfat", "reduced fat"],
}

QUALITY_CLAIMS_MAP = {
    "grass_fed": ["grass-?fed"],
    "pasture_raised": ["pasture-?raised"],
    "cage_free": ["cage-?free"],
}

ALL_MAPPINGS = {
    **DIETARY_RESTRICTIONS_MAP,
    **ALLERGEN_CLAIMS_MAP,
    **NUTRITIONAL_CLAIMS_MAP,
    **QUALITY_CLAIMS_MAP,
}

# Exclusions to avoid false positives
EXCLUSIONS = {
    # None needed yet based on spot-check; add as edge cases appear
}


def word_match(term: str, text: str) -> bool:
    """
    Match term as whole word/phrase within text (not substring).
    Handles hyphens and multi-word phrases correctly.
    """
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text, re.IGNORECASE) is not None


def extract_modifiers(description: str) -> dict:
    """
    Parse a Branded Foods description and extract modifiers.
    
    Returns a dict with all modifier categories present (even if not matched).
    Non-matches use NONE_VALUE sentinel.
    """
    desc_lower = (description or "").lower().strip()
    
    # Start every category at NONE_VALUE
    modifiers = {modifier_name: NONE_VALUE for modifier_name in ALL_MAPPINGS}
    
    # For each modifier, check if any of its patterns match
    for modifier_name, patterns in ALL_MAPPINGS.items():
        for pattern in patterns:
            # Try regex first, then word_match as fallback
            try:
                if re.search(pattern, desc_lower, re.IGNORECASE):
                    modifiers[modifier_name] = modifier_name  # Value is the modifier name itself (boolean-like)
                    break
            except re.error:
                if word_match(pattern, desc_lower):
                    modifiers[modifier_name] = modifier_name
                    break
    
    return modifiers


def main():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index("food-index")
    
    print(f"Loading Branded Foods from: {BRANDED_FOODS_CSV}")
    df = pd.read_csv(BRANDED_FOODS_CSV, low_memory=False)
    
    # Extract fdc_id and description
    records = df[["fdc_id", "description"]].dropna(subset=["description"]).to_dict("records")
    records = records[RESUME_OFFSET:]
    
    if TEST_MODE:
        records = records[:TEST_LIMIT]
        print(f"TEST_MODE on — running {len(records)} records only")
    
    print(f"Processing {len(records):,} records...\n")
    
    batch_size = 100
    modifier_counts = {}
    updated_count = 0
    
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        
        for row in batch:
            fdc_id = row["fdc_id"]
            description = row["description"]
            
            modifiers = extract_modifiers(description)
            
            # Count non-NONE matches for summary
            for category, value in modifiers.items():
                if value == NONE_VALUE:
                    continue
                if category not in modifier_counts:
                    modifier_counts[category] = {}
                if value not in modifier_counts[category]:
                    modifier_counts[category][value] = 0
                modifier_counts[category][value] += 1
            
            # Patch to Pinecone: full overwrite of all modifier categories
            # ID prefix "branded-" matches the embedding script convention
            index.update(
                id=f"branded-{fdc_id}",
                set_metadata=modifiers,
            )
            updated_count += 1
        
        print(f"Processed batch {i // batch_size + 1}: {len(batch)} records (total: {updated_count:,})")
    
    print(f"\nTotal records updated: {updated_count:,}")
    
    print("\n" + "=" * 80)
    print("MODIFIER EXTRACTION SUMMARY (matches only, NONE excluded)")
    print("=" * 80)
    
    for category in sorted(modifier_counts.keys()):
        values = modifier_counts[category]
        print(f"\n{category}:")
        for value, count in sorted(values.items(), key=lambda x: -x[1]):
            pct = (count / updated_count) * 100 if updated_count > 0 else 0
            print(f"  {value:30} {count:6,} ({pct:5.2f}%)")


if __name__ == "__main__":
    main()