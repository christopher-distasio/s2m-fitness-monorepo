"""Unit tests for voice clarification reply classifiers.

These must stay pure (no network): Whisper transcripts arrive as text, and we
recognize digit/word numbers, repeat/more, and brand-vs-generic answers before
the food parser can combine a bare "one" with the previous food.
"""
import json

from backend.services.clarification import (
    clarification_state,
    is_awaiting_clarification,
    parse_brand_choice,
    parse_clarification_command,
    parse_stop_command,
    parse_timeout_choice,
)


def _history(payload: dict) -> list[dict]:
    return [{"role": "assistant", "content": json.dumps(payload)}]


# --- parse_clarification_command: numbers (digit + word forms) ---


def test_select_digit_forms():
    assert parse_clarification_command("1") == {"type": "select", "index": 1}
    assert parse_clarification_command("3") == {"type": "select", "index": 3}
    assert parse_clarification_command("#2") == {"type": "select", "index": 2}
    assert parse_clarification_command("number 3") == {"type": "select", "index": 3}
    assert parse_clarification_command("option 2") == {"type": "select", "index": 2}
    assert parse_clarification_command("the 3rd") == {"type": "select", "index": 3}
    assert parse_clarification_command("3 please") == {"type": "select", "index": 3}


def test_select_word_forms():
    assert parse_clarification_command("one") == {"type": "select", "index": 1}
    assert parse_clarification_command("two") == {"type": "select", "index": 2}
    assert parse_clarification_command("number three") == {
        "type": "select",
        "index": 3,
    }
    assert parse_clarification_command("the third one") == {
        "type": "select",
        "index": 3,
    }
    assert parse_clarification_command("option two") == {
        "type": "select",
        "index": 2,
    }


def test_repeat_and_more():
    assert parse_clarification_command("repeat") == {"type": "repeat"}
    assert parse_clarification_command("say it again") == {"type": "repeat"}
    assert parse_clarification_command("more") == {"type": "more"}
    assert parse_clarification_command("hear more") == {"type": "more"}
    assert parse_clarification_command("what else") == {"type": "more"}


def test_food_names_fall_through_not_commands():
    """Additive gate: naming a food/brand directly must NOT be classified."""
    assert parse_clarification_command("banana") is None
    assert parse_clarification_command("one banana") is None
    assert parse_clarification_command("more chicken") is None
    assert parse_clarification_command("the raisin bran one") is None
    assert parse_clarification_command("a small bowl") is None
    assert parse_clarification_command("") is None


# --- parse_brand_choice ---


def test_brand_choice_words():
    assert parse_brand_choice("brand") == "brand"
    assert parse_brand_choice("specific") == "brand"
    assert parse_brand_choice("a specific brand") == "brand"
    assert parse_brand_choice("generic") == "generic"
    assert parse_brand_choice("general") == "generic"
    assert parse_brand_choice("plain") == "generic"
    assert parse_brand_choice("1") == "generic"
    assert parse_brand_choice("number two") == "brand"
    assert parse_brand_choice("two") == "brand"
    assert parse_brand_choice("to") == "brand"  # Whisper mishear of "two"
    assert parse_brand_choice("I said general") == "generic"
    assert parse_brand_choice("number 2 please") == "brand"
    assert parse_brand_choice("um brand") == "brand"
    assert parse_brand_choice("specific") == "brand"
    assert parse_brand_choice("Chobani") is None
    assert parse_brand_choice("yogurt") is None


def test_stop_anytime():
    assert parse_stop_command("stop") is True
    assert parse_stop_command("stop listening") is True
    assert parse_stop_command("stop now") is True
    assert parse_stop_command("no") is False
    assert parse_stop_command("stop eating") is False
    assert parse_stop_command("banana") is False


def test_timeout_choice():
    assert parse_timeout_choice("yes") == "more_time"
    assert parse_timeout_choice("yeah") == "more_time"
    assert parse_timeout_choice("sure") == "more_time"
    assert parse_timeout_choice("more time") == "more_time"
    assert parse_timeout_choice("no") == "stop"
    assert parse_timeout_choice("nope") == "stop"
    assert parse_timeout_choice("stop") == "stop"
    assert parse_timeout_choice("never mind") == "stop"
    # Must not steal list commands or food names.
    assert parse_timeout_choice("more") is None
    assert parse_timeout_choice("one") is None
    assert parse_timeout_choice("banana") is None
    assert parse_timeout_choice("one more time") is None
    assert parse_timeout_choice("hold on") is None


# --- clarification_state / is_awaiting_clarification ---


def test_state_brand_choice():
    history = _history(
        {
            "confidence": "medium",
            "resolution": {"status": "needs_brand_choice"},
            "candidates": [],
        }
    )
    assert clarification_state(history) == "brand_choice"
    assert is_awaiting_clarification(history) is True


def test_state_list_from_needs_clarification():
    history = _history(
        {
            "confidence": "medium",
            "resolution": {"status": "needs_clarification"},
            "candidates": [{"name": "Banana"}],
        }
    )
    assert clarification_state(history) == "list"


def test_state_list_from_medium_with_options():
    history = _history(
        {
            "confidence": "medium",
            "candidates": [{"name": "Banana"}],
            "portion_options": [],
        }
    )
    assert clarification_state(history) == "list"


def test_state_none_when_high_confidence_or_empty():
    assert clarification_state([]) is None
    assert (
        clarification_state(
            _history({"confidence": "high", "candidates": [], "portion_options": []})
        )
        is None
    )
    assert is_awaiting_clarification([]) is False
