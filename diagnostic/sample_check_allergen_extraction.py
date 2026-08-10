"""
Sanity-check allergen extraction logic against a real sample of branded_food.csv.

Not the full 2M run -- just enough to eyeball whether the modifier-gating and
compound-exclusion logic behaves correctly on real, messy ingredient text
before committing to the full extraction.

Output written to a file so nothing scrolls off in the terminal.
"""

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from allergen_extraction_logic import extract_allergen_states, ALLERGEN_TERMS

CSV_PATH = "data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv"
SAMPLE_SIZE = 500
OUTPUT_FILE = "diagnostic/allergen_sample_check_2026_08_04.txt"


def term_actually_present(text_lower: str, allergen: str) -> bool:
    """
    Check if ANY term for this allergen (not just the category name itself)
    appears in the text. Used to reduce false-alarm noise in the review flag --
    'milk' firing because of 'whey' is correct, not suspicious.
    """
    for term in ALLERGEN_TERMS.get(allergen, []):
        if term in text_lower:
            return True
    return False


def run_sample_check():
    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out(f"Loading sample of {SAMPLE_SIZE} records from {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH, low_memory=False, usecols=["fdc_id", "ingredients"])
    sample = df.dropna(subset=["ingredients"]).sample(n=SAMPLE_SIZE, random_state=42)

    results = []
    for _, row in sample.iterrows():
        states = extract_allergen_states(row["ingredients"])
        non_unknown = {k: v for k, v in states.items() if v != "UNKNOWN"}
        results.append({
            "fdc_id": row["fdc_id"],
            "ingredients_full": row["ingredients"],
            "ingredients_preview": row["ingredients"][:80],
            "non_unknown_count": len(non_unknown),
            "states": non_unknown,
        })

    total_with_any_signal = sum(1 for r in results if r["non_unknown_count"] > 0)
    out("=" * 80)
    out(f"SAMPLE SUMMARY (n={SAMPLE_SIZE})")
    out("=" * 80)
    out(f"\nRecords with at least one non-UNKNOWN allergen state: {total_with_any_signal} ({100*total_with_any_signal/SAMPLE_SIZE:.1f}%)")

    allergen_counts = {}
    for r in results:
        for allergen, state in r["states"].items():
            key = f"{allergen}:{state}"
            allergen_counts[key] = allergen_counts.get(key, 0) + 1

    out("\nBreakdown by allergen:state:")
    for key, count in sorted(allergen_counts.items(), key=lambda x: -x[1]):
        out(f"  {key}: {count}")

    out("\n" + "=" * 80)
    out("SAMPLE RECORDS WITH SIGNAL (first 20)")
    out("=" * 80)
    shown = 0
    for r in results:
        if r["non_unknown_count"] > 0 and shown < 20:
            out(f"\nfdc_id: {r['fdc_id']}")
            out(f"  Ingredients: {r['ingredients_preview']}...")
            out(f"  States: {r['states']}")
            shown += 1

    # REAL flagging: check against the FULL ingredient text and ALL terms for
    # that allergen, not just the 80-char preview and not just the category name.
    # This should produce a much shorter, much more meaningful list.
    out("\n" + "=" * 80)
    out("FLAGGED FOR MANUAL REVIEW (allergen fired, but no known term found anywhere in full text)")
    out("=" * 80)
    real_flags = 0
    for r in results:
        full_lower = r["ingredients_full"].lower()
        for allergen, state in r["states"].items():
            if state == "CONTAINS" and not term_actually_present(full_lower, allergen):
                real_flags += 1
                out(f"\n  fdc_id {r['fdc_id']}: {allergen}=CONTAINS but NO matching term found in full ingredients")
                out(f"    Full text: {r['ingredients_full']}")

    if real_flags == 0:
        out("\n  None. Every CONTAINS match traces to an actual term in the full ingredient text.")
    else:
        out(f"\n  Total genuine flags: {real_flags}")

    # Write to file
    Path("diagnostic").mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(lines))
    print(f"\n\nFull output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_sample_check()