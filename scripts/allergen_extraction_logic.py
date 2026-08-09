"""
FDA allergen term list + three-state extraction logic.

Priority order per allergen, per product:
1. Explicit "CONTAINS: X, Y" statement present -> named = CONTAINS, not named = FREE
2. "MAY CONTAIN: X" cross-contamination warning -> CONTAINS if severity=severe, ignored if moderate
3. No statement -> scan raw ingredient text for allergen + derivative terms -> match = CONTAINS
4. No statement, no match -> UNKNOWN
5. No ingredients text at all (SR Legacy, FNDDS, ~5,373 blank Branded records) -> UNKNOWN for all allergens

FREE is only ever asserted from an explicit statement. Never inferred from absence of a term match --
that would just mean the term list missed a derivative name, not that the allergen is genuinely absent.

TERM TIERS (per multi-AI review, 2026-08-03):
- Tier A (explicit derivative): whey, casein, ovalbumin, tahini, etc. -- always a direct positive match
- Tier B (generic head noun): milk, butter, cream, cheese, yogurt, mayonnaise -- require modifier-pattern
  check before matching, since "almond milk" / "peanut butter" / "vegan mayonnaise" are not the allergen
- Tier C (unstable prepared-food term): caesar, worcestershire, nougat, praline -- REMOVED as standalone
  triggers. Ground truth varies too much per-product (many modern versions omit the allergen entirely).
  Matching on the specific derivative (anchovy, almond, hazelnut) instead is more reliable than matching
  on the dish/confection name.

SHELLFISH SCOPE: combined crustacean + mollusk under one "shellfish" field. FDA's mandatory labeling law
only covers crustaceans, but a person setting a "shellfish-free" toggle means both groups colloquially --
matching the legal definition only would create a silent gap for clam/oyster/mussel/scallop allergies.

WHEAT / PASTA-NOODLE FIX (2026-08-09): spot-check of the SR Legacy + FNDDS allergen run found
41/113 pasta or noodle records left UNKNOWN for wheat -- "macaroni salad", "flavored pasta",
generic "noodles" dishes were never matching any wheat term, since the term list only had
technical/ingredient-label words (semolina, durum, etc.), not the common dish names. Pasta and
noodles are wheat-based by default in USDA descriptions unless a non-wheat base is explicitly
named (rice noodle, mung bean noodle, egg noodle w/o wheat, spaghetti squash). Added dish-name
terms below, with compound exclusions for the confirmed non-wheat cases.
"""

import re

# ============================================================================
# FDA 9 MAJOR ALLERGENS + DERIVATIVE TERMS
# Source: FALCPA / FASTER Act labeling guidance, validated + expanded via
# multi-AI review (GPT-5, Gemini, Grok) against real ingredient text samples.
# ============================================================================

ALLERGEN_TERMS = {
    "milk": [
        # Tier A: explicit derivatives, always positive
        "whey", "casein", "caseinate", "sodium caseinate", "calcium caseinate",
        "potassium caseinate", "lactose", "lactalbumin", "lactoglobulin",
        "lactoferrin", "ghee", "curds", "buttermilk", "custard",
        "milkfat", "butterfat", "milk powder", "milk solids", "milk protein",
        "milk protein isolate", "milk protein concentrate", "skim milk",
        "nonfat milk", "sweet cream",
        # Tier B: generic head nouns -- gated by modifier check, see is_generic_term_genuine()
        "milk", "cream", "butter", "cheese", "yogurt",
    ],
    "egg": [
        "albumin", "globulin", "lysozyme", "meringue", "ovalbumin", "ovomucin",
        "livetin", "vitellin", "egg white", "egg yolk", "dried egg", "egg solids",
        "egg powder", "whole egg",
        "egg", "eggs", "mayonnaise",  # Tier B: modifier-gated
    ],
    "fish": [
        "anchovy", "anchovies", "anchovy paste", "surimi", "cod", "salmon",
        "tuna", "tilapia", "halibut", "pollock", "haddock", "trout", "sardine",
        "herring", "mackerel", "snapper", "fish sauce", "fish gelatin",
        "isinglass", "caviar", "roe", "bonito",
        # Removed: "worcestershire", "caesar" -- unstable ground truth, see Tier C note above
        # Removed: "bass" -- too broad, negligible real risk per review
        "fish",  # Tier B: modifier-gated (vegan fish, fishless, fish-free)
    ],
    "shellfish": [
        # Crustaceans (FDA-mandated)
        "shrimp", "crab", "lobster", "prawn", "krill", "crawfish", "crayfish",
        "langoustine", "scampi",
        # Mollusks (combined per decision 2026-08-03 -- colloquial "shellfish" includes these)
        "clam", "oyster", "mussel", "scallop", "squid", "octopus",
    ],
    "tree_nut": [
        "almond", "cashew", "walnut", "pecan", "pistachio", "macadamia",
        "hazelnut", "brazil nut", "pine nut", "chestnut", "chinquapin",
        "lychee nut", "shea nut",
        "marzipan", "gianduja",  # stable -- almost always genuinely nut-based
        # Removed: "praline", "nougat" -- unstable ground truth per review
    ],
    "peanut": [
        "peanut", "peanuts", "arachis", "groundnut",
        # Removed: "beer nuts" -- generic trademark/snack name, not reliably peanut
    ],
    "wheat": [
        "wheat", "semolina", "durum", "farina", "spelt", "seitan",
        "bulgur", "couscous", "graham flour", "matzo",
        "vital wheat gluten", "wheat gluten", "gluten flour",
        "tritordeum", "emmer", "einkorn", "kamut", "triticale", "atta", "maida", "freekeh",
        # Added 2026-08-09: pasta/noodle is wheat by default unless the description
        # names a specific non-wheat base (rice, mung bean, egg-only, etc.). Confirmed
        # gap via spot-check: 41/113 pasta/noodle records were UNKNOWN for wheat.
        "pasta", "macaroni", "noodle", "noodles", "spaghetti", "linguine",
        "fettuccine", "penne", "rigatoni", "vermicelli", "lasagna", "ravioli",
        "tortellini", "orzo", "ziti", "fusilli", "rotini",
    ],
    "soy": [
        "soy", "soybean", "tofu", "edamame", "miso", "tempeh",
        "soy lecithin", "soy protein", "tamari",
        "textured vegetable protein", "textured soy protein",
        "hydrolyzed soy protein", "soy flour", "soy isolate", "soy concentrate",
        "glycine max", "yuba", "natto", "kinako", "shoyu",
    ],
    "sesame": [
        "sesame", "tahini", "tahina", "benne", "gingelly", "halvah",
        "sesame oil", "sesamum indicum", "til", "simsim",
    ],
}

# Tier B: generic head nouns that require a modifier-pattern check.
# If preceded by one of these modifiers, the match is a non-allergen substitute
# and should NOT count as CONTAINS.
PLANT_MODIFIERS = [
    "almond", "oat", "soy", "coconut", "rice", "cashew", "hemp", "flax",
    "pea", "macadamia", "pistachio", "walnut", "quinoa", "hazelnut",
    "banana", "potato",
]

GENERIC_HEAD_NOUN_MODIFIERS = {
    "milk": PLANT_MODIFIERS,
    "butter": PLANT_MODIFIERS + ["peanut", "cocoa", "shea", "apple", "sunflower",
                                   "cookie", "pumpkin seed", "mango"],
    "cream": PLANT_MODIFIERS + ["oat"],
    "cheese": PLANT_MODIFIERS + ["vegan", "dairy-free", "plant-based"],
    "yogurt": PLANT_MODIFIERS + ["vegan", "dairy-free", "plant-based"],
    "mayonnaise": ["vegan", "plant-based", "egg-free"],
    "egg": ["vegan", "egg-free", "plant-based"],
    "fish": ["vegan", "fish-free", "plant-based", "fishless"],
    # Added 2026-08-09: pasta/noodle terms are wheat by default, but these named
    # non-wheat bases should gate the match, same pattern as almond milk / oat milk.
    "pasta": ["rice", "mung bean", "chickpea", "lentil", "quinoa", "corn",
              "shirataki", "konjac", "black bean", "edamame", "zucchini",
              "spaghetti squash", "gluten-free", "gluten free"],
    "noodle": ["rice", "mung bean", "chickpea", "lentil", "quinoa", "corn",
               "shirataki", "konjac", "black bean", "kelp", "glass",
               "cellophane", "gluten-free", "gluten free"],
    "noodles": ["rice", "mung bean", "chickpea", "lentil", "quinoa", "corn",
                "shirataki", "konjac", "black bean", "kelp", "glass",
                "cellophane", "gluten-free", "gluten free"],
}

# Fixed compound-noun exclusions -- these are NOT modifier patterns (no space-separated
# prefix that generalizes), they're specific known phrases that happen to contain an
# allergen substring. Small, finite list, unlike the open-ended modifier problem.
COMPOUND_NOUN_EXCLUSIONS = [
    "crab apple", "crabapple",
    "water chestnut",
    "cream of tartar", "creamed corn", "creamed honey", "cream soda",
    "pine apple", "pineapple",
    "wheat grass", "wheatgrass",
    "bean curd",  # tofu -- soy, not dairy, despite containing "curd"
    "custard apple",  # fruit, not dairy custard
    # Added 2026-08-09: spaghetti squash is a vegetable, not pasta -- confirmed
    # false-hit risk from the new "spaghetti" wheat term.
    "spaghetti squash",
]

CONTAINS_PATTERN = re.compile(r'CONTAINS:?\s+(?!LESS THAN)([A-Z][A-Z,\s]*?)(?:\.|$)', re.IGNORECASE)
MAY_CONTAIN_PATTERN = re.compile(r'MAY CONTAIN:?\s+([A-Z][A-Z,\s]*?)(?:\.|$)', re.IGNORECASE)


def is_compound_exclusion(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a matched term is actually part of a known compound-noun exclusion
    (e.g. matched "crab" but it's really "crab apple").
    """
    # Look at a window around the match for known compound phrases
    window_start = max(0, match_start - 15)
    window_end = min(len(text), match_end + 15)
    window = text[window_start:window_end].lower()

    if any(phrase in window for phrase in COMPOUND_NOUN_EXCLUSIONS):
        return True

    return False


def is_spaghetti_squash(text: str, term: str) -> bool:
    """
    USDA descriptions are comma-reordered ("Squash, winter, spaghetti, cooked...")
    so "spaghetti" and "squash" aren't adjacent like a normal compound phrase --
    the standard window-based compound exclusion above misses it. Catch it
    directly: if the "spaghetti" wheat-term match came from a description that
    also contains "squash" anywhere, it's the vegetable, not pasta.
    """
    return term == "spaghetti" and "squash" in text


def is_modifier_gated_false_positive(text: str, term: str, match_start: int) -> bool:
    """
    For Tier B generic head nouns (milk, butter, cream, etc.), check whether the
    match is preceded by a known non-allergen modifier (e.g. "almond" before "milk").

    Returns True if this is a false positive (should NOT count as CONTAINS).
    """
    modifiers = GENERIC_HEAD_NOUN_MODIFIERS.get(term)
    if not modifiers:
        return False  # not a gated term, no check needed

    # Look at the word(s) immediately before the match
    preceding_text = text[max(0, match_start - 30):match_start].lower().strip()

    for modifier in modifiers:
        if preceding_text.endswith(modifier):
            return True

    return False


def extract_explicit_statement(ingredients_text: str, pattern: re.Pattern) -> set:
    """
    Extract allergen names from an explicit CONTAINS: or MAY CONTAIN: statement.
    Returns set of matched allergen category names (e.g. {"milk", "wheat"}).

    Explicit statements are FDA-mandated and complete by law -- no modifier-gating
    needed here, a "CONTAINS: MILK" statement means milk, full stop.
    """
    if not ingredients_text:
        return set()

    match = pattern.search(ingredients_text)
    if not match:
        return set()

    statement_text = match.group(1).lower()
    found = set()

    for allergen, terms in ALLERGEN_TERMS.items():
        for term in terms:
            if term in statement_text:
                found.add(allergen)
                break

    return found


def scan_ingredients_for_terms(ingredients_text: str) -> set:
    """
    Scan raw ingredient text for allergen derivative terms.
    Lower confidence than an explicit statement -- used only when no
    CONTAINS: statement is present.

    Applies compound-noun exclusion and modifier-gating to Tier B terms
    to avoid false positives like "almond milk" -> milk, "crab apple" -> shellfish.
    """
    if not ingredients_text:
        return set()

    text_lower = ingredients_text.lower()
    found = set()

    for allergen, terms in ALLERGEN_TERMS.items():
        for term in terms:
            for m in re.finditer(r'\b' + re.escape(term) + r'\b', text_lower):
                # Check compound-noun exclusions (crab apple, water chestnut, etc.)
                if is_compound_exclusion(text_lower, m.start(), m.end()):
                    continue

                # Check spaghetti-squash special case (comma-reordered USDA naming)
                if is_spaghetti_squash(text_lower, term):
                    continue

                # Check modifier-gating for generic head nouns (almond milk, peanut butter)
                if is_modifier_gated_false_positive(text_lower, term, m.start()):
                    continue

                # Genuine match
                found.add(allergen)
                break
            if allergen in found:
                break

    return found


def extract_allergen_states(ingredients_text: str) -> dict:
    """
    Full three-state extraction for one product across all 9 allergens.

    Returns dict like:
    {
        "milk": "CONTAINS",
        "egg": "FREE",
        "fish": "UNKNOWN",
        ...
    }
    """
    all_allergens = list(ALLERGEN_TERMS.keys())

    # No ingredients data at all -> UNKNOWN across the board
    if not ingredients_text or not ingredients_text.strip():
        return {a: "UNKNOWN" for a in all_allergens}

    # Priority 1: explicit CONTAINS: statement
    explicit_contains = extract_explicit_statement(ingredients_text, CONTAINS_PATTERN)

    if explicit_contains:
        # Statement present -> named allergens are CONTAINS, everything else is FREE
        # (FREE is only trustworthy here because FDA mandates completeness of this statement)
        states = {}
        for allergen in all_allergens:
            states[allergen] = "CONTAINS" if allergen in explicit_contains else "FREE"
        return states

    # Priority 2: no explicit statement -> scan raw ingredients (with modifier/compound gating)
    scanned_contains = scan_ingredients_for_terms(ingredients_text)

    states = {}
    for allergen in all_allergens:
        if allergen in scanned_contains:
            states[allergen] = "CONTAINS"
        else:
            # No match found -- could be genuinely absent, could be a missed derivative term.
            # Never assert FREE without an explicit statement.
            states[allergen] = "UNKNOWN"

    return states


def apply_may_contain_severity(states: dict, ingredients_text: str) -> dict:
    """
    Fold 'MAY CONTAIN: X' cross-contamination warnings into CONTAINS.
    Only call this when building the SEVERE payload variant --
    moderate severity should ignore cross-contamination warnings.
    """
    if not ingredients_text:
        return states

    may_contain = extract_explicit_statement(ingredients_text, MAY_CONTAIN_PATTERN)

    severe_states = dict(states)
    for allergen in may_contain:
        severe_states[allergen] = "CONTAINS"

    return severe_states


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    test_cases = [
        # Original tests
        "INGREDIENTS: WHEAT FLOUR, SUGAR, EGGS, BUTTER. CONTAINS: WHEAT, MILK, EGG.",
        "INGREDIENTS: RICE, WATER, SALT.",
        "INGREDIENTS: PEANUT BUTTER, SUGAR, PALM OIL. MAY CONTAIN: TREE NUTS.",
        "",
        "INGREDIENTS: SOY LECITHIN, COCOA, SUGAR.",
        # Modifier-gating and compound exclusions
        "INGREDIENTS: ALMOND MILK, VANILLA, SEA SALT.",  # should be milk: UNKNOWN, tree_nut: CONTAINS (almond)
        "INGREDIENTS: OAT MILK, OAT FLOUR.",  # milk: UNKNOWN (oat is a modifier, not tree_nut/other allergen)
        "INGREDIENTS: APPLE, CRAB APPLE CONCENTRATE, SUGAR.",  # shellfish: UNKNOWN (compound exclusion)
        "INGREDIENTS: WATER CHESTNUT, SOY SAUCE, GINGER.",  # tree_nut: UNKNOWN (compound exclusion), soy: CONTAINS
        "INGREDIENTS: VEGAN MAYONNAISE (SOY PROTEIN, VINEGAR).",  # egg: UNKNOWN (vegan-gated), soy: CONTAINS
        "INGREDIENTS: SHRIMP, OYSTER SAUCE, GARLIC.",  # shellfish: CONTAINS (both crustacean + mollusk)
        # New tests -- pasta/noodle wheat fix (2026-08-09)
        "Macaroni or pasta salad with tuna and egg",  # wheat: CONTAINS, fish: CONTAINS, egg: CONTAINS
        "Rice noodles, dry",  # wheat: UNKNOWN (rice-gated)
        "Long rice noodles, made from mung beans, cooked",  # wheat: UNKNOWN (mung bean-gated)
        "Squash, winter, spaghetti, cooked, boiled, drained, or baked, with salt",  # wheat: UNKNOWN (compound exclusion)
        "Beef, noodles, and vegetables excluding carrots, broccoli, and dark-green leafy; gravy",  # wheat: CONTAINS
        "Shrimp and noodles with cream or white sauce",  # wheat: CONTAINS, shellfish: CONTAINS
    ]

    for i, text in enumerate(test_cases, 1):
        print(f"\nTest {i}: {text[:70]}")
        states = extract_allergen_states(text)
        non_unknown = {k: v for k, v in states.items() if v != "UNKNOWN"}
        print(f"  Non-UNKNOWN states: {non_unknown}")
