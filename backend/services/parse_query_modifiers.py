"""
Query-side modifier parser — extracts the same 13 modifiers from user input 
that the database-side extractor tags on food descriptions.

Matches the database-side logic exactly:
- word-boundary matching (not substring)
- canonical enum values ("COOKING_FAT", "SKIN_OFF", etc.)
- NONE sentinel for non-matches
- ALL 13 categories always present on every parse result
- Exclusions list to catch false positives

This ensures user-side "grilled chicken, no skin" produces the same
modifier tags as the database would assign to that description.
"""

import re

from backend.services.modifier_extract import extract_modifiers_from_maps

NONE_VALUE = "NONE"

# All 13 categories with mappings (USDA term -> canonical value)
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
    # `multigrain` is not whole grain (may be all refined). Do not map it.
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
    "iced": "TEMP_COLD",
    # "hot" deliberately omitted — see database-side extractor notes
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

# False-positive exclusions (from database-side extractor)
EXCLUSIONS = {
    "skin eaten": ["ns as to skin eaten"],
    "light": ["light meat", "light or dark meat"],
    "iced": ["cream filled, iced", "iced molasses", "iced oatmeal"],
}


def word_match(term: str, text: str) -> bool:
    """
    Match `term` as a whole word/phrase within `text`.
    Uses lookbehind/lookahead on non-alphanumeric chars to avoid
    false positives like "iced" inside "diced" or "raw" inside "strawberry".
    Also handles punctuation correctly (e.g. 'trimmed to 1/8" fat').
    """
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


def parse_query_modifiers(user_input: str) -> dict:
    """
    Extract modifiers from user query using word-boundary matching.
    
    Returns a flat dict with ALL 13 categories always present:
    {
        "cooking_method": "COOKING_FAT" | canonical_value | "NONE",
        "prep_form": ...,
        "skin_status": ...,
        ...
    }
    
    This matches the database-side extractor exactly, ensuring
    "grilled chicken, no skin" produces the same modifier tags
    that the database assigns.
    """
    
    return extract_modifiers_from_maps(user_input, ALL_MAPPINGS, EXCLUSIONS)


# Test
if __name__ == "__main__":
    test_inputs = [
        "grilled chicken breast, no skin",
        "fried eggs in butter",
        "boiled egg",
        "unsalted peanuts",
        "frozen yogurt",
        "light meat turkey",
    ]
    
    for inp in test_inputs:
        mods = parse_query_modifiers(inp)
        # Show only matches (exclude NONE for clarity)
        matches = {k: v for k, v in mods.items() if v != NONE_VALUE}
        print(f"\nInput: {inp}")
        print(f"Modifiers: {matches if matches else '(no matches)'}")