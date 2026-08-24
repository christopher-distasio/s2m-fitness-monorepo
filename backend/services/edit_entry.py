"""Voice edit_entry: correct a past log by time/description, not only the last one.

Search is bounded (default 7 days) and always scoped to subject_user_id.
Zero matches speak an explicit miss — never fall back to correct_last.
Multiple matches reuse Spec 2 contrastive clarification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.models import DietaryPreferences, FoodLog
from backend.services.allergy_check import check_allergy_block
from backend.services.confirmation import (
    contrastive_question,
    resolve_confirmation_reply,
    spoken_candidates_from_history,
)
from backend.services.correct_last import (
    apply_food_event_correction,
    identity_fields_changed,
)
from backend.services.food_parser import parse_food_input
from backend.services.restriction_eval import evaluate_restrictions
from backend.services.user_logs import load_user_profile, logs_for_user_since

# Voice matching only — frontend tap-to-edit has no such window.
EDIT_ENTRY_SEARCH_WINDOW = timedelta(days=7)

# Local-hour ranges [start, end). Shared table — not learned per user.
MEAL_HOUR_RANGES: dict[str, tuple[int, int]] = {
    "breakfast": (5, 11),
    "morning": (5, 12),
    "lunch": (11, 16),
    "afternoon": (12, 17),
    "dinner": (17, 22),
    "evening": (17, 23),
    "tonight": (17, 24),
    "night": (20, 24),
}

NO_MATCH_MESSAGE = "I couldn't find a matching entry in the last 7 days."

_SPLITTERS = (
    r"\bthat was actually\b",
    r"\bthat were actually\b",
    r"\bactually\b",
    r"\bshould have been\b",
    r"\bshould've been\b",
    r"\bmake it\b",
    r"\bchange (?:it|that|them) to\b",
    r"\bi forgot\b",
    r"\binstead(?: of)?\b",
    r",\s*not\b",
)

_MEAL_ALIASES = {
    "this morning": "morning",
    "this afternoon": "afternoon",
    "this evening": "evening",
    "last night": "night",
    "breakfast": "breakfast",
    "morning": "morning",
    "lunch": "lunch",
    "afternoon": "afternoon",
    "dinner": "dinner",
    "evening": "evening",
    "tonight": "tonight",
    "night": "night",
}

_STOP = {
    "i", "i'd", "i've", "i'm", "me", "my", "the", "a", "an", "to", "for", "of",
    "on", "at", "in", "and", "or", "was", "were", "that", "this", "it", "had",
    "have", "logged", "log", "change", "edit", "update", "fix", "correct",
    "actually", "forgot", "entry", "entries", "what", "ate", "eaten", "please",
    "can", "you", "make", "not", "instead", "should", "been", "from", "into",
    "yesterday", "today", "morning", "afternoon", "evening", "night", "tonight",
    "breakfast", "lunch", "dinner", "snack", "last", "one", "ones", "just",
    "about", "with", "without", "some", "any", "thing", "things",
}

_SAFETY_ASSERTION_RE = re.compile(
    r"\b(safe|unsafe|not safe|is fine|you're fine|you are fine|should be fine)\b",
    re.I,
)


@dataclass
class EditReference:
    relative_days: int | None
    meal_label: str | None
    food_terms: list[str]
    correction_text: str | None
    reference_text: str


def pending_edit_entry(history: list[dict] | None) -> dict | None:
    """Return the open edit_entry confirmation payload, if any."""
    if not history:
        return None
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except (json.JSONDecodeError, TypeError):
            continue
        confirmation = data.get("confirmation") or {}
        if confirmation.get("pending_kind") == "edit_entry":
            return confirmation
        return None
    return None


def parse_edit_reference(utterance: str) -> EditReference:
    text = utterance or ""
    lowered = text.lower()

    correction_text = None
    reference_text = text
    for pattern in _SPLITTERS:
        match = re.search(pattern, lowered, flags=re.I)
        if match:
            reference_text = text[: match.start()].strip(" ,.")
            correction_text = text[match.end() :].strip(" ,.")
            break

    ref_l = reference_text.lower()
    relative_days: int | None = None
    if "yesterday" in ref_l or "last night" in ref_l:
        relative_days = 1
    elif any(
        phrase in ref_l
        for phrase in (
            "today",
            "this morning",
            "this afternoon",
            "this evening",
            "tonight",
        )
    ):
        relative_days = 0

    meal_label = None
    for phrase, label in sorted(_MEAL_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if phrase in ref_l:
            meal_label = label
            break

    tokens = re.findall(r"[a-z0-9]+", ref_l)
    food_terms = [
        tok
        for tok in tokens
        if tok not in _STOP and not tok.isdigit() and len(tok) >= 3
    ]
    return EditReference(
        relative_days=relative_days,
        meal_label=meal_label,
        food_terms=food_terms,
        correction_text=correction_text or None,
        reference_text=reference_text,
    )


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _local(dt: datetime, tz: ZoneInfo) -> datetime:
    return _as_aware(dt).astimezone(tz)


def _in_hour_range(local: datetime, start: int, end: int) -> bool:
    hour = local.hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _food_blob(log: FoodLog) -> str:
    event = log.food_event if isinstance(log.food_event, dict) else {}
    parts = [
        log.food_name or "",
        str(event.get("food") or ""),
        str(event.get("brand") or ""),
        str(event.get("preparation") or ""),
        str(log.raw_input or ""),
    ]
    return " ".join(parts).lower()


def match_logs(
    logs: list[FoodLog],
    reference: EditReference,
    *,
    now: datetime,
    tz: ZoneInfo,
) -> list[FoodLog]:
    today_local = now.astimezone(tz).date()
    matched: list[FoodLog] = []
    hour_range = (
        MEAL_HOUR_RANGES.get(reference.meal_label) if reference.meal_label else None
    )

    for log in logs:
        local = _local(log.logged_at, tz)
        if reference.relative_days is not None:
            target = today_local - timedelta(days=reference.relative_days)
            if local.date() != target:
                continue
        if hour_range is not None:
            if not _in_hour_range(local, hour_range[0], hour_range[1]):
                continue
        if reference.food_terms:
            blob = _food_blob(log)
            if not any(term in blob for term in reference.food_terms):
                continue
        matched.append(log)
    return matched


def _hour_label(local: datetime) -> str:
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{hour}{suffix}"


def candidate_from_log(log: FoodLog, tz: ZoneInfo) -> dict:
    local = _local(log.logged_at, tz)
    food = log.food_name or "entry"
    label = f"your {_hour_label(local)} {food}"
    event = log.food_event if isinstance(log.food_event, dict) else {}
    return {
        "name": label,
        "label": label,
        "food": food,
        "brand": event.get("brand"),
        "log_id": str(log.id),
        "kind": "log_entry",
    }


def _allergen_states(record: dict | None) -> dict[str, str]:
    if not record:
        return {}
    nested = record.get("allergen_state") or {}
    states: dict[str, str] = {}
    if isinstance(nested, dict):
        for name, value in nested.items():
            states[str(name).lower()] = str(value).lower()
    for name in record.get("allergens") or []:
        states.setdefault(str(name).lower(), "contains")
    return states


def factual_restriction_message(
    previous_event: dict | None,
    updated_record: dict,
    verdict,
) -> str | None:
    """Report what the record now shows. Never a safety assertion (D2)."""
    before = _allergen_states(previous_event)
    after = _allergen_states(updated_record)
    newly = [
        name.replace("_", " ")
        for name, state in after.items()
        if state == "contains" and before.get(name) != "contains"
    ]
    if newly:
        if len(newly) == 1:
            msg = f"This now shows {newly[0]} as an ingredient."
        else:
            msg = (
                f"This now shows {', '.join(newly[:-1])}, and {newly[-1]} "
                "as ingredients."
            )
    elif verdict is not None and verdict.verdict != "allowed" and verdict.reasons:
        msg = " ".join(verdict.reasons)
    else:
        return None
    if _SAFETY_ASSERTION_RE.search(msg):
        msg = _SAFETY_ASSERTION_RE.sub("shown", msg)
    return msg


def _ask_payload(
    question: str,
    spoken: list[dict],
    original_utterance: str,
    transcription: str,
) -> dict:
    confirmation = {
        "action": "ASK",
        "pending_kind": "edit_entry",
        "question": question,
        "question_kind": "contrastive",
        "spoken_candidates": spoken,
        "original_utterance": original_utterance,
    }
    return {
        "message": question,
        "transcription": transcription,
        "logged": False,
        "corrected": False,
        "needs_clarification": True,
        "confirmation": confirmation,
    }


async def _parse_correction(
    raw_input: str,
    user_id: str,
    history: list[dict] | None,
    asr: float | None,
) -> dict:
    return await parse_food_input(
        raw_input,
        history or [],
        user_id=user_id,
        input_modality="voice",
        activation="push_to_talk",
        asr=asr,
    )


def _parse_error_payload(parsed: dict, transcription: str) -> dict | None:
    if parsed.get("error") == "nutrition_unavailable":
        return {
            "error": "nutrition_unavailable",
            "message": parsed.get("message")
            or "Nutrition search is temporarily unavailable. Please try again.",
            "raw": parsed.get("raw"),
            "transcription": transcription,
            "logged": False,
            "corrected": False,
        }
    unresolved = parsed.get("resolution_status") == "unresolved" or (
        parsed.get("resolution") or {}
    ).get("status") == "unresolved"
    if parsed.get("error") or unresolved:
        return {
            "message": parsed.get("reasoning")
            or parsed.get("message")
            or "I didn't recognize that as a food I can look up. Nothing was changed.",
            "transcription": transcription,
            "logged": False,
            "corrected": False,
            "resolution_status": parsed.get("resolution_status") or "unresolved",
        }
    return None


async def _apply_to_log(
    log: FoodLog,
    parsed: dict,
    user_id: str,
    raw_input: str,
    prefs: DietaryPreferences | None,
) -> dict:
    previous_event = dict(log.food_event) if isinstance(log.food_event, dict) else {}
    previous_name = log.food_name
    after_event = (
        parsed.get("food_event")
        if isinstance(parsed.get("food_event"), dict)
        else parsed
    )
    identity_changed = identity_fields_changed(
        previous_event,
        after_event,
        before_name=previous_name,
        after_name=parsed.get("food"),
    )

    blocked, reason = check_allergy_block(parsed, prefs)
    if blocked:
        return {
            "transcription": raw_input,
            "error": "allergy_block",
            "message": reason or "Blocked by dietary safety filter",
            "logged": False,
            "corrected": False,
        }

    await apply_food_event_correction(log, parsed, user_id, raw_input=raw_input)

    message = f"Updated your {log.food_name or parsed.get('food') or 'entry'}."
    restriction_message = None
    restriction_verdict = None
    if identity_changed:
        updated = dict(log.food_event) if isinstance(log.food_event, dict) else dict(parsed)
        restriction_verdict = evaluate_restrictions(updated, prefs)
        restriction_message = factual_restriction_message(
            previous_event, updated, restriction_verdict
        )
        if restriction_message:
            message = f"{message} {restriction_message}"

    payload: dict = {
        "message": message,
        "transcription": raw_input,
        "id": str(log.id),
        "logged": False,
        "corrected": True,
    }
    if restriction_verdict is not None:
        payload["restriction_verdict"] = restriction_verdict.model_dump()
    if restriction_message:
        payload["restriction_update"] = restriction_message
    return payload


async def _resolve_pending(
    user_id: str,
    raw_input: str,
    pending: dict,
    history: list[dict] | None,
    asr: float | None,
) -> dict:
    spoken = pending.get("spoken_candidates") or spoken_candidates_from_history(history)
    spoken = [c for c in spoken if isinstance(c, dict)]
    resolved = resolve_confirmation_reply(raw_input, spoken) if spoken else None
    if not resolved or resolved.get("type") != "select":
        labels = [str(c.get("name") or c.get("label") or "") for c in spoken[:3]]
        question, _kind = contrastive_question(labels)
        return _ask_payload(
            question,
            spoken[:3],
            pending.get("original_utterance") or raw_input,
            raw_input,
        )

    candidate = resolved.get("candidate") or {}
    log_id = candidate.get("log_id")
    if not log_id:
        return {
            "message": NO_MATCH_MESSAGE,
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
        }

    log = await FoodLog.get(log_id)
    if log is None or log.user_id != user_id:
        return {
            "message": NO_MATCH_MESSAGE,
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
        }

    original = pending.get("original_utterance") or raw_input
    reference = parse_edit_reference(original)
    parse_text = reference.correction_text or original
    parsed = await _parse_correction(parse_text, user_id, history, asr)
    err = _parse_error_payload(parsed, raw_input)
    if err:
        return err
    profile = await load_user_profile(user_id)
    prefs = profile.dietary_preferences if profile else None
    return await _apply_to_log(log, parsed, user_id, original, prefs)


async def handle_edit_entry(
    user_id: str,
    raw_input: str,
    *,
    history: list[dict] | None = None,
    asr: float | None = None,
    now: datetime | None = None,
) -> dict:
    """Find a past entry by time/description and correct it in place."""
    profile = await load_user_profile(user_id)
    tz = _tz(getattr(profile, "timezone", None) if profile else None)
    clock = now or datetime.now(timezone.utc)

    pending = pending_edit_entry(history)
    if pending:
        return await _resolve_pending(user_id, raw_input, pending, history, asr)

    since = clock - EDIT_ENTRY_SEARCH_WINDOW
    logs = await logs_for_user_since(user_id, since)
    reference = parse_edit_reference(raw_input)
    matches = match_logs(logs, reference, now=clock, tz=tz)

    if not matches:
        return {
            "message": NO_MATCH_MESSAGE,
            "transcription": raw_input,
            "logged": False,
            "corrected": False,
        }

    if len(matches) > 1:
        spoken = [candidate_from_log(log, tz) for log in matches[:3]]
        labels = [c["name"] for c in spoken]
        question, _kind = contrastive_question(labels)
        return _ask_payload(question, spoken, raw_input, raw_input)

    parse_text = reference.correction_text or raw_input
    parsed = await _parse_correction(parse_text, user_id, history, asr)
    err = _parse_error_payload(parsed, raw_input)
    if err:
        return err
    prefs = profile.dietary_preferences if profile else None
    return await _apply_to_log(matches[0], parsed, user_id, raw_input, prefs)
