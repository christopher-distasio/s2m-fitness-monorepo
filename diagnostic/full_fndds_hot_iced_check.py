"""
Pull the COMPLETE list of 'hot' and 'iced' matches in FNDDS descriptions
to determine exactly what (if anything) needs excluding, given that
FNDDS was already fully processed with the pre-fix version of the
extraction script.

Run from repo root: poetry run python scripts/full_fndds_hot_iced_check.py
"""

import re
import pandas as pd
from pathlib import Path

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"

survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")


def word_match(term, text):
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


for word in ["hot", "iced"]:
    matched = foods[foods["description"].apply(
        lambda d: word_match(word, str(d).lower()) if pd.notna(d) else False
    )]
    print(f"\n{'='*70}")
    print(f"ALL '{word}' matches in FNDDS ({len(matched)} total)")
    print(f"{'='*70}")
    for _, row in matched.iterrows():
        print(f"    {row['fdc_id']}: {row['description']}")