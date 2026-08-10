"""
Spot-check: Find descriptions containing nutritional modifier claims.
Validates whether these claims exist in text before deciding extraction method.
"""

import pandas as pd

csv_path = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv"

print("Loading Branded Foods...")
df = pd.read_csv(csv_path, low_memory=False)
descriptions = df["description"].dropna()

print(f"Total: {len(descriptions)}\n")

# ============================================================================
# LOW SUGAR / SUGAR-FREE
# ============================================================================
print("=" * 80)
print("LOW SUGAR / SUGAR-FREE CLAIMS")
print("=" * 80)

sugar_patterns = [
    "sugar-?free",
    "sugar free",
    "no sugar",
    "without sugar",
    "low sugar",
    "reduced sugar",
    "unsweetened"
]

sugar_matches = []
for pattern in sugar_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, regex=True, na=False)]
    print(f"\n'{pattern}': {len(matches):6,} matches")
    if len(matches) > 0:
        print("  Examples:")
        for desc in matches.head(3).values:
            print(f"    - {desc}")
    sugar_matches.extend(matches.tolist())

print(f"\nTotal unique sugar-related: {len(set(sugar_matches)):,}")

# ============================================================================
# LOW SODIUM / UNSALTED
# ============================================================================
print("\n" + "=" * 80)
print("LOW SODIUM / UNSALTED CLAIMS")
print("=" * 80)

sodium_patterns = [
    "low sodium",
    "low-sodium",
    "low salt",
    "low-salt",
    "unsalted",
    "no salt",
    "without salt",
    "salt-?free",
    "salt free",
    "reduced sodium",
    "reduced-sodium"
]

sodium_matches = []
for pattern in sodium_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, regex=True, na=False)]
    print(f"\n'{pattern}': {len(matches):6,} matches")
    if len(matches) > 0:
        print("  Examples:")
        for desc in matches.head(3).values:
            print(f"    - {desc}")
    sodium_matches.extend(matches.tolist())

print(f"\nTotal unique sodium-related: {len(set(sodium_matches)):,}")

# ============================================================================
# LOW FAT / FAT-FREE
# ============================================================================
print("\n" + "=" * 80)
print("LOW FAT / FAT-FREE CLAIMS")
print("=" * 80)

fat_patterns = [
    "fat-?free",
    "fat free",
    "no fat",
    "without fat",
    "low fat",
    "low-fat",
    "nonfat",
    "reduced fat",
    "reduced-fat",
    "light"  # Often used for fat reduction, but risky (light meat, light roast, etc.)
]

fat_matches = []
for pattern in fat_patterns:
    matches = descriptions[descriptions.str.contains(pattern, case=False, regex=True, na=False)]
    print(f"\n'{pattern}': {len(matches):6,} matches")
    if len(matches) > 0:
        print("  Examples:")
        for desc in matches.head(3).values:
            print(f"    - {desc}")
    fat_matches.extend(matches.tolist())

print(f"\nTotal unique fat-related: {len(set(fat_matches)):,}")

# ============================================================================
# SUMMARY COMPARISON
# ============================================================================
print("\n" + "=" * 80)
print("SUMMARY: Nutritional Claims Frequency")
print("=" * 80)
print(f"Sugar-free/low-sugar:  {len(set(sugar_matches)):6,} products")
print(f"Sodium-free/low-sodium: {len(set(sodium_matches)):6,} products")
print(f"Fat-free/low-fat:      {len(set(fat_matches)):6,} products")
print(f"\nComparison to explicit claims (from discovery):")
print(f"  Organic:           102,123")
print(f"  Gluten-free:        11,558")
print(f"  Vegan:               3,465")