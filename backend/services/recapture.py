"""Spec 4 — partial recapture for garbled/incomprehensible voice audio.

Runs BEFORE Spec 2 confirmation. Spec 2 needs a usable parse; this path
fires when extraction failed or Whisper food-identity ASR is too low to
trust. Typed input does not use recapture.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from backend.services.confidence import ASR_MEDIUM
from backend.services.confirmation import contrastive_question
from backend.services.response_compose import compose_response

# 3rd recapture attempt on the same missing piece uses the circuit-breaker.
RECAPTURE_FAILURES_BEFORE_BREAKER = 2

NOTHING_USABLE_PROMPT = "What did you eat?"
PARTIAL_PROMPT = "I caught '{food}' but missed what came after."
BREAKER_VARIED_PROMPT = "No rush — what did you eat? Take your time."
MODALITY_SWITCH_PROMPT = "Would it be easier to type this instead?"
TYPE_INSTEAD_REPLY_RE = re.compile(
    r"\b(type(?:\s+it)?(?:\s+instead)?|i(?:'ll|'ll)?\s+type)\b",
    re.IGNORECASE,
)

_FILLER = {
    "i",
    "i'd",
    "i've",
    "im",
    "i'm",
    "had",
    "have",
    "ate",
    "eaten",
    "a",
    "an",
    "the",
    "some",
    "my",
    "of",
    "and",
    "then",
    "with",
    "just",
    "like",
    "uh",
    "um",
    "uhh",
    "umm",
    "er",
    "ah",
    "hmm",
    "please",
    "log",
}

_AMOUNT_UNIT = {
    "cup",
    "cups",
    "ounce",
    "ounces",
    "oz",
    "gram",
    "grams",
    "g",
    "pound",
    "pounds",
    "lb",
    "lbs",
    "slice",
    "slices",
    "piece",
    "pieces",
    "bowl",
    "bowls",
    "plate",
    "tablespoon",
    "teaspoon",
    "tbsp",
    "tsp",
    "ml",
    "liter",
    "half",
    "quarter",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
}

_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _band(parsed: dict, field: str) -> str | None:
    detail = parsed.get("confidence_detail") or {}
    entry = detail.get(field) or {}
    if isinstance(entry, dict):
        return entry.get("band")
    return None


def _food_name(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return str(parsed.get("food") or parsed.get("food_name") or "").strip()


def food_identity_trusted(parsed: dict, asr: float | None) -> bool:
    """Reasonable confidence that the food name itself is usable."""
    food = _food_name(parsed)
    if not food:
        return False
    if parsed.get("error") in {"unparseable", "unresolved"}:
        return False
    if (parsed.get("resolution") or {}).get("status") == "unresolved":
        return False
    if parsed.get("resolution_status") == "unresolved":
        return False
    if asr is not None and asr < ASR_MEDIUM:
        return False
    band = _band(parsed, "food")
    if band == "low":
        return False
    return True


def unparsed_tail(transcript: str, food: str | None) -> str:
    """Leftover content after a captured food that did not parse as amount/unit."""
    if not food or not transcript:
        return ""
    t = transcript.lower()
    f = food.lower().strip()
    idx = t.find(f)
    if idx < 0:
        first = f.split()[0] if f else ""
        idx = t.find(first) if first else -1
        if idx < 0:
            return ""
        f = first
    rest = t[idx + len(f) :].strip(" .,!?;:")
    words = [re.sub(r"[^a-z0-9.]", "", w) for w in rest.split()]
    words = [w for w in words if w]
    leftover = [
        w
        for w in words
        if w not in _FILLER and w not in _AMOUNT_UNIT and not _NUMBER_RE.match(w)
    ]
    if leftover:
        return rest
    return ""


def missing_piece(parsed: dict, transcript: str, asr: float | None) -> str:
    """Which gap recapture is asking for. Used to keep the failure counter scoped."""
    if food_identity_trusted(parsed, asr):
        if unparsed_tail(transcript, _food_name(parsed)):
            return "trailing"
        return "trailing"
    return "food"


def should_enter_recapture(
    parsed: dict | None,
    transcript: str,
    asr: float | None,
    input_modality: str | None,
) -> bool:
    if (input_modality or "text") != "voice":
        return False
    if not (transcript or "").strip():
        return True
    parsed = parsed or {}
    if parsed.get("error") in {"unparseable"}:
        return True
    if parsed.get("error") in {"nutrition_unavailable", "safety", "off_domain", "allergy_block"}:
        return False
    if parsed.get("entry_mode") == "direct_macro":
        return False
    if (parsed.get("resolution") or {}).get("status") == "needs_brand_choice":
        return False
    if (parsed.get("confirmation") or {}).get("action") == "ASK":
        # Spec 2 already has a viable parse to ask about.
        if food_identity_trusted(parsed, asr) and not unparsed_tail(
            transcript, _food_name(parsed)
        ):
            return False
    if food_identity_trusted(parsed, asr):
        return bool(unparsed_tail(transcript, _food_name(parsed)))
    return True


def recapture_from_history(history: list | None) -> dict | None:
    if not history:
        return None
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except (json.JSONDecodeError, TypeError):
            return None
        recapture = data.get("recapture")
        if isinstance(recapture, dict) and recapture.get("pending"):
            return recapture
        return None
    return None


def merge_recapture_text(captured: dict | None, new_text: str) -> str:
    food = str((captured or {}).get("food") or "").strip()
    new = (new_text or "").strip()
    if food and new and food.lower() not in new.lower():
        return f"{food} {new}"
    return new or food


def _candidate_labels(parsed: dict | None) -> list[str]:
    labels: list[str] = []
    for c in (parsed or {}).get("candidates") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or c.get("food") or "").strip()
        if name and name not in labels:
            labels.append(name)
        if len(labels) >= 3:
            break
    return labels


def _compose(prompt: str) -> str:
    return compose_response("recapture", {"message": prompt})


def recapture_prompt(
    *,
    parsed: dict | None,
    transcript: str,
    asr: float | None,
    failures: int,
    input_modality: str | None = "voice",
    captured_food: str = "",
) -> dict[str, Any]:
    """Build the next recapture prompt. `failures` is consecutive misses so far."""
    trusted = (
        captured_food
        or (
            _food_name(parsed)
            if food_identity_trusted(parsed or {}, asr)
            else ""
        )
    )
    piece = missing_piece(parsed or {}, transcript, asr)
    if trusted and piece == "food":
        # Keep asking about the trailing gap if we already named a food.
        piece = "trailing"
    breaker = failures >= RECAPTURE_FAILURES_BEFORE_BREAKER
    modality_switch = False
    kind: Literal["partial", "empty", "contrastive", "modality_switch", "varied"]
    if breaker:
        labels = _candidate_labels(parsed)
        if 2 <= len(labels) <= 3:
            prompt, _k = contrastive_question(labels, "food")
            kind = "contrastive"
        elif (input_modality or "voice") == "voice":
            prompt = MODALITY_SWITCH_PROMPT
            kind = "modality_switch"
            modality_switch = True
        else:
            prompt = BREAKER_VARIED_PROMPT
            kind = "varied"
    elif trusted:
        prompt = PARTIAL_PROMPT.format(food=trusted)
        kind = "partial"
    else:
        prompt = NOTHING_USABLE_PROMPT
        kind = "empty"
    spoken = _compose(prompt)
    return {
        "pending": True,
        "prompt": spoken,
        "message": spoken,
        "captured": {"food": trusted} if trusted else {},
        "missing_field": piece,
        "failures": failures,
        "kind": kind,
        "modality_switch": modality_switch,
        "input_modality": input_modality or "voice",
        "candidates": (parsed or {}).get("candidates") or [],
    }


def next_recapture_state(
    previous: dict | None,
    *,
    parsed: dict | None,
    transcript: str,
    asr: float | None,
    input_modality: str | None,
    failed: bool,
) -> dict:
    prev = dict(previous or {})
    prev_food = str((prev.get("captured") or {}).get("food") or "")
    piece = missing_piece(parsed or {}, transcript, asr)
    if prev_food:
        piece = prev.get("missing_field") or piece
    same_piece = prev.get("missing_field") == piece if prev.get("pending") else True
    if not failed:
        failures = 0
    elif same_piece:
        failures = int(prev.get("failures") or 0) + 1
    else:
        failures = 1
    state = recapture_prompt(
        parsed=parsed,
        transcript=transcript,
        asr=asr,
        failures=failures,
        input_modality=input_modality,
        captured_food=prev_food,
    )
    return state


def is_type_instead_reply(text: str) -> bool:
    return bool(TYPE_INSTEAD_REPLY_RE.search(text or ""))


def recapture_payload(state: dict, transcription: str) -> dict:
    spoken = state.get("message") or state.get("prompt") or NOTHING_USABLE_PROMPT
    return {
        "logged": False,
        "transcription": transcription,
        "recapture": state,
        "message": spoken,
        "spoken_message": spoken,
    }


def reset_recapture_state() -> dict:
    return {
        "pending": False,
        "failures": 0,
        "captured": {},
        "missing_field": None,
    }
