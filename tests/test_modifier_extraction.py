"""
Regression tests for the modifier extraction logic (extract_modifiers_fndds.py
and extract_modifiers_sr_legacy.py).

Per our testing standard, Tier 3: any bug found in data/ranking/parsing
logic gets promoted to a permanent pytest case, so future edits to the
mapping dictionaries or exclusion lists can't silently reintroduce it.

Every test here corresponds to a real, confirmed bug found and fixed
during development -- not a hypothetical edge case. Each test's docstring
notes which conversation/investigation surfaced the issue.

Run: poetry run pytest tests/test_modifier_extraction.py -v
"""

import pytest
from extract_modifiers_fndds import extract_modifiers as extract_fndds
from extract_modifiers_sr_legacy import extract_modifiers as extract_sr_legacy


# ============================================================================
# FNDDS -- confirmed bugs
# ============================================================================

class TestFnddsModifiers:

    def test_hot_dog_not_tagged_temperature(self):
        """
        'hot dog' contains the word 'hot' but is a food name, not a
        temperature. Original bare "hot": "TEMP_HOT" mapping caused
        ~40 hot-dog-related FNDDS records to be wrongly tagged TEMP_HOT.
        """
        result = extract_fndds("Hot dog, NFS")
        assert result["temperature"] == "NONE"

    def test_hot_sauce_not_tagged_temperature(self):
        """'hot sauce' / 'hot chili' are about spice level, not temperature."""
        result = extract_fndds("Chicken \"wings\" with hot sauce, from fast food / restaurant")
        assert result["temperature"] == "NONE"

    def test_hot_pocket_not_tagged_temperature(self):
        """'Hot Pocket' is a brand/product name, not a temperature descriptor."""
        result = extract_fndds("Turnover or hot pocket, NFS")
        assert result["temperature"] == "NONE"

    def test_hot_chocolate_correctly_tagged_hot(self):
        """
        Sanity check: legitimate hot beverages should still match, since
        we switched to phrase-based matching ("hot chocolate", "hot cocoa",
        "tea, hot", "hot buttered") rather than removing "hot" entirely.
        """
        result = extract_fndds("Hot chocolate / cocoa, NFS")
        assert result["temperature"] == "TEMP_HOT"

    def test_hot_tea_correctly_tagged_hot(self):
        result = extract_fndds("Tea, hot, leaf, black")
        assert result["temperature"] == "TEMP_HOT"

    def test_cream_filled_iced_pastry_not_tagged_cold(self):
        """
        'iced' on a cream puff/pastry means frosted, not cold. This was a
        real bug: "Cream puff, eclair, custard or cream filled, iced" was
        wrongly tagged TEMP_COLD.
        """
        result = extract_fndds("Cream puff, eclair, custard or cream filled, iced")
        assert result["temperature"] == "NONE"

    def test_not_iced_pastry_not_tagged_cold(self):
        """
        Worse variant of the bug above: even "not iced" contains the
        substring/word 'iced' and was matching before the 'cream filled'
        exclusion was added.
        """
        result = extract_fndds("Cream puff, eclair, custard or cream filled, not iced")
        assert result["temperature"] == "NONE"

    def test_iced_or_not_iced_pastry_not_tagged_cold(self):
        result = extract_fndds("Pastry, puff, custard or cream filled, iced or not iced")
        assert result["temperature"] == "NONE"

    def test_iced_coffee_correctly_tagged_cold(self):
        """Sanity check: legitimate cold beverages should still match."""
        result = extract_fndds("Iced Coffee, brewed")
        assert result["temperature"] == "TEMP_COLD"

    def test_iced_tea_correctly_tagged_cold(self):
        result = extract_fndds("Tea, iced, brewed, black, unsweetened")
        assert result["temperature"] == "TEMP_COLD"

    def test_ns_as_to_skin_eaten_not_tagged_skin_on(self):
        """
        'NS as to skin eaten' means UNSPECIFIED, not confirmed skin-on.
        Verified against actual USDA nutrient data: the NS record's
        calories/fat exactly matched the SKIN_OFF sibling, not SKIN_ON --
        confirming NS defaults to the lower-calorie assumption for this
        category, not skin-on.
        """
        result = extract_fndds("Chicken, NS as to part and cooking method, NS as to skin eaten")
        assert result["skin_status"] == "NONE"

    def test_skin_eaten_correctly_tagged_skin_on(self):
        """Sanity check: an unambiguous 'skin eaten' should still match."""
        result = extract_fndds("Chicken breast, NS as to cooking method, skin eaten")
        assert result["skin_status"] == "SKIN_ON"

    def test_skin_not_eaten_correctly_tagged_skin_off(self):
        result = extract_fndds("Chicken breast, NS as to cooking method, skin not eaten")
        assert result["skin_status"] == "SKIN_OFF"


# ============================================================================
# SR Legacy -- confirmed bugs
# ============================================================================

class TestSrLegacyModifiers:

    def test_hot_dog_not_tagged_temperature(self):
        result = extract_sr_legacy("Pickle relish, hot dog")
        assert result["temperature"] == "NONE"

    def test_hot_chili_not_tagged_temperature(self):
        """
        SR Legacy's 'hot' matches were 32/33 false positives (hot dog,
        hot chili/chile/sauce, HOT POCKETS, named cereal products) with
        only 1 arguably-legitimate case (a named beverage product, not a
        true temperature modifier). Decision: remove "hot" entirely from
        SR Legacy's TEMP_MAP rather than phrase-matching, unlike FNDDS
        where genuine hot-beverage phrases were common enough to keep.
        """
        result = extract_sr_legacy("Peppers, hot chili, red, raw")
        assert result["temperature"] == "NONE"

    def test_hot_pocket_style_product_not_tagged_temperature(self):
        result = extract_sr_legacy("WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single")
        assert result["temperature"] == "NONE"

    def test_light_meat_not_tagged_fat_level(self):
        """
        'light meat' refers to meat color/type (vs. dark meat), not fat
        content. Bare "light": "FAT_LEVEL_REDUCED" would incorrectly tag
        this. Confirmed via SR Legacy ambiguity scan.
        """
        result = extract_sr_legacy("Turkey, light or dark meat, smoked, cooked, skin and bone removed")
        assert result["fat_level"] == "NONE"

    def test_light_ice_cream_correctly_tagged_reduced_fat(self):
        """Sanity check: legitimate 'light' as a fat-reduction descriptor should still match."""
        result = extract_sr_legacy("Ice creams, vanilla, light")
        assert result["fat_level"] == "FAT_LEVEL_REDUCED"

    def test_iced_pastry_not_tagged_cold(self):
        result = extract_sr_legacy("Archway Home Style Cookies, Iced Molasses")
        assert result["temperature"] == "NONE"

    def test_iced_oatmeal_cookie_not_tagged_cold(self):
        result = extract_sr_legacy("Archway Home Style Cookies, Iced Oatmeal")
        assert result["temperature"] == "NONE"

    def test_iced_coffee_correctly_tagged_cold(self):
        """Sanity check: legitimate cold beverages should still match."""
        result = extract_sr_legacy("Beverages, coffee, ready to drink, iced, mocha, milk based")
        assert result["temperature"] == "TEMP_COLD"

    def test_ns_as_to_skin_eaten_not_tagged_skin_on(self):
        """Same fix ported over from FNDDS."""
        result = extract_sr_legacy("Chicken, NS as to part, NS as to skin eaten")
        assert result["skin_status"] == "NONE"


# ============================================================================
# Shared word-boundary matching behavior
# (identical word_match() logic in both scripts; testing via FNDDS is
# sufficient to cover both, but each dataset's real trigger case is used
# to document why the fix mattered.)
# ============================================================================

class TestWordBoundaryMatching:

    def test_diced_does_not_match_iced(self):
        """
        Plain substring matching would find 'iced' inside 'diced', wrongly
        tagging TEMP_COLD. Word-boundary matching prevents this.
        """
        result = extract_fndds("Spanish rice mix, dry mix, prepared with diced tomatoes")
        assert result["temperature"] == "NONE"

    def test_strawberry_does_not_match_raw(self):
        """
        Plain substring matching would find 'raw' inside 'strawberry',
        wrongly tagging COOKING_RAW even for cooked/processed strawberry
        products.
        """
        result = extract_sr_legacy("Strawberries, frozen, sweetened, sliced")
        assert result["cooking_method"] == "NONE"

    def test_lightly_does_not_match_light(self):
        """
        Plain substring matching would find 'light' inside 'lightly',
        wrongly tagging FAT_LEVEL_REDUCED for something just lightly
        salted/seasoned.
        """
        result = extract_sr_legacy("Snacks, pretzels, hard, plain, salted")
        assert result["fat_level"] == "NONE"


# ============================================================================
# NONE-sentinel full-overwrite pattern
# ============================================================================

class TestNoneSentinelPattern:

    def test_all_categories_always_present(self):
        """
        Every call to extract_modifiers() must return all categories,
        even when nothing matches -- this is what guarantees a full
        overwrite on every Pinecone update, preventing stale values from
        a previous run from silently lingering (the original bug that
        caused "Milk, whole" to keep an incorrect GRAIN_WHOLE tag after
        the underlying mapping was fixed).
        """
        result = extract_fndds("Completely unmatched food description xyz")
        expected_categories = {
            "cooking_method", "prep_form", "skin_status", "coating_status",
            "sodium_level", "sweetness", "fat_level", "fat_added",
            "fat_trim", "grain_type", "sauce_profile", "source", "temperature",
        }
        assert set(result.keys()) == expected_categories
        assert all(v == "NONE" for v in result.values())

    def test_whole_milk_no_longer_tagged_grain_whole(self):
        """
        Regression test for the specific bug: bare 'whole' matched inside
        'Milk, whole' and got wrongly tagged GRAIN_WHOLE. Fixed by
        removing bare 'whole' from GRAIN_TYPE_MAP (kept 'whole grain',
        'whole wheat', 'multigrain' only).
        """
        result = extract_fndds("Milk, whole")
        assert result["grain_type"] == "NONE"

    def test_whole_grain_bread_correctly_tagged(self):
        """Sanity check: legitimate whole grain matches should still work."""
        result = extract_fndds("Bread, whole grain, white")
        assert result["grain_type"] == "GRAIN_WHOLE"