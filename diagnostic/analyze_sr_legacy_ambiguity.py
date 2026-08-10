"""
Analyze SR Legacy food descriptions for:
1. Ambiguity phrases similar to FNDDS's "NS as to X" pattern (e.g. "not
   specified", "unspecified", "all classes", "mixed species", "NFS")
2. Real-world context for our known risky collision words (whole, sweet,
   light, raw, hot, iced, plain, coated, flavored, diet) -- to check
   whether SR Legacy's vocabulary creates NEW collisions we haven't
   already handled, or whether the existing word-boundary + exclusion
   logic is likely sufficient as-is.

Adjust SR_LEGACY_DIR below to point at your actual SR Legacy raw data
folder before running.

Run from repo root: poetry run python scripts/analyze_sr_legacy_ambiguity.py
"""

import re
import pandas as pd
from pathlib import Path

# TODO: update this to your actual SR Legacy folder name under data/raw/
SR_LEGACY_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_sr_legacy_food_csv_2018-04"
food_desc = pd.read_csv(f"{SR_LEGACY_DIR}/food.csv")[["fdc_id", "description"]]

# ============================================================================
# PART 1: Ambiguity phrase scan
# ============================================================================

AMBIGUITY_PHRASES = [
    "ns as to",
    "not specified",
    "unspecified",
    "not further specified",
    "nfs",
    "all classes",
    "mixed species",
    "all grades",
    "unknown",
    "n.s.",
]

print("=" * 70)
print("PART 1: AMBIGUITY PHRASE SCAN (FNDDS-style 'NS' equivalents)")
print("=" * 70)

for phrase in AMBIGUITY_PHRASES:
    matches = food_desc[food_desc["description"].str.lower().str.contains(re.escape(phrase), na=False)]
    print(f"\n'{phrase}': {len(matches)} matches")
    for desc in matches["description"].head(5):
        print(f"    {desc}")

# ============================================================================
# PART 2: Known risky collision words -- check SR Legacy context
# ============================================================================

RISKY_WORDS = [
    "whole", "sweet", "light", "raw", "hot", "iced", "plain",
    "coated", "flavored", "diet", "fresh", "diced", "sliced",
]


def word_match(term, text):
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


print("\n" + "=" * 70)
print("PART 2: RISKY WORD CONTEXT CHECK (word-boundary matches only)")
print("=" * 70)

for word in RISKY_WORDS:
    matched_descs = [
        desc for desc in food_desc["description"].dropna()
        if word_match(word, desc.lower())
    ]
    print(f"\n'{word}': {len(matched_descs)} word-boundary matches (sample below)")
    for desc in matched_descs[:8]:
        print(f"    {desc}")