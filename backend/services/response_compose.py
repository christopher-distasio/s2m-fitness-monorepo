"""Spec 3 — verbosity (length) and Safety Mode (content), composed then spoken.

Callers build text here, then pass it through `speak()` (frontend `lib/speak.ts`
or backend `tts_service.speak`). There is no second TTS/response path.

Verbosity is a floor, not a ceiling: types that are not in VERBOSITY_TABLE
have no quick/standard/careful variants and always render at full length
(Spec 0 safety, Spec 2 ASK, allergen read-back, restriction verdicts).
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping

VerbosityLevel = Literal["quick", "standard", "careful"]
ResponseType = Literal[
    "log_confirmation",
    "daily_summary",
    "calories_today",
    "spec0_safety",
    "spec2_ask",
    "allergen_readback",
    "restriction_verdict",
]

# Routine copy only. Safety-relevant types are intentionally absent.
VERBOSITY_TABLE: dict[str, dict[VerbosityLevel, str]] = {
    "log_confirmation": {
        "quick": "Logged {food}.",
        "standard": "Logged {food}, {calories} calories.",
        "careful": (
            "Logged {food}, {calories} calories. "
            "Protein {protein} grams, carbs {carbs} grams, fat {fat} grams."
        ),
    },
    "daily_summary": {
        "quick": "Today you've had {calories} calories.",
        "standard": (
            "Today you've had {calories} calories. "
            "Protein: {protein} grams. Carbs: {carbs} grams. Fat: {fat} grams. "
            "You're at {pct}% of your daily goal."
        ),
        "careful": (
            "Here's today's summary. You've logged {entry_count} items totaling "
            "{calories} calories. Protein: {protein} grams. Carbs: {carbs} grams. "
            "Fat: {fat} grams. That's {pct}% of your {calorie_goal} calorie goal. "
            "You have {remaining} calories left today."
        ),
    },
    "calories_today": {
        "quick": "You've logged {calories} calories today.",
        "standard": "You have logged {calories} calories today.",
        "careful": (
            "You have logged {calories} calories today, "
            "{remaining} calories left toward your goal."
        ),
    },
}

# Safety Mode never touches these — D3 / Spec 0 / Spec 2 / Part C.
PROTECTED_RESPONSE_TYPES = frozenset(
    {
        "spec0_safety",
        "spec2_ask",
        "allergen_readback",
        "restriction_verdict",
    }
)

# Blind-logging templates: no calorie/energy/budget/remaining language.
SAFETY_MODE_TEMPLATES: dict[str, str] = {
    "log_confirmation": "Logged {food}.",
    "daily_summary": "Today you logged {entry_count} items.",
    "calories_today": "Your foods for today are logged.",
}

_ENERGY_LANGUAGE_RE = re.compile(
    r"""
    (
        calories?\s+left
        | remaining\s+calories?
        | calories?\s+remaining
        | energy\s+budget
        | calorie\s+budget
        | calorie\s+goal
        | daily\s+goal
        | weekly\s+goal
        | of\s+your\s+(daily\s+)?goal
        | burn(?:ing)?\s+(?:off|it)
        | work\s+off
        | offset
        | compensatory
        | calories?\s+to\s+(?:go|spare)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Broader calorie/energy metrics (item counts, remaining, totals framed as energy).
_CALORIE_METRIC_RE = re.compile(
    r"\b(calories?|kcal|energy\s+budget|calorie\s+goal)\b",
    re.IGNORECASE,
)


def settings_from_profile(profile: Any | None) -> tuple[VerbosityLevel, bool]:
    if profile is None:
        return "standard", False
    raw = getattr(profile, "verbosity_level", None) or "standard"
    verbosity: VerbosityLevel = (
        raw if raw in {"quick", "standard", "careful"} else "standard"
    )
    safety = bool(getattr(profile, "safety_mode_enabled", False))
    return verbosity, safety


def contains_energy_language(text: str) -> bool:
    """True if text has remaining/budget/compensatory-exercise framing."""
    if not text:
        return False
    return _ENERGY_LANGUAGE_RE.search(text) is not None


def contains_calorie_metric(text: str) -> bool:
    if not text:
        return False
    return bool(_CALORIE_METRIC_RE.search(text))


def _format_context(template: str, context: Mapping[str, Any]) -> str:
    calories = context.get("calories")
    goal = context.get("calorie_goal") or 0
    try:
        cal_n = float(calories) if calories is not None else 0.0
    except (TypeError, ValueError):
        cal_n = 0.0
    try:
        goal_n = float(goal) if goal else 0.0
    except (TypeError, ValueError):
        goal_n = 0.0
    remaining = max(0, round(goal_n - cal_n)) if goal_n else 0
    pct = min(100, round((cal_n / goal_n) * 100)) if goal_n else 0
    values = {
        "food": context.get("food") or "food",
        "calories": int(round(cal_n)),
        "protein": _num(context.get("protein")),
        "carbs": _num(context.get("carbs")),
        "fat": _num(context.get("fat")),
        "entry_count": int(context.get("entry_count") or 0),
        "calorie_goal": int(round(goal_n)) if goal_n else 0,
        "pct": pct,
        "remaining": remaining,
    }
    try:
        return template.format(**values)
    except KeyError:
        return template


def _num(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.1f}"


def _passthrough_message(context: Mapping[str, Any]) -> str:
    return str(context.get("message") or context.get("question") or "")


def _restriction_message(context: Mapping[str, Any]) -> str:
    reasons = context.get("reasons") or []
    parts = [f"The record shows: {reason}." for reason in reasons if reason]
    return " ".join(parts)


def compose_response(
    response_type: str,
    context: Mapping[str, Any] | None = None,
    *,
    verbosity_level: str = "standard",
    safety_mode_enabled: bool = False,
) -> str:
    """Build user-facing copy. Protected types ignore verbosity and Safety Mode."""
    ctx = dict(context or {})
    verbosity: VerbosityLevel = (
        verbosity_level
        if verbosity_level in {"quick", "standard", "careful"}
        else "standard"
    )

    if response_type in PROTECTED_RESPONSE_TYPES:
        if response_type == "restriction_verdict":
            return _restriction_message(ctx)
        return _passthrough_message(ctx)

    if safety_mode_enabled and response_type in SAFETY_MODE_TEMPLATES:
        text = _format_context(SAFETY_MODE_TEMPLATES[response_type], ctx)
    else:
        variants = VERBOSITY_TABLE.get(response_type)
        if not variants:
            return _passthrough_message(ctx)
        text = _format_context(variants[verbosity], ctx)

    if safety_mode_enabled:
        # Last-line defense: never leak remaining/budget/compensatory phrasing.
        if contains_energy_language(text) or contains_calorie_metric(text):
            fallback = SAFETY_MODE_TEMPLATES.get(response_type)
            text = _format_context(fallback, ctx) if fallback else "Logged."

    extra = ctx.get("restriction_reasons")
    if extra:
        verdict = compose_response(
            "restriction_verdict",
            {"reasons": extra},
            verbosity_level=verbosity,
            safety_mode_enabled=safety_mode_enabled,
        )
        if verdict:
            text = f"{text} {verdict}".strip()
    return text
