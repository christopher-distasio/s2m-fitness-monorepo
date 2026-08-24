"""Ordered utterance routing for Spec 0 + correct_last.

Pipeline (required order):
    raw utterance
      → safety-detector          (Spec 0) — STOP if hit
      → domain-boundary          — STOP if off-topic
      → intent classification    — voice only; text path still bypasses this
      → handler (correct_last / delete / read / calories / log)

Safety runs on voice AND text. Intent classification stays voice-only
(known text-path bypass — do not extend classify_intent onto POST /food).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from backend.models import FoodLog
from backend.services.correct_last import handle_correct_last
from backend.services.domain_boundary import is_off_domain, off_domain_response
from backend.services.edit_entry import handle_edit_entry, pending_edit_entry
from backend.services.intent_classifier import classify_intent
from backend.services.safety_detector import build_safety_response, detect_safety
from backend.services.user_logs import latest_log_for_user, load_user_profile
from backend.services.response_compose import compose_response, settings_from_profile

PIPELINE_ORDER = ("safety", "domain_boundary", "intent", "handler")

DispatchKind = Literal[
    "safety",
    "off_domain",
    "correct_last",
    "edit_entry",
    "delete_last",
    "read_today",
    "calories_today",
    "log",
]


@dataclass
class DispatchResult:
    kind: DispatchKind
    stages: list[str] = field(default_factory=list)
    response: dict | None = None
    intent: str | None = None


async def run_safety_and_domain(
    text: str,
    user_id: str | None,
) -> DispatchResult:
    """Gates shared by voice and text. Intent classifier is NOT called here."""
    stages = ["safety"]
    hit = detect_safety(text)
    if hit is not None:
        response = await build_safety_response(hit, user_id, text)
        return DispatchResult(kind="safety", stages=stages, response=response)

    stages.append("domain_boundary")
    if is_off_domain(text):
        return DispatchResult(
            kind="off_domain",
            stages=stages,
            response=off_domain_response(text),
        )
    return DispatchResult(kind="log", stages=stages)


async def dispatch_voice_utterance(
    text: str,
    user_id: str,
    *,
    history: list[dict] | None = None,
    asr: float | None = None,
) -> DispatchResult:
    """Voice path: safety → domain → intent → non-log handlers.

    kind='log' means the caller should continue into parse / insert.
    Any other kind includes a ready-to-return ``response``.
    """
    gated = await run_safety_and_domain(text, user_id)
    if gated.response is not None:
        return gated

    stages = list(gated.stages)
    if pending_edit_entry(history):
        stages.append("handler")
        response = await handle_edit_entry(
            user_id, text, history=history, asr=asr
        )
        return DispatchResult(
            kind="edit_entry",
            stages=stages,
            intent="edit_entry",
            response=response,
        )

    stages.append("intent")
    classified = await classify_intent(text)
    intent_name = classified.get("intent") or "unknown"

    stages.append("handler")
    if intent_name == "delete_last":
        last = await latest_log_for_user(user_id)
        if last:
            await last.delete()
            return DispatchResult(
                kind="delete_last",
                stages=stages,
                intent=intent_name,
                response={
                    "message": "Last entry deleted",
                    "transcription": text,
                },
            )
        return DispatchResult(
            kind="delete_last",
            stages=stages,
            intent=intent_name,
            response={
                "message": "No entries to delete",
                "transcription": text,
            },
        )

    if intent_name in {"calories_today", "read_today"}:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = await FoodLog.find(
            FoodLog.user_id == user_id, FoodLog.logged_at >= start
        ).to_list()
        if intent_name == "calories_today":
            profile = await load_user_profile(user_id)
            verbosity, safety = settings_from_profile(profile)
            total = sum(log.calories or 0 for log in logs)
            goal = getattr(profile, "calorie_goal", 2000) if profile else 2000
            message = compose_response(
                "calories_today",
                {
                    "calories": total,
                    "entry_count": len(logs),
                    "calorie_goal": goal,
                },
                verbosity_level=verbosity,
                safety_mode_enabled=safety,
            )
        else:
            names = ", ".join(log.food_name for log in logs) or "nothing yet"
            message = f"Today you ate: {names}"
        return DispatchResult(
            kind=intent_name,  # type: ignore[arg-type]
            stages=stages,
            intent=intent_name,
            response={
                "message": message,
                "spoken_message": message,
                "transcription": text,
            },
        )

    if intent_name == "correct_last":
        response = await handle_correct_last(
            user_id, text, history=history, asr=asr
        )
        return DispatchResult(
            kind="correct_last",
            stages=stages,
            intent=intent_name,
            response=response,
        )

    if intent_name == "edit_entry":
        response = await handle_edit_entry(
            user_id, text, history=history, asr=asr
        )
        return DispatchResult(
            kind="edit_entry",
            stages=stages,
            intent=intent_name,
            response=response,
        )

    return DispatchResult(kind="log", stages=stages, intent=intent_name)
