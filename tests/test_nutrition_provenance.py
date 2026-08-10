"""Unit tests for Vitamin A / Folate / Vitamin D provenance tagging.

Deterministic — no network. Covers the rules locked in during the
nutrition backfill session (no IU→RAE conversion; folate total fallback;
Vitamin D IU/40).
"""

from nutrition_provenance import VITAMIN_D_IU_TO_MCG, apply_micronutrient_provenance


def test_vitamin_d_iu_to_mcg_ratio_matches_fda_example():
    """FDA example: 800 IU → 20 mcg."""
    assert VITAMIN_D_IU_TO_MCG == 40.0
    assert round(800 / VITAMIN_D_IU_TO_MCG, 2) == 20.0


def test_vitamin_a_measured_rae_keeps_rae_and_tags():
    food = {"vitamin_a_rae_mcg": 58.0, "vitamin_a_iu": None}
    apply_micronutrient_provenance(food)
    assert food["vitamin_a_rae_mcg"] == 58.0
    assert food["vitamin_a_source"] == "measured_rae"


def test_vitamin_a_iu_only_does_not_convert_to_rae():
    food = {"vitamin_a_rae_mcg": None, "vitamin_a_iu": 820.0}
    apply_micronutrient_provenance(food)
    assert food["vitamin_a_rae_mcg"] is None
    assert food["vitamin_a_iu"] == 820.0
    assert food["vitamin_a_source"] == "unsupported_conversion"


def test_vitamin_a_neither_is_no_data():
    food = {"vitamin_a_rae_mcg": None, "vitamin_a_iu": None}
    apply_micronutrient_provenance(food)
    assert food["vitamin_a_rae_mcg"] is None
    assert food["vitamin_a_source"] == "no_data"


def test_folate_measured_dfe():
    food = {"folate_dfe_mcg": 36.0, "folate": None}
    apply_micronutrient_provenance(food)
    assert food["folate_dfe_mcg"] == 36.0
    assert food["folate_source"] == "measured_dfe"


def test_folate_fallback_copies_total_into_dfe():
    food = {"folate_dfe_mcg": None, "folate": 160.0}
    apply_micronutrient_provenance(food)
    assert food["folate_dfe_mcg"] == 160.0
    assert food["folate"] == 160.0
    assert food["folate_source"] == "fallback_from_total"


def test_folate_neither_is_no_data():
    food = {"folate_dfe_mcg": None, "folate": None}
    apply_micronutrient_provenance(food)
    assert food["folate_dfe_mcg"] is None
    assert food["folate_source"] == "no_data"


def test_vitamin_d_measured_mcg():
    food = {"vitamin_d_mcg": 2.0, "vitamin_d_iu": None}
    apply_micronutrient_provenance(food)
    assert food["vitamin_d_mcg"] == 2.0
    assert food["vitamin_d_source"] == "measured_mcg"


def test_vitamin_d_converts_iu_with_fixed_ratio():
    food = {"vitamin_d_mcg": None, "vitamin_d_iu": 164.0}
    apply_micronutrient_provenance(food)
    assert food["vitamin_d_mcg"] == 4.1
    assert food["vitamin_d_iu"] == 164.0
    assert food["vitamin_d_source"] == "converted_from_iu"


def test_vitamin_d_neither_is_no_data():
    food = {"vitamin_d_mcg": None, "vitamin_d_iu": None}
    apply_micronutrient_provenance(food)
    assert food["vitamin_d_mcg"] is None
    assert food["vitamin_d_source"] == "no_data"


def test_measured_rae_preferred_even_when_iu_also_present():
    food = {"vitamin_a_rae_mcg": 10.0, "vitamin_a_iu": 500.0}
    apply_micronutrient_provenance(food)
    assert food["vitamin_a_source"] == "measured_rae"
    assert food["vitamin_a_rae_mcg"] == 10.0
