"""
Discover dietary modifiers in Branded Foods descriptions.

Scans ~460k Branded Foods descriptions for Tier 1 (hard constraints) and Tier 2 
(preferences) modifiers. Outputs frequency distribution to CSV for validation 
before extraction.

Matches the word-boundary regex logic used by database-side extractors.
"""

import os
import re
import pandas as pd
from pathlib import Path
from collections import defaultdict

# ============================================================================
# MODIFIER SEARCH TERMS (from multi-AI synthesis)
# ============================================================================

TIER_1_MODIFIERS = {
    # FDA Major Allergens
    "dairy_free": [
        "dairy-?free", "dairy free", "no dairy", "without dairy",
        "milk-?free", "milk free", "no milk", "without milk",
        "lactose-?free", "lactose free", "no lactose"
    ],
    "egg_free": ["egg-?free", "egg free", "no eggs", "without eggs", "eggless"],
    "peanut_free": ["peanut-?free", "peanut free", "no peanuts", "without peanuts"],
    "tree_nut_free": [
        "tree nut-?free", "tree nut free", "tree nuts-?free",
        "nut-?free", "nut free", "no nuts", "without nuts", "nutless"
    ],
    "wheat_free": ["wheat-?free", "wheat free", "no wheat", "without wheat"],
    "soy_free": ["soy-?free", "soy free", "no soy", "without soy"],
    "sesame_free": ["sesame-?free", "sesame free", "no sesame", "without sesame"],
    "fish_free": ["fish-?free", "fish free", "no fish", "without fish"],
    "shellfish_free": [
        "shellfish-?free", "shellfish free", "crustacean-?free", "crustacean free",
        "shrimp-?free", "crab-?free", "lobster-?free"
    ],
    
    # Medical
    "gluten_free": ["gluten-?free", "gluten free", "no gluten", "without gluten", "celiac"],
    "sulfite_free": ["sulfite-?free", "sulfite free", "no sulfites", "without sulfites"],
    
    # Ethical/Religious
    "vegan": [r"\bvegan\b"],
    "vegetarian": [r"\bvegetarian\b"],
    "kosher": [r"\bkosher\b"],
    "halal": [r"\bhalal\b"],
}

TIER_2_MODIFIERS = {
    # Preferences
    "keto": [r"\bketo\b", "keto-?friendly", "keto friendly", "ketogenic"],
    "low_carb": ["low-?carb", "low carb", "low-carb", "low-?carbohydrate"],
    "paleo": [r"\bpaleo\b", "paleo-?friendly"],
    "organic": [r"\borganic\b"],
    "non_gmo": ["non-?gmo", "non gmo", "gmo-?free", "gmo free"],
    "grass_fed": ["grass-?fed", "grass fed"],
    "pasture_raised": ["pasture-?raised", "pasture raised"],
    "cage_free": ["cage-?free", "cage free", "free-?range", "free range"],
    
    # Optional user preferences (note: extracted but low reliability from text)
    "low_fodmap": ["low-?fodmap", "low fodmap", "fodmap-?friendly"],
    "nightshade_free": ["nightshade-?free", "nightshade free"],
    "histamine_friendly": ["low-?histamine", "low histamine", "histamine-?friendly"],
}

def word_match(term: str, text: str) -> bool:
    """
    Match term as whole word/phrase (not substring).
    Uses word-boundary regex: handles hyphens and multi-word phrases.
    """
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


def extract_keywords(description: str, modifiers_dict: dict) -> dict:
    """
    Find all matching modifiers in a description.
    Returns {modifier_name: True/False} for each category.
    """
    desc_lower = (description or "").lower().strip()
    matches = {}
    
    for modifier_name, patterns in modifiers_dict.items():
        found = False
        for pattern in patterns:
            # Some patterns are plain regex (like \bvegan\b), others are plain terms
            try:
                if re.search(pattern, desc_lower, re.IGNORECASE):
                    found = True
                    break
            except re.error:
                # Fallback to word_match if regex fails
                if word_match(pattern, desc_lower):
                    found = True
                    break
        
        matches[modifier_name] = found
    
    return matches


def discover_modifiers(csv_path: str, output_csv: str):
    """
    Scan Branded Foods CSV for all Tier 1 + Tier 2 modifiers.
    Output: CSV with frequency distribution.
    """
    
    print(f"Loading Branded Foods from: {csv_path}")
    df = pd.read_csv(csv_path, dtype={"description": str})
    descriptions = df["description"].dropna()
    
    print(f"Total descriptions: {len(descriptions)}")
    
    # Aggregate results
    tier_1_counts = defaultdict(int)
    tier_2_counts = defaultdict(int)
    total_scanned = 0
    
    # Scan descriptions
    for i, desc in enumerate(descriptions):
        if i % 50000 == 0 and i > 0:
            print(f"  Processed {i:,} descriptions...")
        
        tier_1_matches = extract_keywords(desc, TIER_1_MODIFIERS)
        tier_2_matches = extract_keywords(desc, TIER_2_MODIFIERS)
        
        for modifier, found in tier_1_matches.items():
            if found:
                tier_1_counts[modifier] += 1
        
        for modifier, found in tier_2_matches.items():
            if found:
                tier_2_counts[modifier] += 1
        
        total_scanned += 1
    
    print(f"\nScanned {total_scanned:,} descriptions.")
    
    # Build output DataFrame
    results = []
    
    print("\n" + "=" * 80)
    print("TIER 1 (Hard Constraints)")
    print("=" * 80)
    for modifier in sorted(TIER_1_MODIFIERS.keys()):
        count = tier_1_counts[modifier]
        pct = (count / total_scanned) * 100 if total_scanned > 0 else 0
        print(f"  {modifier:25} {count:6,} ({pct:5.2f}%)")
        results.append({
            "tier": "Tier 1",
            "modifier": modifier,
            "count": count,
            "percentage": pct,
            "per_100k": (count / total_scanned) * 100000 if total_scanned > 0 else 0
        })
    
    print("\n" + "=" * 80)
    print("TIER 2 (Preferences)")
    print("=" * 80)
    for modifier in sorted(TIER_2_MODIFIERS.keys()):
        count = tier_2_counts[modifier]
        pct = (count / total_scanned) * 100 if total_scanned > 0 else 0
        print(f"  {modifier:25} {count:6,} ({pct:5.2f}%)")
        results.append({
            "tier": "Tier 2",
            "modifier": modifier,
            "count": count,
            "percentage": pct,
            "per_100k": (count / total_scanned) * 100000 if total_scanned > 0 else 0
        })
    
    # Write CSV
    output_df = pd.DataFrame(results)
    output_df = output_df.sort_values(["tier", "count"], ascending=[True, False])
    output_df.to_csv(output_csv, index=False)
    
    print("\n" + "=" * 80)
    print(f"Results saved to: {output_csv}")
    print("=" * 80)
    
    # Summary stats
    tier_1_total = sum(tier_1_counts.values())
    tier_2_total = sum(tier_2_counts.values())
    print(f"\nSummary:")
    print(f"  Total Tier 1 matches: {tier_1_total:,}")
    print(f"  Total Tier 2 matches: {tier_2_total:,}")
    print(f"  Combined: {tier_1_total + tier_2_total:,}")


if __name__ == "__main__":
    # Adjust paths to your local setup
    # Find the Branded Foods CSV in your data/raw/ directory
    
    # Possible paths (check which exists):
    possible_paths = [
        "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv"
    ]
    
    csv_path = None
    for p in possible_paths:
        if os.path.exists(p):
            csv_path = p
            break
    
    if csv_path is None:
        print("ERROR: Could not find Branded Foods CSV.")
        print("Checked:")
        for p in possible_paths:
            print(f"  - {p}")
        exit(1)
    
    output_csv = "diagnostic/dietary_keywords_branded.csv"
    os.makedirs("diagnostic", exist_ok=True)
    
    discover_modifiers(csv_path, output_csv)