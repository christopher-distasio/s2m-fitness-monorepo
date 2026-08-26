"""Lactose-free filter accepts dairy-free; reverse is never inferred."""

from backend.models import AllergyConstraint, Tier1Preferences
from backend.services.confirmation import contrastive_question
from backend.services.dietary_filters import (
    build_tier_1_filter,
    is_dairy_free_not_lactose,
    is_literal_lactose_free,
    lactose_contrastive_resolution,
    lactose_groups_need_clarification,
    rank_lactose_preference,
    wants_lactose_avoidance,
)
from backend.services.modifier_extract import extract_literal_diet_claims


def _filter_keys(filt) -> set[str]:
    keys: set[str] = set()
    if filt is None:
        return keys
    for cond in list(filt.must or []) + list(filt.must_not or []):
        if getattr(cond, "key", None):
            keys.add(cond.key)
        for inner in getattr(cond, "should", None) or []:
            if getattr(inner, "key", None):
                keys.add(inner.key)
    return keys


def test_literal_claims_do_not_cross_map():
    both = extract_literal_diet_claims("lactose-free whole milk")
    assert both == {"lactose_free": "lactose_free"}
    dairy = extract_literal_diet_claims("dairy-free oat milk")
    assert dairy == {"dairy_free": "dairy_free"}
    assert "lactose_free" not in dairy


def test_lactose_filter_is_or_with_dairy_free():
    tier_1 = Tier1Preferences(lactose_free=True)
    filt = build_tier_1_filter(tier_1)
    assert filt is not None
    nested = filt.must[0]
    keys = {c.key for c in nested.should}
    assert keys == {"lactose_free", "dairy_free"}


def test_avoiding_dairy_does_not_accept_lactose_free_only():
    """Unsafe reverse: lactose-free cow's milk is still dairy."""
    vegan = build_tier_1_filter(Tier1Preferences(vegan=True))
    assert vegan.must[0].key == "vegan"
    assert "lactose_free" not in _filter_keys(vegan)
    assert "dairy_free" not in _filter_keys(vegan)

    milk = Tier1Preferences(
        allergens={"milk": AllergyConstraint(enabled=True, severity="severe")}
    )
    milk_filt = build_tier_1_filter(milk)
    assert _filter_keys(milk_filt) == {"milk", "milk_may_contain"}
    assert "lactose_free" not in _filter_keys(milk_filt)


def test_rank_literal_lactose_above_dairy_free():
    matches = [
        {"score": 0.9, "metadata": {"dairy_free": "dairy_free", "name": "oat"}},
        {"score": 0.85, "metadata": {"lactose_free": "lactose_free", "name": "LF milk"}},
    ]
    ranked = rank_lactose_preference(matches)
    assert ranked[0]["metadata"]["name"] == "LF milk"


def test_clarification_only_when_groups_are_close():
    close = [
        {"score": 0.80, "metadata": {"lactose_free": "lactose_free"}},
        {"score": 0.79, "metadata": {"dairy_free": "dairy_free"}},
    ]
    assert lactose_groups_need_clarification(close) is True
    far = [
        {"score": 0.95, "metadata": {"lactose_free": "lactose_free"}},
        {"score": 0.50, "metadata": {"dairy_free": "dairy_free"}},
    ]
    assert lactose_groups_need_clarification(far) is False
    only_lit = [{"score": 0.8, "metadata": {"lactose_free": "lactose_free"}}]
    assert lactose_groups_need_clarification(only_lit) is False
    only_plant = [{"score": 0.8, "metadata": {"dairy_free": "dairy_free"}}]
    assert lactose_groups_need_clarification(only_plant) is False


def test_lactose_clarification_reuses_spec2_contrastive_question():
    expected_q, expected_kind = contrastive_question(
        ["dairy milk without lactose", "a plant milk"],
        "food",
    )
    resolution = lactose_contrastive_resolution()
    assert resolution["status"] == "needs_clarification"
    assert resolution["axis"] == "lactose"
    assert resolution["kind"] == expected_kind == "contrastive"
    assert resolution["question"] == expected_q


def test_wants_lactose_from_utterance_or_profile():
    assert wants_lactose_avoidance("lactose-free milk", None) is True
    prefs = Tier1Preferences(lactose_free=True)
    assert wants_lactose_avoidance("milk", prefs) is True
    assert wants_lactose_avoidance("milk", None) is False


def test_tag_helpers():
    lit = {"metadata": {"lactose_free": "lactose_free", "dairy_free": "dairy_free"}}
    plant = {"metadata": {"dairy_free": "dairy_free"}}
    assert is_literal_lactose_free(lit) is True
    assert is_dairy_free_not_lactose(lit) is False
    assert is_dairy_free_not_lactose(plant) is True
