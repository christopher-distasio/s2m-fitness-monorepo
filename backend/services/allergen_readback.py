"""Spec 3 Part C — voice-only allergen/negation read-back.

Runs AFTER Spec 2 confirmation, not as a new band in the policy table.
Typed/text input does not use this gate. Spec 2 ASK on negation/allergen_match
already blocks storage, so this gate covers the high-confidence voice case.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from backend.services.clarification import parse_clarification_command
from backend.services.confirmation import detect_negation_cues
from backend.services.dietary_filters import FDA_ALLERGENS, NON_ALLERGEN_TIER_1

ReadbackReply = Literal["yes", "no", "other"]

_ALLERGEN_ALIASES: dict[str, tuple[str, ...]] = {
    "peanut": ("peanut", "peanuts"),
    "milk": ("milk", "dairy", "lactose"),
    "egg": ("egg", "eggs"),
    "fish": ("fish",),
    "shellfish": ("shellfish", "shrimp", "crab", "lobster"),
    "tree_nut": ("tree nut", "tree nuts", "almond", "walnut", "cashew", "pecan"),
    "wheat": ("wheat",),
    "soy": ("soy", "soya"),
    "sesame": ("sesame",),
}

_RESTRICTION_ALIASES: dict[str, tuple[str, ...]] = {
    "gluten_free": ("gluten",),
    "lactose_free": ("lactose",),
    "vegan": ("vegan",),
    "vegetarian": ("vegetarian",),
    "kosher": ("kosher",),
    "halal": ("halal",),
}

_NO_RE = re.compile(
    r"^\s*(no|nope|nah|wrong|incorrect|that's wrong|thats wrong)\b",
    re.IGNORECASE,
)
_STATED_CLAIM_RE = re.compile(
    r"\b(?:i(?:'m| am) allergic to|allergic to|contains?|no|without|hold(?: the)?)\s+"
    r"(?P<item>[a-z][a-z\s]{0,30})",
    re.IGNORECASE,
)


def _alias_hits(token: str) -> list[str]:
    t = token.strip().lower()
    if not t:
        return []
    hits: list[str] = []
    for key, aliases in {**_ALLERGEN_ALIASES, **_RESTRICTION_ALIASES}.items():
        for alias in aliases:
            if alias in t or t in alias:
                hits.append(key)
                break
    for name in list(FDA_ALLERGENS) + list(NON_ALLERGEN_TIER_1):
        label = name.replace("_", " ")
        if label in t or t.startswith(label) or name in t:
            if name not in hits:
                hits.append(name)
    return hits


def explicit_allergen_declarations(raw_input: str) -> list[str]:
    """User-stated allergen/restriction claims (negation or explicit claim)."""
    claims: list[str] = []
    seen: set[str] = set()
    for item in detect_negation_cues(raw_input):
        if _alias_hits(item):
            phrase = f"no {item}"
            if phrase not in seen:
                claims.append(phrase)
                seen.add(phrase)
    for match in _STATED_CLAIM_RE.finditer(raw_input or ""):
        item = re.sub(r"\s+", " ", match.group("item")).strip().lower()
        item = re.split(r"\b(and|or|,|\.)\b", item, maxsplit=1)[0].strip()
        if _alias_hits(item):
            lead = match.group(0).split(match.group("item"))[0].strip().lower()
            phrase = f"{lead} {item}".strip()
            if "no " in phrase or phrase.startswith("without") or phrase.startswith("hold"):
                phrase = f"no {item}"
            if phrase not in seen:
                claims.append(phrase)
                seen.add(phrase)
    return claims


def needs_allergen_readback(
    parsed: dict,
    raw_input: str,
    input_modality: str | None,
) -> bool:
    if (input_modality or parsed.get("input_modality") or "text") != "voice":
        return False
    if not explicit_allergen_declarations(raw_input):
        return False
    confirmation = parsed.get("confirmation") or {}
    asked = confirmation.get("asked_fields") or []
    if "negation" in asked or "allergen_match" in asked:
        return False
    return True


def readback_prompt(claim: str) -> str:
    return f"Logging: {claim}. Is that correct?"


def defer_allergen_fields(parsed: dict, claim: str) -> dict:
    """Do not store the allergen/negation claim; mark the field unresolved."""
    event = dict(parsed.get("food_event") or {})
    event["stated_negation"] = None
    event["allergen_readback"] = {
        "status": "pending",
        "claim": claim,
        "fields": ["negation"],
    }
    parsed = dict(parsed)
    parsed["food_event"] = event
    parsed["stated_negation"] = None
    parsed["allergen_readback"] = event["allergen_readback"]
    events = parsed.get("food_events")
    if isinstance(events, list) and events and isinstance(events[0], dict):
        merged = dict(events[0])
        merged.update(event)
        parsed["food_events"] = [merged, *events[1:]]
    else:
        parsed["food_events"] = [event]
    return parsed


def apply_readback_to_event(event: dict | None, reply: ReadbackReply) -> dict:
    data = dict(event or {})
    pending = dict(data.get("allergen_readback") or {})
    claim = pending.get("claim")
    if reply == "yes" and claim:
        data["stated_negation"] = claim
        data["allergen_readback"] = {
            "status": "confirmed",
            "claim": claim,
            "fields": pending.get("fields") or ["negation"],
        }
    else:
        data["stated_negation"] = None
        data["allergen_readback"] = {
            "status": "unresolved",
            "claim": None,
            "fields": pending.get("fields") or ["negation"],
        }
    return data


def classify_readback_reply(text: str) -> ReadbackReply:
    command = parse_clarification_command(text)
    if command and command.get("type") == "confirm":
        return "yes"
    if _NO_RE.search((text or "").strip()):
        return "no"
    t = (text or "").strip().lower()
    if t in {"no", "nope", "nah", "wrong", "incorrect", "cancel"}:
        return "no"
    return "other"


def allergen_readback_payload(parsed: dict, raw_input: str, log_id: str | None) -> dict:
    claims = explicit_allergen_declarations(raw_input)
    claim = claims[0] if claims else "the allergen note"
    prompt = readback_prompt(claim)
    return {
        "pending": True,
        "claim": claim,
        "log_id": log_id,
        "message": prompt,
        "fields": ["negation"],
    }
