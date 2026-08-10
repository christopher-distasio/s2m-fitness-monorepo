"""
Spot-check: Find actual descriptions containing sesame or shellfish keywords.
"""

import pandas as pd

csv_path = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv"

print("Loading Branded Foods...")
df = pd.read_csv(csv_path, low_memory=False)
descriptions = df["description"].dropna()

print(f"Total: {len(descriptions)}\n")

# Search for sesame
print("=" * 80)
print("SESAME KEYWORD SEARCH")
print("=" * 80)

sesame_patterns = ["sesame", "tahini", "sesame-free", "sesame free"]
sesame_matches = []

for pattern in sesame_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, na=False)]
    print(f"\n'{pattern}': {len(matches)} matches")
    if len(matches) > 0:
        print("  Examples:")
        for desc in matches.head(5).values:
            print(f"    - {desc}")
        sesame_matches.extend(matches.tolist())

print(f"\nTotal unique sesame-related: {len(set(sesame_matches))}")

# Search for shellfish
print("\n" + "=" * 80)
print("SHELLFISH KEYWORD SEARCH")
print("=" * 80)

shellfish_patterns = ["shellfish", "shrimp", "crab", "lobster", "crayfish", "crustacean", "mollusc", "oyster", "clam", "mussel"]
shellfish_matches = []

for pattern in shellfish_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, na=False)]
    print(f"\n'{pattern}': {len(matches)} matches")
    if len(matches) > 0:
        print("  Examples:")
        for desc in matches.head(3).values:
            print(f"    - {desc}")
        shellfish_matches.extend(matches.tolist())

print(f"\nTotal unique shellfish-related: {len(set(shellfish_matches))}")

# Negation search (free from...)
print("\n" + "=" * 80)
print("NEGATION PATTERNS (free from...)")
print("=" * 80)

negation_patterns = [
    "shellfish-?free",
    "shellfish free",
    "no shellfish",
    "without shellfish",
    "free from shellfish",
    "sesame-?free",
    "sesame free",
    "no sesame",
    "without sesame",
]

for pattern in negation_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, regex=True, na=False)]
    print(f"'{pattern}': {len(matches)} matches")
    if len(matches) > 0:
        for desc in matches.head(2).values:
            print(f"  - {desc}")
