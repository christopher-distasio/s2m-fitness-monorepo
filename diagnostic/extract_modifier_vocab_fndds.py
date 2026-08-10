"""
Same modifier-vocabulary extraction as extract_modifier_vocab.py, but for
FNDDS descriptions (from food.csv, joined via survey_fndds_food.csv).
FNDDS descriptions are more free-text/conversational than SR Legacy's
strict comma-clause style, so this may surface different vocabulary -
useful since FNDDS is closer to how people actually describe food.

Run from repo root: poetry run python scripts/extract_modifier_vocab_fndds.py
"""

import pandas as pd
from collections import Counter

FNDDS_DIR = "data/raw/FoodData_Central_survey_food_csv_2024-10-31"

survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
foods = survey_map.merge(food_desc, on="fdc_id", how="left")

clause_counter = Counter()

for desc in foods["description"].dropna():
    clauses = [c.strip().lower() for c in desc.split(",")]
    clause_counter.update(clauses)

print(f"Total unique clauses found: {len(clause_counter)}")
print(f"\nTop 300 most common description clauses (cutoff around freq 20 per SR Legacy pass):\n")
for clause, count in clause_counter.most_common(300):
    print(f"  {count:5d}  {clause}")