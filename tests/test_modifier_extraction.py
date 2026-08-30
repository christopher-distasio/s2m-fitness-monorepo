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
            "fat_trim", "grain_type", "sauce_profile", "preparation_source", "temperature",
        }
        assert set(result.keys()) == expected_categories
        assert all(v == "NONE" for v in result.values())

    def test_whole_milk_no_longer_tagged_grain_whole(self):
        """
        Regression test for the specific bug: bare 'whole' matched inside
        'Milk, whole' and got wrongly tagged GRAIN_WHOLE. Fixed by
        removing bare 'whole' from GRAIN_TYPE_MAP (kept 'whole grain',
        'whole wheat' only). `multigrain` is not whole grain and is not mapped.
        """
        result = extract_fndds("Milk, whole")
        assert result["grain_type"] == "NONE"

    def test_whole_grain_bread_correctly_tagged(self):
        """Sanity check: legitimate whole grain matches should still work."""
        result = extract_fndds("Bread, whole grain, white")
        assert result["grain_type"] == "GRAIN_WHOLE"


# ============================================================================
# Branded-name rule fixes (2026-08-25 sample review)
# Applied to both extractors so query-side and DB-side stay aligned.
# ============================================================================

class TestBrandedRuleFixes:
    """Six term-list fixes from the branded 200-row review. Not LLM."""

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_multigrain_is_not_whole_grain(self, extract):
        assert extract("ORGANICS MULTIGRAIN BREAD")["grain_type"] == "NONE"
        assert extract("HOT CEREAL, TART CHERRY MULTIGRAIN")["grain_type"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_whole_grain_and_whole_wheat_still_fire(self, extract):
        assert extract("WHITE WHOLE GRAIN BREAD")["grain_type"] == "GRAIN_WHOLE"
        assert extract("WHOLE WHEAT TORTILLA")["grain_type"] == "GRAIN_WHOLE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_suppressed_in_non_fat_senses(self, extract):
        assert extract("CHUNK LIGHT TUNA IN WATER")["fat_level"] == "NONE"
        assert extract("CHUNK LIGHT TONGOL TUNA")["fat_level"] == "NONE"
        assert extract("WILD-CAUGHT LIGHT TUNA")["fat_level"] == "NONE"
        assert extract("EXTRA LIGHT SYRUP")["fat_level"] == "NONE"
        assert extract("NECTAR, LIGHT GUAVA")["fat_level"] == "NONE"
        assert extract("LIGHT ROAST COFFEE")["fat_level"] == "NONE"
        assert extract("LIGHT BROWN SUGAR")["fat_level"] == "NONE"
        assert extract("LIGHT CORN SYRUP")["fat_level"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_still_fires_for_reduced_fat_products(self, extract):
        assert extract("LIGHT RANCH DRESSING")["fat_level"] == "FAT_LEVEL_REDUCED"
        assert extract("VANILLA LIGHT ICE CREAM")["fat_level"] == "FAT_LEVEL_REDUCED"
        assert extract("Progresso Light Chicken Pot Pie Style Soup")["fat_level"] == "FAT_LEVEL_REDUCED"
        assert extract("LIGHT & LEAN SOFT TACO FIESTA")["fat_level"] == "FAT_LEVEL_REDUCED"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_raw_honey_and_raw_sugar_not_cooking_raw(self, extract):
        assert extract("WATER WITH RAW HONEY")["cooking_method"] == "NONE"
        assert extract("RAW HONEY, BLACKBERRY BLOSSOM")["cooking_method"] == "NONE"
        assert extract("SOUTHWEST LOCAL RAW HONEY")["cooking_method"] == "NONE"
        assert extract("RAW SUGAR")["cooking_method"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_raw_shrimp_still_fires(self, extract):
        assert extract("RAW PINWHEEL SHRIMP SKEWERS")["cooking_method"] == "COOKING_RAW"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_dry_roasted_does_not_also_tag_dried(self, extract):
        result = extract("DRY ROASTED WHOLE ALMOND")
        assert result["cooking_method"] == "COOKING_DRY"
        assert result["prep_form"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_standalone_dry_still_tags_dried(self, extract):
        assert extract("DRY PASTA")["prep_form"] == "PREP_FORM_DRIED"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_rotisserie_is_dry_heat_not_smoke(self, extract):
        result = extract("DELI STYLE ROTISSERIE SEASONED CHICKEN BREAST")
        assert result["cooking_method"] == "COOKING_DRY"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_smoked_still_tags_smoke(self, extract):
        assert extract("NATURAL SMOKED TURKEY BREAST")["cooking_method"] == "COOKING_SMOKE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_brand_denylist_suppresses_trigger_only(self, extract):
        assert extract("CANADA DRY GINGER ALE")["prep_form"] == "NONE"
        fresh_market = extract("FRESH FOODS MARKET, SMOKED GOUDA")
        assert fresh_market["prep_form"] == "NONE"
        creative = extract("FRESH CREATIVE FOODS, SMOKED GOUDA PIMENTO SPREAD")
        assert creative["prep_form"] == "NONE"
        assert creative["cooking_method"] == "COOKING_SMOKE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_fresh_still_fires_when_not_a_denied_brand(self, extract):
        assert extract("FRESH SALSA")["prep_form"] == "PREP_FORM_FRESH"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_low_calorie_is_not_low_fat(self, extract):
        assert extract("COCONUT WATER LOW CALORIE DRINK STICKS")["fat_level"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_comma_split_chunk_tuna(self, extract):
        assert extract("CHUNK LIGHT TUNA IN WATER, CHUNK LIGHT IN WATER")["fat_level"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_beverage_and_color_senses(self, extract):
        assert extract("BLUEBERRY LEMONADE LIGHT LOW CALORIE DRINK MIX STICKS")["fat_level"] == "NONE"
        assert extract("WYLER'S LIGHT, LOW CALORIE SOFT DRINK MIX, PINK LEMONADE")["fat_level"] == "NONE"
        assert extract("MOLASSES, LIGHT & SWEET")["fat_level"] == "NONE"
        assert extract("LIGHT YELLOW CLING SLICED PEACHES")["fat_level"] == "NONE"
        assert extract("EXTRA LIGHT IN TASTE OLIVE OIL")["fat_level"] == "NONE"
        assert extract("LIGHT & CRISPY HAND BREADED RAVIOLI")["fat_level"] == "NONE"
        assert extract("REFRESHINGLY LIGHT PREMIUM INDIAN TONIC WATER")["fat_level"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_must_keep_reduced_fat_products(self, extract):
        keep = [
            "LIGHT ICE CREAM",
            "LIGHT SOUR CREAM",
            "LIGHT CREAM CHEESE",
            "LIGHT RANCH DRESSING",
            "LIGHT CAESAR DRESSING",
            "LIGHT ITALIAN DRESSING",
            "LIGHT BALSAMIC VINAIGRETTE DRESSING",
            "Progresso Light Chicken Pot Pie Style Soup",
            "Yoplait Light",
            "LIGHT BUTTER FLAVORED MICROWAVE POPCORN",
            "WHIPPED LIGHT CREAM",
            "UNSWEETENED LIGHT COCONUT MILK",
        ]
        for name in keep:
            assert extract(name)["fat_level"] == "FAT_LEVEL_REDUCED", name

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_and_fit_line_does_not_claim_reduced_fat(self, extract):
        """Dannon Light + Fit is a product line, not a USDA fat-level claim.

        Confirmed 2026-08-29: extracting FAT_LEVEL_REDUCED from 'light' and
        applying it as a Qdrant must-filter excluded the real (mostly
        FAT_LEVEL_FREE) cups. Suppress the 'light' trigger; do not remap
        the line to FAT_LEVEL_FREE.
        """
        none = [
            "dannon light and fit yogurt",
            "Dannon Light & Fit yogurt",
            "Dannon Light + Fit yogurt",
            "dannon light+fit yogurt",
            "LIGHT & FIT GREEK YOGURT",
            "dannon light yogurt",
        ]
        for name in none:
            assert extract(name)["fat_level"] == "NONE", name

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_light_and_fit_does_not_block_unrelated_reduced_fat(self, extract):
        assert extract("LIGHT RANCH DRESSING")["fat_level"] == "FAT_LEVEL_REDUCED"
        assert extract("LIGHT & LEAN SOFT TACO FIESTA")["fat_level"] == "FAT_LEVEL_REDUCED"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_raw_marketing_and_cane_sugar(self, extract):
        assert extract("ORGANIC RAW! GO SPROUTED SUNFLOWER SEEDS")["cooking_method"] == "NONE"
        assert extract("RAW CANE SUGAR")["cooking_method"] == "NONE"
        assert extract("RAW TURBINADO")["cooking_method"] == "NONE"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_raw_seafood_and_seeds_still_fire(self, extract):
        assert extract("RAW SHRIMP")["cooking_method"] == "COOKING_RAW"
        assert extract("RAW CHOPPED SEA CLAMS")["cooking_method"] == "COOKING_RAW"
        assert extract("RAW WHOLE POPPY SEEDS")["cooking_method"] == "COOKING_RAW"
        assert extract("RAW CHICKEN")["cooking_method"] == "COOKING_RAW"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_iced_baked_goods_vs_drinks(self, extract):
        assert extract("ICED DEVIL'S FOOD CAKE")["temperature"] == "NONE"
        assert extract("TULIPS STRAWBERRY ICED COOKIES")["temperature"] == "NONE"
        assert extract("ICED TEA")["temperature"] == "TEMP_COLD"
        assert extract("ICED COFFEE")["temperature"] == "TEMP_COLD"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_boston_baked_beans_candy_vs_baked_beans(self, extract):
        candy = extract("BOSTON BAKED BEANS CANDY COATED PEANUTS")
        assert candy["cooking_method"] == "NONE"
        beans = extract("BAKED BEANS")
        assert beans["cooking_method"] == "COOKING_OVEN"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_salted_caramel_does_not_fire_sodium(self, extract):
        assert extract("SALTED CARAMEL BLONDIE")["sodium_level"] == "NONE"
        assert extract("SALTED BUTTER")["sodium_level"] == "SODIUM_ADDED"
        assert extract("ROASTED SALTED CASHEWS")["sodium_level"] == "SODIUM_ADDED"

    @pytest.mark.parametrize("extract", [extract_fndds, extract_sr_legacy])
    def test_preparation_source_does_not_use_source_key(self, extract):
        result = extract("prepared from recipe")
        assert "source" not in result or result.get("source") is None
        assert result["preparation_source"] == "SOURCE_HOME"


def test_query_side_parser_shares_light_and_fit_suppression():
    from backend.services.parse_query_modifiers import parse_query_modifiers

    for q in (
        "dannon light and fit yogurt",
        "Dannon Light & Fit yogurt",
        "dannon light yogurt",
    ):
        assert parse_query_modifiers(q)["fat_level"] == "NONE"
    assert parse_query_modifiers("light ranch dressing")["fat_level"] == "FAT_LEVEL_REDUCED"