"""
Analyze FNDDS food descriptions for the same risky collision words we
found problems with in SR Legacy ("hot", "light", "iced", etc.) -- to
check whether FNDDS has its own version of the same false-positive
matching issues before finalizing the modifier extraction logic.

Run from repo root: poetry run python scripts/analyze_fndds_ambiguity.py
"""

import re
import pandas as pd
from pathlib import Path

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"

survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")

RISKY_WORDS = [
    "whole", "sweet", "light", "raw", "hot", "iced", "plain",
    "coated", "flavored", "diet", "fresh", "diced", "sliced",
]


def word_match(term, text):
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


print("=" * 70)
print("FNDDS RISKY WORD CONTEXT CHECK (all matches, word-boundary only)")
print("=" * 70)

for word in RISKY_WORDS:
    matched_descs = [
        desc for desc in foods["description"].dropna()
        if word_match(word, desc.lower())
    ]
    print(f"\n'{word}': {len(matched_descs)} word-boundary matches")
    # Print ALL matches if <= 15, otherwise a sample of 15
    to_show = matched_descs if len(matched_descs) <= 15 else matched_descs[:15]
    for desc in to_show:
        print(f"    {desc}")
    if len(matched_descs) > 15:
        print(f"    ... and {len(matched_descs) - 15} more")