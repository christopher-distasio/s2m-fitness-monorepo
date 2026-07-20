"""Regression tests for brand-name duplication ("Great Value Great Value…").

The live bug was brand+name concatenation when `name` already contained the
brand. These tests pin the *mechanism* (format_branded_name / process_branded
construction contract), not a single product string — so a one-off patch for
Great Value alone would fail the parametrized / pattern cases.
"""

from __future__ import annotations

import re

import pytest

from backend.services.nutrition_service import format_branded_name


def consecutive_brand_duplication(name: str, brand: str) -> bool:
    """True when `name` starts with the brand phrase twice in a row.

    Matches the audible failure mode: "GREAT VALUE GREAT VALUE POTATO CHIPS".
    Ignores legitimate later repeats of a single word that isn't the full brand.
    """
    name = (name or "").strip()
    brand = (brand or "").strip()
    if not name or not brand:
        return False
    # Normalize commas/punctuation the USDA often sticks on brand tokens.
    n = re.sub(r"[,]+", " ", name.lower())
    n = re.sub(r"\s+", " ", n).strip()
    b = re.sub(r"[,]+", " ", brand.lower())
    b = re.sub(r"\s+", " ", b).strip()
    if not b:
        return False
    return n.startswith(f"{b} {b}") or n.startswith(f"{b}, {b}")


def build_branded_search_name(brand_name: str, description: str) -> str:
    """Contract mirror of process_branded.py name construction.

    Uses brand_name only (not brand_owner). Skips prepend when the brand is
    already present in the description (case-insensitive).
    """
    brand = (brand_name or "").strip()
    description = (description or "").strip()
    if brand and brand.lower() not in description.lower():
        return f"{brand} {description}"
    return description


def spoken_candidate(
    name: str,
    brand: str | None,
    *,
    serving_label: str | None = None,
    calories: float | None = None,
) -> str:
    """Mirror of frontend speakCandidate (formatBrandedName + serving + kcal)."""
    parts = [format_branded_name(name, brand)]
    serving = (serving_label or "").strip()
    if serving:
        parts.append(serving)
    if calories is not None:
        parts.append(f"{int(round(calories))} calories")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Mechanism: general pattern (not Great-Value-only)
# ---------------------------------------------------------------------------

BRAND_ALREADY_IN_NAME = [
    ("GREAT VALUE", "GREAT VALUE POTATO CHIPS"),
    ("GREAT VALUE", "Great Value light Greek yogurt"),
    ("KROGER", "KROGER SMOKED DELI STYLE LEAN HAM, SMOKED"),
    ("CHOBANI", "CHOBANI NONFAT PLAIN YOGURT"),
    ("GOOD & GATHER", "GOOD & GATHER ROASTED ALMONDS"),
    ("MEMBER'S MARK", "MEMBER'S MARK TRAIL MIX"),
    ("KIRKLAND", "KIRKLAND SIGNATURE PROTEIN BAR"),
    ("PRIVATE SELECTION", "PRIVATE SELECTION SMOKED HAM"),
]


@pytest.mark.parametrize("brand,name", BRAND_ALREADY_IN_NAME)
def test_format_skips_prepend_for_many_brands_not_just_great_value(brand, name):
    """If this only passed for Great Value, the fix would be a narrow patch."""
    assert format_branded_name(name, brand) == name
    assert not consecutive_brand_duplication(format_branded_name(name, brand), brand)


@pytest.mark.parametrize(
    "brand,description,expected",
    [
        ("GREAT VALUE", "GREAT VALUE POTATO CHIPS", "GREAT VALUE POTATO CHIPS"),
        ("GREAT VALUE", "POTATO CHIPS", "GREAT VALUE POTATO CHIPS"),
        ("KROGER", "KROGER LEAN HAM", "KROGER LEAN HAM"),
        ("KROGER", "LEAN HAM", "KROGER LEAN HAM"),
        # brand_owner must NOT be used — description already has store brand
        ("", "GREAT VALUE, POTATO CHIPS", "GREAT VALUE, POTATO CHIPS"),
    ],
)
def test_process_branded_construction_contract(brand, description, expected):
    assert build_branded_search_name(brand, description) == expected
    if brand:
        assert not consecutive_brand_duplication(expected, brand)


def test_process_branded_does_not_prepend_owner_when_description_has_store_brand():
    """Regression: brand_owner 'Wal-Mart…' must not become the name prefix
    when description already starts with GREAT VALUE (old construction)."""
    description = "GREAT VALUE, POTATO CHIPS"
    # New contract: only brand_name participates. Empty brand_name → description.
    assert build_branded_search_name("", description) == description
    # Even if someone mistakenly passes owner as brand_name, the `in` check
    # still prevents Owner+Owner when owner is already in the description.
    owner = "Wal-Mart Stores, Inc."
    assert build_branded_search_name(owner, f"{owner} {description}").startswith(
        owner
    )
    assert not consecutive_brand_duplication(
        build_branded_search_name(owner, f"{owner} {description}"), owner
    )


# ---------------------------------------------------------------------------
# False-positive: legitimate repeated words must NOT be stripped
# ---------------------------------------------------------------------------

LEGITIMATE_REPEATS = [
    # Repeated product word, brand is different — keep both HOT tokens.
    ("TABASCO", "HOT HOT SAUCE", "TABASCO HOT HOT SAUCE"),
    ("PEPPERIDGE FARM", "VERY VERY BERRY", "PEPPERIDGE FARM VERY VERY BERRY"),
    # Name already includes brand once; extra non-brand repeat stays.
    ("GREAT VALUE", "GREAT VALUE MAYO MAYONNAISE", "GREAT VALUE MAYO MAYONNAISE"),
    ("KROGER", "KROGER DIP DIPPERS", "KROGER DIP DIPPERS"),
]


@pytest.mark.parametrize("brand,name,expected", LEGITIMATE_REPEATS)
def test_does_not_strip_legitimate_non_brand_repeated_words(brand, name, expected):
    assert format_branded_name(name, brand) == expected


def test_detector_ignores_non_brand_word_repeats():
    """'MAYO MAYONNAISE' is not brand duplication of GREAT VALUE."""
    name = "GREAT VALUE MAYO MAYONNAISE"
    assert not consecutive_brand_duplication(name, "GREAT VALUE")
    assert consecutive_brand_duplication(
        "GREAT VALUE GREAT VALUE MAYO MAYONNAISE", "GREAT VALUE"
    )


# ---------------------------------------------------------------------------
# Spoken / TTS path (same composition as frontend speakCandidate)
# ---------------------------------------------------------------------------


def test_spoken_great_value_candidate_has_no_audible_brand_repeat():
    speech = spoken_candidate(
        "GREAT VALUE POTATO CHIPS",
        "GREAT VALUE",
        serving_label="1 oz",
        calories=150,
    )
    assert "great value great value" not in speech.lower()
    assert speech.lower().startswith("great value potato chips")
    assert "150 calories" in speech


@pytest.mark.parametrize("brand,name", BRAND_ALREADY_IN_NAME)
def test_spoken_path_no_consecutive_brand_dup_for_general_pattern(brand, name):
    speech = spoken_candidate(name, brand, serving_label="1 serving", calories=100)
    assert not consecutive_brand_duplication(speech.split(",")[0], brand)
    assert brand.lower() in speech.lower()


def test_spoken_still_prepends_when_name_lacks_brand():
    speech = spoken_candidate("POTATO CHIPS", "GREAT VALUE", calories=150)
    assert speech.startswith("GREAT VALUE POTATO CHIPS")
    assert "great value great value" not in speech.lower()
