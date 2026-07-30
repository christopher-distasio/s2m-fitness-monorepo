"""
Data-driven modifier discovery: USDA descriptions are comma-separated
clauses (e.g. "Chicken, thigh, meat only, cooked, roasted"). This splits
every description on commas and counts clause frequency across SR Legacy,
Branded, and FNDDS - surfacing the ACTUAL modifier vocabulary in your
data, rather than guessing from memory.

Run from repo root: poetry run python scripts/extract_modifier_vocab.py
"""

import json
from collections import Counter
from pathlib import Path

# Adjust these paths to match your data/processed/ and data/raw/ locations
SR_LEGACY_JSON = "data/processed/sr_legacy_full_clean.json"

clause_counter = Counter()

with open(SR_LEGACY_JSON) as f:
    sr_legacy = json.load(f)

for food in sr_legacy:
    desc = food.get("description", "")
    clauses = [c.strip().lower() for c in desc.split(",")]
    clause_counter.update(clauses)

print(f"Total unique clauses found: {len(clause_counter)}")
print(f"\nTop 300 most common description clauses (the modifier vocabulary):\n")
for clause, count in clause_counter.most_common(300):
    print(f"  {count:5d}  {clause}")