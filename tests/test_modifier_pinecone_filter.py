"""Offline unit tests for modifier → Qdrant filter builders."""

from qdrant_client.http import models as qmodels

from backend.services.nutrition_service import (
    _combine_filters,
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


def test_combine_with_source_merges_must_clauses():
    combined = _combine_filters(
        _source_qdrant_condition("generic"),
        _modifiers_qdrant_conditions(
            {"cooking_method": "COOKING_FAT", "skin_status": "SKIN_OFF"}
        ),
        None,
    )
    assert combined is not None
    assert combined.must is not None
    assert len(combined.must) == 3  # source + 2 modifiers
    assert combined.must_not is None


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
