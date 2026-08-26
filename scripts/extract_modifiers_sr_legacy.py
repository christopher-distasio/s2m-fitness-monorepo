"""
Extract modifiers from SR Legacy food descriptions and patch them into
Pinecone.

This script mirrors extract_modifiers_fndds.py, adapted for SR Legacy's
description format and vector ID prefix (sr_{fdc_id}). Prefix verified
via Pinecone fetch() against a known fdc_id before the production run
(see ID_PREFIX / embed_sr_legacy.py).

FIXES BAKED IN FROM SR LEGACY AMBIGUITY ANALYSIS:
- "hot" removed entirely from TEMP_MAP -- 32/33 SR Legacy matches were
  false positives (hot dog, hot chili/chile/sauce, HOT POCKETS, named
  cereal products), only 1 was arguably about temperature and even that
  was a named beverage type, not a true modifier.
- "iced" kept, but with exclusions for pastry-icing false positives
  ("cream filled, iced", "iced molasses", "iced oatmeal").
- "light" kept, but excluded when it means meat color, not fat level
  ("light meat", "light or dark meat").
- "skin eaten" excluded when preceded by "ns as to" (unspecified doesn't
  mean skin-on) -- carried over from the FNDDS fix.

MATCHING STRATEGY:
Uses word-boundary matching (not plain substring) to avoid false
positives like "iced" matching inside "diced" or "raw" matching inside
"strawberry".

Pinecone metadata values must be strings, numbers, booleans, or lists of
strings -- NOT nested objects/dicts. So each modifier category is written
as its own top-level metadata field.

Every record write includes ALL 13 categories, using the sentinel value
"NONE" for any category that didn't match -- this guarantees every
Pinecone update is a full, clean overwrite rather than a partial patch
that could leave stale values from a previous run.

Resume support: set RESUME_OFFSET if interrupted.
"""

import os
import re
import sys
import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from backend.services.modifier_extract import extract_modifiers_from_maps

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

SR_LEGACY_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "FoodData_Central_sr_legacy_food_csv_2018-04"
RESUME_OFFSET = 0
TEST_MODE = False
TEST_LIMIT = 50

# Confirmed via fetch() against Pinecone: SR Legacy vectors use "sr_"
# (underscore, not hyphen) as their ID prefix -- see embed_sr_legacy.py
# line 115: f"sr_{food['fdc_id']}"
ID_PREFIX = "sr_"

NONE_VALUE = "NONE"

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
    "rotisserie": "COOKING_DRY",

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
    # "hot" removed entirely -- see module docstring for rationale.
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
    "preparation_source": SOURCE_MAP,
    "temperature": TEMP_MAP,
}

EXCLUSIONS = {
    "skin eaten": ["ns as to skin eaten"],
    "light": ["light meat", "light or dark meat"],
    "iced": ["cream filled, iced", "iced molasses", "iced oatmeal"],
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
    Parse an SR Legacy food description and extract modifiers.

    Returns a flat dict with ALL 13 categories always present -- either
    a matched canonical value, or the NONE_VALUE sentinel if nothing
    matched.
    """
    return extract_modifiers_from_maps(description, ALL_MAPPINGS, EXCLUSIONS)


def main():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index("food-index")

    food_desc = pd.read_csv(f"{SR_LEGACY_DIR}/food.csv")[["fdc_id", "description"]]

    records = food_desc.to_dict("records")[RESUME_OFFSET:]
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
                    continue
                if category not in modifier_counts:
                    modifier_counts[category] = {}
                if value not in modifier_counts[category]:
                    modifier_counts[category][value] = 0
                modifier_counts[category][value] += 1

            index.update(
                id=f"{ID_PREFIX}{fdc_id}",
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