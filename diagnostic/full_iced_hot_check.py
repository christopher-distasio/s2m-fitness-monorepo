"""
Pull the COMPLETE list of matches for 'iced' and 'hot' in SR Legacy
(not just a sample), so we can build a comprehensive, accurate exclusion
list rather than guessing from partial data.

Run from repo root: poetry run python scripts/full_iced_hot_check.py
"""

import re
import pandas as pd
from pathlib import Path

SR_LEGACY_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_sr_legacy_food_csv_2018-04"

food_desc = pd.read_csv(f"{SR_LEGACY_DIR}/food.csv")[["fdc_id", "description"]]


def word_match(term, text):
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


for word in ["iced", "hot"]:
    matched = [
        desc for desc in food_desc["description"].dropna()
        if word_match(word, desc.lower())
    ]
    print(f"\n{'='*70}")
    print(f"ALL '{word}' matches ({len(matched)} total)")
    print(f"{'='*70}")
    for desc in matched:
        print(f"    {desc}")