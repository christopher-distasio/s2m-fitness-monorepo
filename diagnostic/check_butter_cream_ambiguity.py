"""
Check how often 'butter' and 'cream' appear in known non-dairy phrasings
(peanut butter, cocoa butter, coconut cream, etc.) vs total occurrences.

Answers: is a small exclusion list enough, or does this open a long tail
of similar problems that make dropping the term the safer bet?
"""

import pandas as pd
import re

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"

# Known non-dairy phrasings that contain "butter" or "cream" as substrings
NON_DAIRY_BUTTER_PHRASES = [
    "peanut butter", "almond butter", "cashew butter", "cocoa butter",
    "shea butter", "apple butter", "sunflower butter", "cocoa nib butter",
    "mango butter", "body butter",  # supplement/cosmetic crossover, unlikely but cheap to check
]
NON_DAIRY_CREAM_PHRASES = [
    "coconut cream", "cream of tartar", "creamed corn", "creamed honey",
    "cream of coconut",
]

def check_ambiguous_terms():
    print(f"Loading {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH, low_memory=False, usecols=["ingredients"])
    ingredients = df["ingredients"].dropna().str.lower()

    print("=" * 80)
    print("'BUTTER' AMBIGUITY CHECK")
    print("=" * 80)

    total_butter = ingredients.str.contains(r'\bbutter\b', regex=True, na=False).sum()
    print(f"\nTotal records containing 'butter': {total_butter:,}")

    non_dairy_butter_mask = pd.Series(False, index=ingredients.index)
    for phrase in NON_DAIRY_BUTTER_PHRASES:
        matches = ingredients.str.contains(phrase, regex=False, na=False)
        count = matches.sum()
        if count > 0:
            print(f"  '{phrase}': {count:,}")
        non_dairy_butter_mask |= matches

    non_dairy_butter_total = non_dairy_butter_mask.sum()
    print(f"\nTotal non-dairy 'butter' phrasings: {non_dairy_butter_total:,}")
    print(f"Estimated genuine dairy 'butter' mentions: {total_butter - non_dairy_butter_total:,}")
    print(f"Non-dairy share of all 'butter' mentions: {100*non_dairy_butter_total/total_butter:.1f}%")

    print("\n" + "=" * 80)
    print("'CREAM' AMBIGUITY CHECK")
    print("=" * 80)

    total_cream = ingredients.str.contains(r'\bcream\b', regex=True, na=False).sum()
    print(f"\nTotal records containing 'cream': {total_cream:,}")

    non_dairy_cream_mask = pd.Series(False, index=ingredients.index)
    for phrase in NON_DAIRY_CREAM_PHRASES:
        matches = ingredients.str.contains(phrase, regex=False, na=False)
        count = matches.sum()
        if count > 0:
            print(f"  '{phrase}': {count:,}")
        non_dairy_cream_mask |= matches

    non_dairy_cream_total = non_dairy_cream_mask.sum()
    print(f"\nTotal non-dairy 'cream' phrasings: {non_dairy_cream_total:,}")
    print(f"Estimated genuine dairy 'cream' mentions: {total_cream - non_dairy_cream_total:,}")
    print(f"Non-dairy share of all 'cream' mentions: {100*non_dairy_cream_total/total_cream:.1f}%")

    # Show a sample of "butter" mentions NOT caught by the exclusion list,
    # to eyeball whether there's a long tail we're missing
    print("\n" + "=" * 80)
    print("SAMPLE: 'butter' mentions NOT in known non-dairy phrase list")
    print("=" * 80)
    uncaught = ingredients[
        ingredients.str.contains(r'\bbutter\b', regex=True, na=False) & ~non_dairy_butter_mask
    ]
    for i, text in enumerate(uncaught.head(15), 1):
        # find and show context around "butter"
        idx = text.find("butter")
        start = max(0, idx - 20)
        end = min(len(text), idx + 30)
        print(f"  {i}. ...{text[start:end]}...")

if __name__ == "__main__":
    check_ambiguous_terms()