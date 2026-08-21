"""Spec 0 — safety detector.

Lightweight keyword/pattern check that MUST run on every utterance (voice and
text) before domain-boundary filtering and before intent classification.

False positives on self-harm are cheap; false negatives are not. This pass is
a pattern layer only — not a comprehensive clinical classifier.
TODO: replace the self-harm pattern list with a more robust detector later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.services.restriction_eval import evaluate_restrictions
from backend.services.user_logs import latest_log_for_user, load_user_profile

SafetyCategory = Literal["medical_reaction", "self_harm"]

# Phrases we must never emit (D2 — report, never assert safety).
FORBIDDEN_SAFETY_ASSERTIONS = (
    "is safe",
    "you're safe",
    "you are safe",
    "this is fine",
    "this is safe",
    "should be fine",
    "you're fine",
    "you are fine",
    "probably the cause",
    "this was probably",
)

# Acute allergic / medical reaction — highest relevance to a food app.
_MEDICAL_RE = re.compile(
    r"""
    \b(
        allergic\s+reaction
        | anaphylax(is|tic)
        | can'?t\s+breathe
        | cannot\s+breathe
        | trouble\s+breathing
        | throat\s+(feels\s+)?(tight|closing|swollen)
        | tongue\s+(is\s+|feels\s+)?swollen
        | lips?\s+(are\s+|feel\s+)?swollen
        | reacting\s+to\s+(something\s+i\s+ate|the\s+food|what\s+i\s+ate)
        | (need|get)\s+(my\s+)?epi(\s*pen)?
        | hives
        | dizzy\s+after\s+eating
        | passing\s+out
        | going\s+to\s+(pass\s+out|faint)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Conservative self-harm / crisis flags. Do not attempt nuance here.
# TODO: more robust self-harm classifier — pattern layer is sufficient for Spec 0.
_SELF_HARM_RE = re.compile(
    r"""
    \b(
        kill\s+myself
        | want\s+to\s+die
        | end\s+my\s+life
        | suicidal
        | suicide
        | self[-\s]?harm
        | hurt\s+myself
        | cut\s+myself
        | don'?t\s+want\s+to\s+be\s+alive
        | better\s+off\s+dead
        | going\s+to\s+purge
        | make\s+myself\s+throw\s+up
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

MEDICAL_ACKNOWLEDGMENT = (
    "I heard that you may be having a medical reaction. "
    "I can't provide medical guidance. If this is an emergency, call 911."
)

SELF_HARM_RESPONSE = (
    "I'm sorry you're going through this. I can't help with that here. "
    "If you're in immediate danger, call 911. "
    "You can also reach the Suicide and Crisis Lifeline by calling or texting 988."
)


@dataclass(frozen=True)
class SafetyHit:
    category: SafetyCategory
    matched: str


def detect_safety(text: str) -> SafetyHit | None:
    """Return a hit if the utterance is safety-relevant. No I/O, no LLM."""
    if not text or not text.strip():
        return None
    # Medical emergencies first when both could match — breathing/anaphylaxis
    # needs 911, not a crisis-line-only reply.
    medical = _MEDICAL_RE.search(text)
    if medical:
        return SafetyHit(category="medical_reaction", matched=medical.group(0))
    crisis = _SELF_HARM_RE.search(text)
    if crisis:
        return SafetyHit(category="self_harm", matched=crisis.group(0))
    return None


def _food_record_from_log(log) -> dict:
    if getattr(log, "food_event", None):
        return dict(log.food_event)
    return {
        "food": log.food_name,
        "allergen_state": {},
        "restriction_tags": {},
        "certification_status": {},
    }


def _factual_record_lines(log, profile) -> list[str]:
    """What the record shows — never an interpretation of cause or safety."""
    record = _food_record_from_log(log)
    lines = [f"Your most recent log is {log.food_name}."]
    verdict = evaluate_restrictions(record, profile)
    for reason in verdict.reasons:
        lines.append(f"The record shows: {reason}.")
    states = record.get("allergen_state") or {}
    for name, state in states.items():
        if any(name in r.lower() for r in verdict.reasons):
            continue
        lines.append(f"The record lists {name} as {state}.")
    cert = record.get("certification_status") or {}
    for name, status in cert.items():
        lines.append(f"The record lists {name} certification as {status}.")
    return lines


def contains_safety_assertion(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in FORBIDDEN_SAFETY_ASSERTIONS)


async def build_safety_response(
    hit: SafetyHit,
    user_id: str | None,
    raw_input: str,
) -> dict:
    """Canonical safety copy. Callers must pass `message` through speak()."""
    if hit.category == "self_harm":
        message = SELF_HARM_RESPONSE
    else:
        parts = [MEDICAL_ACKNOWLEDGMENT]
        if user_id:
            log = await latest_log_for_user(user_id)
            profile = await load_user_profile(user_id) if log else None
            if log is not None:
                parts.extend(_factual_record_lines(log, profile))
        message = " ".join(parts)

    if contains_safety_assertion(message):
        # Last-line defense: never ship a safety assertion even if copy drifts.
        message = MEDICAL_ACKNOWLEDGMENT if hit.category == "medical_reaction" else SELF_HARM_RESPONSE

    return {
        "error": "safety",
        "safety_category": hit.category,
        "message": message,
        "transcription": raw_input,
        "logged": False,
    }
