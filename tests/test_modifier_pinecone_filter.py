"""Offline unit tests for modifier → Qdrant filter builders."""

from qdrant_client.http import models as qmodels

from backend.services.nutrition_service import (
    _combine_filters,
    _modifier_gate,
    _modifiers_qdrant_conditions,
    _source_qdrant_condition,
)


def test_modifiers_filter_ignores_none_and_empty():
    assert _modifiers_qdrant_conditions(None) == []
    assert _modifiers_qdrant_conditions({}) == []
    assert _modifiers_qdrant_conditions({"skin_status": "NONE"}) == []
    assert _modifiers_qdrant_conditions({"skin_status": "NONE", "temp": ""}) == []


def test_modifiers_filter_single_and_multi():
    single = _modifiers_qdrant_conditions({"skin_status": "SKIN_OFF"})
    assert len(single) == 1
    assert single[0].key == "skin_status"
    assert single[0].match.value == "SKIN_OFF"

    multi = _modifiers_qdrant_conditions(
        {
            "cooking_method": "COOKING_FAT",
            "skin_status": "SKIN_OFF",
            "fat_level": "NONE",
        }
    )
    keys = {c.key for c in multi}
    assert keys == {"cooking_method", "skin_status"}
    assert len(multi) == 2


def test_combine_with_source_wraps_modifiers_in_the_gate():
    """Modifiers are one nested gate clause now, not N flat must clauses."""
    combined = _combine_filters(
        _source_qdrant_condition("generic"),
        _modifiers_qdrant_conditions(
            {"cooking_method": "COOKING_FAT", "skin_status": "SKIN_OFF"}
        ),
        None,
    )
    assert combined is not None
    assert combined.must is not None
    assert len(combined.must) == 2  # source + modifier gate
    assert combined.must_not is None

    source_clause, gate = combined.must
    assert source_clause.key == "source"
    assert isinstance(gate, qmodels.Filter)

    branded_branch, usda_branch = gate.should
    # Branded rows are admitted whatever their tags say...
    assert branded_branch.key == "source"
    assert branded_branch.match.any == ["branded_foods"]
    # ...while USDA-extracted tags stay a hard requirement.
    assert {c.key for c in usda_branch.must} == {"cooking_method", "skin_status"}


def test_gate_is_absent_when_no_modifiers_are_active():
    assert _modifier_gate([]) is None
    assert _modifier_gate(_modifiers_qdrant_conditions({"fat_level": "NONE"})) is None


def test_gate_keeps_allergen_must_not_at_top_level():
    """Nesting modifiers must not bury an allergen exclusion inside the OR."""
    tier_1 = qmodels.Filter(
        must_not=[
            qmodels.FieldCondition(
                key="peanut", match=qmodels.MatchValue(value="CONTAINS")
            )
        ]
    )
    combined = _combine_filters(
        None,
        _modifiers_qdrant_conditions({"cooking_method": "COOKING_FAT"}),
        tier_1,
    )
    assert combined.must_not is not None
    assert [c.key for c in combined.must_not] == ["peanut"]
    assert len(combined.must) == 1
    assert isinstance(combined.must[0], qmodels.Filter)


def test_combine_none_modifiers_keeps_source_only():
    combined = _combine_filters(
        _source_qdrant_condition("generic"),
        _modifiers_qdrant_conditions(None),
        None,
    )
    assert combined is not None
    assert len(combined.must) == 1
    assert isinstance(combined.must[0], qmodels.FieldCondition)
    assert combined.must[0].key == "source"
