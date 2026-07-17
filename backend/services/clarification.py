"""Recognize voice replies to an open clarification prompt.

When the app has just asked a numbered "did you mean…?" question, the user's
next utterance is usually a *command about that list* ("one", "repeat", "more")
rather than a brand-new food. Those must be caught BEFORE the normal food
parser runs.

This module only *classifies* the utterance. The frontend owns which options
are currently shown and does number-to-item resolution / logging.
conversation_history is used only to detect which clarification is open
(brand_choice vs list), not to store the spoken option list.
"""
import json
import re

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

# Whole-utterance only — "more chicken" / "one banana" must fall through.
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
_YES_MORE_TIME_PHRASES = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
    "more time", "need more time", "i need more time", "give me more time",
    "a little more time", "keep listening", "keep going", "continue",
}
_NO_STOP_PHRASES = {
    "no", "nope", "nah", "no thanks", "stop", "stop listening",
    "never mind", "nevermind", "cancel", "dismiss", "forget it",
    "forget that", "i m done", "im done", "i am done", "quit",
    "nothing", "skip",
}
# Narrower than _NO_STOP_PHRASES so a lone "no" during food logging isn't cancel.
_STOP_ANYTIME_PHRASES = {
    "stop", "stop listening", "stop now", "please stop", "stop please",
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

# Spoken order: Number 1 = general, Number 2 = specific. Whisper often hears
# "two" as "to"/"too".
_GENERAL_INDEX_TOKENS = frozenset({"one", "1", "first"})
_SPECIFIC_INDEX_TOKENS = frozenset({"two", "to", "too", "2", "second"})
_BRAND_INDEX_RE = re.compile(
    r"^(?:the\s+|a\s+)?"
    r"(?:number\s+|option\s+|choice\s+|item\s+)?"
    r"(one|two|to|too|1|2|first|second)"
    r"(?:\s+one)?$"
)
_BRAND_INDEX_LEAD_RE = re.compile(
    r"^(?:number|option|choice|item)\s+"
    r"(one|two|to|too|1|2|first|second)\b"
)
_BRAND_DIGIT_LEAD_RE = re.compile(r"^([12])(?:st|nd|rd|th)?\b")

_BRAND_WORDS = {
    "brand", "branded", "a brand", "specific", "specific brand", "a specific brand",
    "brand name", "name brand", "packaged", "store brand", "particular brand",
    "the brand", "the specific one", "specific one",
}
_GENERAL_WORDS = {
    "general", "generic", "a general", "a general item", "general item",
    "the general", "the general one", "general one", "plain", "regular",
    "normal", "basic", "just the general", "just the generic",
    "the generic", "standard", "no brand", "not a brand", "not brand", "unbranded",
}
_BRAND_TOKENS = frozenset({"brand", "branded", "specific", "packaged"})
_GENERAL_TOKENS = frozenset({"general", "generic", "plain", "regular", "unbranded"})


def _normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s#]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for trailer in (" please", " thanks", " thank you"):
        if t.endswith(trailer):
            t = t[: -len(trailer)].strip()
    return t


def _source_from_index_token(token: str) -> str | None:
    """Map prompt index token → API source key (generic | brand)."""
    if token in _GENERAL_INDEX_TOKENS:
        return "generic"
    if token in _SPECIFIC_INDEX_TOKENS:
        return "brand"
    return None


def _source_from_select_index(index: int) -> str | None:
    if index == 1:
        return "generic"
    if index == 2:
        return "brand"
    return None


def parse_clarification_command(text: str) -> dict | None:
    """Classify a list command, or None to fall through to food parsing.

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
        return {"type": "select", "index": n} if 1 <= n <= 20 else None

    word = _WORD_NUMBER_RE.match(t)
    if word:
        return {"type": "select", "index": _WORD_NUMBERS[word.group(1)]}
    return None


def parse_timeout_choice(text: str) -> str | None:
    """Reply to "Do you need more time?" → "more_time" | "stop" | None."""
    t = _normalize(text)
    if not t:
        return None
    if t in _YES_MORE_TIME_PHRASES:
        return "more_time"
    if t in _NO_STOP_PHRASES:
        return "stop"
    return None


def parse_stop_command(text: str) -> bool:
    """True when the user said stop — ends listening at any time."""
    t = _normalize(text)
    return bool(t) and t in _STOP_ANYTIME_PHRASES


def parse_brand_choice(text: str) -> str | None:
    """Brand-vs-general reply → "brand" | "generic" (API source key) | None.

    Accepts words (general/specific/brand/…), numbers (1 = general, 2 = specific),
    and short Whisper variants ("to" for "two", "I said general").
    """
    t = _normalize(text)
    if not t:
        return None
    if t in _BRAND_WORDS:
        return "brand"
    if t in _GENERAL_WORDS:
        return "generic"

    num = _BRAND_INDEX_RE.match(t)
    if num:
        return _source_from_index_token(num.group(1))

    command = parse_clarification_command(t)
    if command and command.get("type") == "select":
        return _source_from_select_index(command["index"])

    tokens = set(t.split())
    brand_hits = tokens & _BRAND_TOKENS
    general_hits = tokens & _GENERAL_TOKENS
    if brand_hits and not general_hits:
        return "brand"
    if general_hits and not brand_hits:
        return "generic"

    lead = _BRAND_INDEX_LEAD_RE.match(t)
    if lead:
        return _source_from_index_token(lead.group(1))
    lead_digit = _BRAND_DIGIT_LEAD_RE.match(t)
    if lead_digit:
        return _source_from_select_index(int(lead_digit.group(1)))
    return None


def clarification_state(history: list[dict]) -> str | None:
    """Open clarification kind from the latest assistant turn, or None."""
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
    return clarification_state(history) is not None
