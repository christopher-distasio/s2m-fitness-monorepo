"""Offline unit tests for modifier → Pinecone metadata filter builders."""

from backend.services.nutrition_service import (
    _combine_pinecone_filters,
    _modifiers_pinecone_filter,
    _source_pinecone_filter,
)


def test_modifiers_filter_ignores_none_and_empty():
    assert _modifiers_pinecone_filter(None) is None
    assert _modifiers_pinecone_filter({}) is None
    assert _modifiers_pinecone_filter({"skin_status": "NONE"}) is None
    assert _modifiers_pinecone_filter({"skin_status": "NONE", "temp": ""}) is None


def test_modifiers_filter_single_and_multi():
    assert _modifiers_pinecone_filter({"skin_status": "SKIN_OFF"}) == {
        "skin_status": {"$eq": "SKIN_OFF"}
    }
    assert _modifiers_pinecone_filter(
        {
            "cooking_method": "COOKING_FAT",
            "skin_status": "SKIN_OFF",
            "fat_level": "NONE",
        }
    ) == {
        "$and": [
            {"cooking_method": {"$eq": "COOKING_FAT"}},
            {"skin_status": {"$eq": "SKIN_OFF"}},
        ]
    }


def test_combine_with_source_flattens_and():
    combined = _combine_pinecone_filters(
        _source_pinecone_filter("generic"),
        _modifiers_pinecone_filter(
            {"cooking_method": "COOKING_FAT", "skin_status": "SKIN_OFF"}
        ),
    )
    assert combined == {
        "$and": [
            {"source": {"$in": ["usda_sr_legacy", "usda_fndds"]}},
            {"cooking_method": {"$eq": "COOKING_FAT"}},
            {"skin_status": {"$eq": "SKIN_OFF"}},
        ]
    }


def test_combine_none_modifiers_keeps_source_only():
    assert _combine_pinecone_filters(
        _source_pinecone_filter("generic"),
        _modifiers_pinecone_filter(None),
    ) == {"source": {"$in": ["usda_sr_legacy", "usda_fndds"]}}
