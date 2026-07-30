"""
Extract modifiers from FNDDS food descriptions and patch them into Pinecone.

This script:
1. Loads FNDDS food descriptions
2. Parses descriptions to identify canonical modifiers (cooking method, skin, fat, etc.)
3. Patches modifier metadata fields onto existing Pinecone records using
   index.update() -- this does NOT touch the existing embedding vector,
   it only adds/overwrites the specified metadata fields.

IMPORTANT -- WHY EVERY CATEGORY IS ALWAYS SET:
index.update() only OVERWRITES the metadata keys you explicitly pass; it
never clears keys you omit. If a previous (buggy) run wrote a category
like grain_type incorrectly, and a later corrected run finds no match for
that category, simply omitting the key leaves the old, wrong value sitting
in Pinecone forever.

To prevent this, every record write includes ALL 13 modifier categories,
using the sentinel value "NONE" for any category that didn't match. This
makes every run a full, clean overwrite instead of a partial patch, so
stale/incorrect values from earlier runs can never linger silently.

MATCHING STRATEGY:
Uses word-boundary matching (not plain substring) to avoid false positives
like "iced" matching inside "diced" or "raw" matching inside "strawberry".
Some terms still collide as WHOLE WORDS even with boundaries (e.g. "hot"
legitimately matches inside "hot dog") -- those are handled via an
explicit EXCLUSIONS list below.

Pinecone metadata values must be strings, numbers, booleans, or lists of
strings -- NOT nested objects/dicts. So each modifier category is written
as its own top-level metadata field, rather than nested under a single
"modifiers" key.

Resume support: set RESUME_OFFSET if interrupted.
"""

import os
import re
import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone
from pathlib import Path

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

FNDDS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_survey_food_csv_2024-10-31"
RESUME_OFFSET = 0
TEST_MODE = False
TEST_LIMIT = 50

NONE_VALUE = "NONE"  # sentinel for "no modifier matched in this category"

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("food-index")

# ============================================================================
# MODIFIER MAPPINGS (USDA term -> Canonical value)
# ============================================================================

COOKING_METHOD_MAP = {
    "raw": "COOKING_RAW",
    "unheated": "COOKING_RAW",
    "unprepared": "COOKING_RAW",
    "from raw": "COOKING_RAW",

    "dry heat": "COOKING_DRY",
    "roasted": "COOKING_DRY",
    "toasted": "COOKING_DRY",
    "dry roasted": "COOKING_DRY",
    "baked or broiled": "COOKING_DRY",

    "boiled": "COOKING_MOIST",
    "steamed": "COOKING_MOIST",
    "stewed": "COOKING_MOIST",
    "braised": "COOKING_MOIST",
    "simmered": "COOKING_MOIST",
    "poached": "COOKING_MOIST",

    "fried": "COOKING_FAT",
    "pan-fried": "COOKING_FAT",
    "pan fried": "COOKING_FAT",
    "sauteed": "COOKING_FAT",
    "sautéed": "COOKING_FAT",
    "grilled": "COOKING_FAT",
    "pan-broiled": "COOKING_FAT",
    "oil roasted": "COOKING_FAT",

    "smoked": "COOKING_SMOKE",
    "rotisserie": "COOKING_SMOKE",

    "baked": "COOKING_OVEN",
    "broiled": "COOKING_OVEN",

    "microwaved": "COOKING_SPECIAL",
}

PREP_FORM_MAP = {
    "fresh": "PREP_FORM_FRESH",
    "frozen": "PREP_FORM_FROZEN",
    "from frozen": "PREP_FORM_FROZEN",
    "canned": "PREP_FORM_CANNED",
    "from canned": "PREP_FORM_CANNED",
    "dried": "PREP_FORM_DRIED",
    "from dried": "PREP_FORM_DRIED",
    "dry": "PREP_FORM_DRIED",
    "bottled": "PREP_FORM_BOTTLED",
    "condensed": "PREP_FORM_CONDENSED",
    "powder": "PREP_FORM_POWDER",
}

SKIN_STATUS_MAP = {
    "meat and skin": "SKIN_ON",
    "skin eaten": "SKIN_ON",
    "skin / coating eaten": "SKIN_ON",
    "with skin": "SKIN_ON",
    "skin on": "SKIN_ON",

    "meat only": "SKIN_OFF",
    "skin not eaten": "SKIN_OFF",
    "skin / coating not eaten": "SKIN_OFF",
    "skinless": "SKIN_OFF",
    "no skin": "SKIN_OFF",
    "skin and breading removed": "SKIN_OFF",
}

COATING_STATUS_MAP = {
    "breaded": "COATING_BREADED",
    "unbreaded": "COATING_UNBREADED",
}

SODIUM_LEVEL_MAP = {
    "no salt added": "SODIUM_NONE",
    "without salt": "SODIUM_NONE",
    "without salt added": "SODIUM_NONE",
    "unsalted": "SODIUM_NONE",

    "with salt": "SODIUM_ADDED",
    "with salt added": "SODIUM_ADDED",
    "salted": "SODIUM_ADDED",

    "reduced sodium": "SODIUM_REDUCED",
    "low sodium": "SODIUM_REDUCED",
}

SWEETNESS_MAP = {
    "unsweetened": "SWEETNESS_NONE",
    "sugar-free": "SWEETNESS_NONE",
    "sugar free": "SWEETNESS_NONE",
    "no sugar added": "SWEETNESS_NONE",
    "reduced sugar": "SWEETNESS_NONE",
    "diet": "SWEETNESS_NONE",
    "sweetened": "SWEETNESS_ADDED",
}

FAT_LEVEL_MAP = {
    "reduced fat": "FAT_LEVEL_REDUCED",
    "low fat": "FAT_LEVEL_REDUCED",
    "fat-free": "FAT_LEVEL_FREE",
    "fat free": "FAT_LEVEL_FREE",
    "nonfat": "FAT_LEVEL_FREE",
    "light": "FAT_LEVEL_REDUCED",
    "low calorie": "FAT_LEVEL_REDUCED",
}

FAT_ADDED_MAP = {
    "no added fat": "FAT_ADDED_NONE",

    "cooked with oil": "FAT_ADDED_OIL",
    "made with oil": "FAT_ADDED_OIL",

    "cooked with butter or margarine": "FAT_ADDED_BUTTER",
    "made with butter": "FAT_ADDED_BUTTER",
    "made with margarine": "FAT_ADDED_BUTTER",
}

FAT_TRIM_MAP = {
    "separable lean only": "FAT_TRIM_LEAN",
    "separable lean and fat": "FAT_TRIM_MIXED",
    "separable fat": "FAT_TRIM_FAT",
    "trimmed to 0\" fat": "FAT_TRIM_0IN",
    "trimmed to 1/8\" fat": "FAT_TRIM_1_8IN",
    "trimmed to 1/4\" fat": "FAT_TRIM_1_4IN",
}

GRAIN_TYPE_MAP = {
    "whole grain": "GRAIN_WHOLE",
    "whole wheat": "GRAIN_WHOLE",
    "multigrain": "GRAIN_WHOLE",
    "gluten-free": "GRAIN_GLUTENFREE",
    "gluten free": "GRAIN_GLUTENFREE",
}

SAUCE_PROFILE_MAP = {
    "no sauce": "SAUCE_NONE",
    "no dressing": "SAUCE_NONE",

    "with gravy": "SAUCE_WITH",
    "gravy": "SAUCE_WITH",
    "tomato-based sauce": "SAUCE_WITH",
    "with tomato sauce": "SAUCE_WITH",
    "with cream sauce": "SAUCE_WITH",
    "soy-based sauce": "SAUCE_WITH",
}

SOURCE_MAP = {
    "from fast food": "SOURCE_FASTFOOD",
    "from fast food / restaurant": "SOURCE_COMMERCIAL",
    "from restaurant": "SOURCE_COMMERCIAL",
    "from school lunch": "SOURCE_SCHOOL",
    "home recipe": "SOURCE_HOME",
    "prepared from recipe": "SOURCE_HOME",
    "from fresh": "SOURCE_FRESH",
    "from frozen": "SOURCE_FROZEN",
    "from canned": "SOURCE_CANNED",
    "from dried": "SOURCE_DRIED",
}

TEMP_MAP = {
    "hot": "TEMP_HOT",
    "iced": "TEMP_COLD",
}

ALL_MAPPINGS = {
    "cooking_method": COOKING_METHOD_MAP,
    "prep_form": PREP_FORM_MAP,
    "skin_status": SKIN_STATUS_MAP,
    "coating_status": COATING_STATUS_MAP,
    "sodium_level": SODIUM_LEVEL_MAP,
    "sweetness": SWEETNESS_MAP,
    "fat_level": FAT_LEVEL_MAP,
    "fat_added": FAT_ADDED_MAP,
    "fat_trim": FAT_TRIM_MAP,
    "grain_type": GRAIN_TYPE_MAP,
    "sauce_profile": SAUCE_PROFILE_MAP,
    "source": SOURCE_MAP,
    "temperature": TEMP_MAP,
}

EXCLUSIONS = {
    "hot": ["hot dog"],
}


def word_match(term, text):
    """
    Match `term` as a whole word/phrase within `text` -- not as a bare
    substring. Uses lookbehind/lookahead on non-alphanumeric characters
    instead of \\b so it also works correctly for terms containing
    punctuation (e.g. 'trimmed to 1/8" fat').
    """
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


def extract_modifiers(description):
    """
    Parse an FNDDS food description and extract modifiers.

    Returns a flat dict with ALL 13 categories always present -- either
    a matched canonical value, or the NONE_VALUE sentinel if nothing
    matched. This guarantees every Pinecone update is a full, clean
    overwrite rather than a partial patch that could leave stale values
    from a previous run.
    """
    desc_lower = (description or "").lower().strip()

    # Start every category at NONE_VALUE so nothing is ever left unset.
    modifiers = {category: NONE_VALUE for category in ALL_MAPPINGS}

    for category, term_map in ALL_MAPPINGS.items():
        for usda_term, canonical_value in term_map.items():
            if not word_match(usda_term, desc_lower):
                continue

            excluded_phrases = EXCLUSIONS.get(usda_term, [])
            if any(phrase in desc_lower for phrase in excluded_phrases):
                continue

            modifiers[category] = canonical_value
            break  # Only one value per category (mutually exclusive)

    return modifiers


def main():
    survey_map = pd.read_csv(f"{FNDDS_DIR}/survey_fndds_food.csv")
    food_desc = pd.read_csv(f"{FNDDS_DIR}/food.csv")[["fdc_id", "description"]]
    foods = survey_map.merge(food_desc, on="fdc_id", how="left")

    records = foods.to_dict("records")[RESUME_OFFSET:]
    if TEST_MODE:
        records = records[:TEST_LIMIT]
        print(f"TEST_MODE on — running {len(records)} records only")

    batch_size = 100
    modifier_counts = {}
    updated_count = 0

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]

        for row in batch:
            fdc_id = row["fdc_id"]
            description = row["description"]

            modifiers = extract_modifiers(description)

            for category, value in modifiers.items():
                if value == NONE_VALUE:
                    continue  # don't count "no match" in the summary
                if category not in modifier_counts:
                    modifier_counts[category] = {}
                if value not in modifier_counts[category]:
                    modifier_counts[category][value] = 0
                modifier_counts[category][value] += 1

            # Every record gets a full overwrite of all 13 categories --
            # this is what clears any stale values from earlier runs.
            index.update(
                id=f"fndds-{fdc_id}",
                set_metadata=modifiers,
            )
            updated_count += 1

        print(f"Processed batch starting at offset {RESUME_OFFSET + i}, size {len(batch)}")

    print(f"\nTotal records updated: {updated_count}")

    print("\n" + "=" * 60)
    print("MODIFIER EXTRACTION SUMMARY (matches only, NONE excluded)")
    print("=" * 60)
    for category, values in sorted(modifier_counts.items()):
        print(f"\n{category}:")
        for value, count in sorted(values.items(), key=lambda x: -x[1]):
            print(f"  {value}: {count}")


if __name__ == "__main__":
    main()