"""Recognize voice replies to an open clarification prompt.

When the app has just asked a numbered "did you mean 1, 2, 3…?" question, the
user's next utterance is usually a *command about that list* ("one", "number
three", "repeat", "more") rather than a brand-new food. Those must be caught
BEFORE the normal food parser runs, otherwise a bare "one" can be combined with
the previous food and silently auto-logged.

This module is intentionally tiny and pure so it's trivial to unit-test and so
the same recognition is reused wherever it's needed. It only ever *classifies*
the utterance — the frontend owns which options are currently shown (trimmed vs
expanded) and therefore does the number-to-item resolution and the logging.
"""
import json
import re

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

# Whole-utterance matches only — we don't want "more chicken" to read as "more"
# or "one banana" to read as "select 1".
_REPEAT_PHRASES = {
    "repeat", "repeat that", "say it again", "say that again", "again",
    "one more time", "come again", "what were they", "what are they",
    "what were those", "read them again", "list them again",
}
_MORE_PHRASES = {
    "more", "hear more", "show more", "see more", "tell me more",
    "the rest", "others", "other options", "more options", "what else",
    "more please", "hear the rest",
}

_WORD_NUMBER_RE = re.compile(
    r"^(?:the\s+|a\s+)?"
    r"(?:number\s+|option\s+|choice\s+|item\s+)?"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"(?:\s+one)?$"
)
_DIGIT_RE = re.compile(
    r"^(?:the\s+|a\s+)?"
    r"(?:number\s*|option\s*|choice\s*|item\s*|#)?"
    r"(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s+one)?$"
)


def _normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s#]", " ", t)      # drop punctuation (keep # for "#3")
    t = re.sub(r"\s+", " ", t).strip()
    # Strip a few polite trailers that don't change meaning.
    for trailer in (" please", " thanks", " thank you"):
        if t.endswith(trailer):
            t = t[: -len(trailer)].strip()
    return t


def parse_clarification_command(text: str) -> dict | None:
    """Classify an utterance as a list command, or None if it's something else
    (e.g. a real food name) that should fall through to normal parsing.

    Returns one of:
      {"type": "select", "index": <1-based int>}
      {"type": "repeat"}
      {"type": "more"}
    """
    t = _normalize(text)
    if not t:
        return None

    if t in _REPEAT_PHRASES:
        return {"type": "repeat"}
    if t in _MORE_PHRASES:
        return {"type": "more"}

    digit = _DIGIT_RE.match(t)
    if digit:
        n = int(digit.group(1))
        if 1 <= n <= 20:
            return {"type": "select", "index": n}
        return None

    word = _WORD_NUMBER_RE.match(t)
    if word:
        return {"type": "select", "index": _WORD_NUMBERS[word.group(1)]}

    return None


# Words that answer "a specific brand, or a general item?".
_BRAND_WORDS = {
    "brand", "branded", "a brand", "specific", "specific brand", "a specific brand",
    "brand name", "name brand", "packaged", "store brand", "particular brand",
}
_GENERIC_WORDS = {
    "generic", "general", "a general item", "general item", "plain", "regular",
    "normal", "basic", "any", "whatever", "just the generic", "the generic",
    "standard", "the general one", "no brand", "any brand",
}


def parse_brand_choice(text: str) -> str | None:
    """Classify a reply to the brand-vs-generic question as "brand" or
    "generic", or None if it's neither (fall through to normal parsing)."""
    t = _normalize(text)
    if not t:
        return None
    if t in _BRAND_WORDS:
        return "brand"
    if t in _GENERIC_WORDS:
        return "generic"
    return None


def clarification_state(history: list[dict]) -> str | None:
    """Which kind of clarification (if any) the most recent assistant turn is
    waiting on: "brand_choice" (the upfront brand-vs-generic question) or
    "list" (a numbered candidate/portion list). None means no open
    clarification, so an utterance is a fresh food, not a command."""
    if not history:
        return None
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        try:
            data = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            return None
        status = (data.get("resolution") or {}).get("status")
        if status == "needs_brand_choice":
            return "brand_choice"
        confidence = data.get("confidence")
        has_options = bool(data.get("candidates")) or bool(
            data.get("portion_options")
        )
        if status == "needs_clarification" or (
            confidence in ("medium", "low") and has_options
        ):
            return "list"
        return None
    return None


def is_awaiting_clarification(history: list[dict]) -> bool:
    """Back-compat helper: True when any clarification is open."""
    return clarification_state(history) is not None
