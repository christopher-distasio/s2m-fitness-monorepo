"""Portion labels must be human words, not FNDDS measure codes."""

import json

from backend.services.nutrition_service import (
    _format_portion_label,
    build_portion_options,
    build_serving_label,
    get_serving_size_g,
)


def test_fndds_uses_description_not_numeric_modifier():
    portion = {
        "amount": 0.0,
        "unit": "undetermined",
        "description": "1 banana",
        "modifier": "60343",
        "gram_weight": 126.0,
        "seq_num": 1,
    }
    assert _format_portion_label(portion) == "1 banana"


def test_sr_legacy_still_uses_text_modifier():
    portion = {
        "amount": 1.0,
        "unit": "undetermined",
        "description": "",
        "modifier": "cup, mashed",
        "gram_weight": 225.0,
        "seq_num": 1,
    }
    assert _format_portion_label(portion) == "1 cup, mashed"


def test_fndds_banana_portion_options_are_words():
    meta = {
        "name": "Banana, raw",
        "source": "fndds",
        "calories": 97,
        "protein": 0.74,
        "carbs": 22.7,
        "fat": 0.28,
        "portions_json": json.dumps(
            [
                {
                    "amount": 0.0,
                    "unit": "undetermined",
                    "description": "1 banana",
                    "modifier": "60343",
                    "gram_weight": 126.0,
                    "seq_num": 1,
                },
                {
                    "amount": 0.0,
                    "unit": "undetermined",
                    "description": "1 slice",
                    "modifier": "61935",
                    "gram_weight": 6.0,
                    "seq_num": 2,
                },
                {
                    "amount": 0.0,
                    "unit": "undetermined",
                    "description": "1 cup, mashed",
                    "modifier": "10118",
                    "gram_weight": 225.0,
                    "seq_num": 4,
                },
                {
                    "amount": 0.0,
                    "unit": "undetermined",
                    "description": "Quantity not specified",
                    "modifier": "90000",
                    "gram_weight": 126.0,
                    "seq_num": 6,
                },
            ]
        ),
    }
    serving_g, source = get_serving_size_g(meta)
    assert build_serving_label(meta, serving_g, source) == "1 banana"
    labels = [o["label"] for o in build_portion_options(meta)]
    assert labels == ["1 slice", "1 banana", "1 cup, mashed"]
    # Last token must be words, not a 5-digit FNDDS measure code.
    assert all(not label.split()[-1].isdigit() for label in labels)
