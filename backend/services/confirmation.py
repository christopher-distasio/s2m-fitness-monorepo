"""Spec 2 — risk-weighted confirmation.

Runs ONLY inside the log handler, after parse + lookup + bands and before
commit. Never before Spec 0, never on correct_last / delete / read / calories.

Barge-in (user speaking during TTS) is a distinct interaction already handled
by frontend/lib/bargeIn.ts — do not conflate it with same-turn self-repair.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.models.food_event import CONFIDENCE_FIELD_KEYS
from backend.services.clarification import parse_clarification_command
from backend.services.confirmation_policy import (
    CONSEQUENCE_TIER,
    PolicyAction,
    policy_action,
)

# ---------------------------------------------------------------------------
# Self-repair (same utterance) vs barge-in (leave to bargeIn.ts)
# ---------------------------------------------------------------------------
_SELF_REPAIR_RE = re.compile(
    r"\b(?P<first>[A-Za-z][A-Za-z]{1,30}(?:\s+[A-Za-z]{1,30})?)"
    r"\s*[—–\-,]+\s*no,?\s+"
    r"(?P<second>[A-Za-z][A-Za-z]{1,30}(?:\s+[A-Za-z]{1,30})?)\s*[.]?\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Negation cues immediately preceding an item
# ---------------------------------------------------------------------------
_NEGATION_RE = re.compile(
    r"\b(?:no|without|hold the|hold|not)\s+(?:any\s+|the\s+)?(?P<item>[a-z][a-z\s]{0,30}?)(?=\s*$|\s+and\b|\s+or\b|[,.])",
    re.IGNORECASE,
)

# Questions the user cannot answer from perception / what they stated.
# Answerability rule: never ask for database-only facts (calories, FDC ids, …).
_UNANSWERABLE_RE = re.compile(
    r"\b(calories?|kcal|fdc(?:_id)?|sodium|milligrams?|\d+\s*cal)\b",
    re.IGNORECASE,
)

_SIZE_TOKENS = ("small", "medium", "large", "jumbo", "mini", "fun size")
_PREP_TOKENS = (
    "dry",
    "cooked",
    "fried",
    "grilled",
    "raw",
    "baked",
    "roasted",
    "steamed",
)
_COMPOUND_PAIRS = {
    frozenset({"food", "variant"}),
    frozenset({"food", "preparation"}),
    frozenset({"amount", "unit"}),
}
_TIER_RANK = {"high": 0, "medium": 1, "low": 2}

_CONFIRM_LABELS = {
    "food": "Food match was a guess — you can correct it later.",
    "amount": "Amount was a guess — you can correct it later.",
    "unit": "Serving unit was a guess — you can correct it later.",
    "brand": "Brand was a guess — you can correct it later.",
    "variant": "Variant was a guess — you can correct it later.",
    "preparation": "Preparation was a guess — you can correct it later.",
    "negation": "A 'without' / 'no' was uncertain — you can correct it later.",
    "allergen_match": "Allergen match was uncertain — you can correct it later.",
}


@dataclass
class ConfirmationDecision:
    action: PolicyAction
    field_actions: dict[str, PolicyAction]
    asked_fields: list[str] = field(default_factory=list)
    markers: list[dict[str, str]] = field(default_factory=list)
    question: str | None = None
    spoken_candidates: list[dict] = field(default_factory=list)
    question_kind: str | None = None  # contrastive | narrowing | direct
    self_repaired: bool = False

    def to_payload(self) -> dict:
        return {
            "action": self.action,
            "field_actions": self.field_actions,
            "asked_fields": self.asked_fields,
            "markers": self.markers,
            "question": self.question,
            "spoken_candidates": self.spoken_candidates,
            "question_kind": self.question_kind,
            "self_repaired": self.self_repaired,
        }


def apply_self_repair(text: str) -> tuple[str, bool]:
    """Rewrite 'chicken — no, turkey' to the corrected value.

    Same-turn self-repair is NOT an ASK trigger. The corrected value is the
    stated value at normal confidence. Barge-in is handled elsewhere.
    """
    if not text or not text.strip():
        return text, False
    match = _SELF_REPAIR_RE.search(text.strip())
    if not match:
        return text, False
    first = match.group("first").strip()
    second = match.group("second").strip()
    if first.lower() == second.lower():
        return text, False
    prefix = text[: match.start("first")].rstrip(" ,.—–-")
    if prefix:
        return f"{prefix} {second}".strip(), True
    return second, True


def detect_negation_cues(text: str) -> list[str]:
    if not text:
        return []
    items = []
    for match in _NEGATION_RE.finditer(text):
        item = re.sub(r"\s+", " ", match.group("item")).strip().lower()
        if item and item not in {"the", "a", "an"}:
            items.append(item)
    return items


def apply_negation_guard(parsed: dict, raw_input: str) -> None:
    """Dropped-negation guard: 'no mayo' must not silently log mayo.

    Detected-but-uncertain negation → band low on the negation field (ASK).
    """
    items = detect_negation_cues(raw_input)
    if not items:
        return
    food = (parsed.get("food") or "").lower()
    haystack = " ".join(
        [
            food,
            str(parsed.get("notes") or ""),
            " ".join(str(a) for a in (parsed.get("allergens") or [])),
        ]
    ).lower()
    skip = {"sure", "really", "very", "too", "just", "that", "this"}
    uncertain = False
    for item in items:
        token = item.split()[0]
        if len(token) < 3 or token in skip:
            continue
        if token in haystack:
            uncertain = True
            break
    if not uncertain:
        return
    detail = parsed.setdefault("confidence_detail", {})
    current = dict(detail.get("negation") or {})
    current["band"] = "low"
    detail["negation"] = current
    parsed["negation_uncertain"] = True
    parsed["negation_cues"] = items


def _band_for(parsed: dict, field: str) -> str | None:
    detail = parsed.get("confidence_detail") or {}
    band = (detail.get(field) or {}).get("band")
    if band in {"high", "medium", "low"}:
        return band
    return None


def _candidate_name(candidate: dict) -> str:
    brand = (candidate.get("brand") or "").strip()
    name = (candidate.get("name") or candidate.get("label") or candidate.get("food") or "").strip()
    if brand and name and brand.lower() not in name.lower():
        return f"{brand} {name}"
    return name or brand


def _size_token(candidate: dict) -> str:
    blob = f"{candidate.get('serving_label') or ''} {candidate.get('name') or ''} {candidate.get('label') or ''}".lower()
    for token in _SIZE_TOKENS:
        if token in blob:
            return token
    return "unspecified"


def _prep_token(candidate: dict) -> str:
    blob = f"{candidate.get('name') or ''} {candidate.get('preparation') or ''} {candidate.get('label') or ''}".lower()
    for token in _PREP_TOKENS:
        if token in blob:
            return token
    return "unspecified"


def _brand_token(candidate: dict) -> str:
    return (candidate.get("brand") or "generic").strip().lower() or "generic"


def _calorie_spread(groups: dict[str, list[float]]) -> float:
    means = [sum(vals) / len(vals) for vals in groups.values() if vals]
    if len(means) < 2:
        return 0.0
    return max(means) - min(means)


def _group_by(candidates: list[dict], getter) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for candidate in candidates:
        groups.setdefault(getter(candidate), []).append(candidate)
    return groups


def _discriminating_attribute(candidates: list[dict]) -> tuple[str, list[str]]:
    """Attribute with the largest nutritional (calorie) spread.

    Cheapest-to-ask (fewer unique values) is a tiebreaker only.
    """
    getters = {
        "brand": _brand_token,
        "size": _size_token,
        "preparation": _prep_token,
    }
    scored: list[tuple[float, int, str, list[str]]] = []
    for name, getter in getters.items():
        groups = _group_by(candidates, getter)
        keys = [k for k in groups if k != "unspecified"]
        if len(keys) < 2:
            continue
        cal_groups = {
            k: [float(c.get("calories") or 0) for c in groups[k]] for k in keys
        }
        spread = _calorie_spread(cal_groups)
        scored.append((spread, -len(keys), name, keys[:3]))
    if not scored:
        labels = [_candidate_name(c) for c in candidates[:3] if _candidate_name(c)]
        return "name", labels
    scored.sort(reverse=True)
    _spread, _cheap, attr, keys = scored[0]
    return attr, keys


def is_answerable_question(question: str) -> bool:
    """True when the user can answer from perception or what they already said.

    Database-only facts (calories, FDC ids, nutrient milligrams) are the
    wrong question — callers should fall back to CONFIRM rather than ASK.
    """
    if not question or not question.strip():
        return False
    return _UNANSWERABLE_RE.search(question) is None


def _join_or(parts: list[str]) -> str:
    clean = [p for p in parts if p]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} or {clean[1]}"
    return f"{', '.join(clean[:-1])}, or {clean[-1]}"


def _contrastive_question(labels: list[str], field: str) -> tuple[str, str]:
    joined = _join_or(labels)
    if field in {"amount", "unit"}:
        return f"Was that {joined}?", "contrastive"
    if field == "preparation":
        return f"Was that {joined}?", "contrastive"
    return f"Was that {joined}?", "contrastive"


def contrastive_question(labels: list[str], field: str = "food") -> tuple[str, str]:
    """Public Spec 2 contrastive prompt — reused by edit_entry candidate lists."""
    return _contrastive_question(labels, field)


def _question_for_fields(
    fields: list[str],
    parsed: dict,
) -> tuple[str | None, list[dict], str | None]:
    candidates = [c for c in (parsed.get("candidates") or []) if isinstance(c, dict)]
    portions = [p for p in (parsed.get("portion_options") or []) if isinstance(p, dict)]
    spoken: list[dict] = []
    kind: str | None = None
    parts: list[str] = []

    for field in fields:
        if field == "negation":
            cues = parsed.get("negation_cues") or detect_negation_cues(
                parsed.get("raw_transcript") or parsed.get("raw") or ""
            )
            item = cues[0] if cues else "that"
            parts.append(f"Did you want that without {item}?")
            kind = kind or "direct"
            continue
        if field == "allergen_match":
            states = parsed.get("allergen_state") or {}
            names = [k for k, v in states.items() if v == "contains"] or list(states)[:1]
            allergen = names[0].replace("_", " ") if names else "an allergen"
            parts.append(f"Did that include {allergen}?")
            kind = kind or "direct"
            continue
        if field in {"amount", "unit"} and portions:
            labels = [str(p.get("label") or "").strip() for p in portions if p.get("label")]
            labels = [lab for lab in labels if lab][:3]
            spoken = [
                {"name": p.get("label"), "label": p.get("label"), "calories": p.get("calories"), "kind": "portion"}
                for p in portions
                if p.get("label")
            ][:3]
            q, kind = _contrastive_question(labels, field)
            parts.append(q)
            continue
        if field in {"food", "variant", "preparation"}:
            usable = [c for c in candidates if _candidate_name(c)]
            if 2 <= len(usable) <= 3:
                labels = [_candidate_name(c) for c in usable[:3]]
                spoken = usable[:3]
                q, kind = _contrastive_question(labels, field)
                parts.append(q)
            elif len(usable) > 3:
                attr, keys = _discriminating_attribute(usable)
                labels = [k.replace("_", " ") for k in keys]
                spoken = usable[:3]
                q = f"Was that {_join_or(labels)}?"
                kind = "narrowing"
                parts.append(q)
                # Keep the 2-3 options that were actually asked, not the full set.
                spoken = [
                    c
                    for c in usable
                    if (
                        (_brand_token(c) in keys)
                        if attr == "brand"
                        else (_size_token(c) in keys)
                        if attr == "size"
                        else (_prep_token(c) in keys)
                    )
                ][:3] or usable[:3]
            else:
                food = parsed.get("food") or "that"
                parts.append(f"Did you mean {food}?")
                kind = kind or "direct"
                if parsed.get("food"):
                    spoken = [{"name": parsed.get("food"), "brand": parsed.get("brand")}]
            continue
        parts.append(f"Can you confirm the {field.replace('_', ' ')}?")
        kind = kind or "direct"

    question = " ".join(p.rstrip("?") + "?" if i == 0 else p for i, p in enumerate(parts)) if parts else None
    if len(parts) == 2:
        a, b = parts[0].rstrip("?"), parts[1].rstrip("?")
        question = f"{a}, and {b[0].lower() + b[1:]}?"
    elif len(parts) == 1:
        question = parts[0]
    return question, spoken, kind


def _cap_ask_fields(ask_fields: list[str]) -> tuple[list[str], list[str]]:
    """At most one question turn. Remainder degrade to CONFIRM."""
    ordered = sorted(ask_fields, key=lambda f: _TIER_RANK[CONSEQUENCE_TIER[f]])
    if not ordered:
        return [], []
    high = [f for f in ordered if CONSEQUENCE_TIER[f] == "high"]
    if high:
        asked = high[:1]
        extra = ordered[1:] if asked[0] in ordered else ordered
        extra = [f for f in extra if f not in asked]
        return asked, extra
    if len(ordered) >= 2 and frozenset(ordered[:2]) in _COMPOUND_PAIRS:
        return ordered[:2], ordered[2:]
    return ordered[:1], ordered[1:]


def evaluate_confirmation(
    parsed: dict,
    raw_input: str,
    *,
    self_repaired: bool = False,
) -> ConfirmationDecision:
    if not self_repaired:
        apply_negation_guard(parsed, raw_input)

    field_actions: dict[str, PolicyAction] = {}
    for key in CONFIDENCE_FIELD_KEYS:
        band = _band_for(parsed, key)
        if band is None:
            continue
        field_actions[key] = policy_action(band, key)

    ask_fields = [f for f, action in field_actions.items() if action == "ASK"]
    asked, degraded = _cap_ask_fields(ask_fields)
    for field in degraded:
        field_actions[field] = "CONFIRM"

    markers = [
        {
            "field": f,
            "band": _band_for(parsed, f) or "low",
            "action": "CONFIRM",
            "label": _CONFIRM_LABELS.get(f, f"{f} was a guess — you can correct it later."),
        }
        for f, action in field_actions.items()
        if action == "CONFIRM"
    ]

    question = None
    spoken: list[dict] = []
    kind = None
    overall: PolicyAction = "SILENT"
    if asked:
        question, spoken, kind = _question_for_fields(asked, {**parsed, "raw_transcript": raw_input})
        if question and not is_answerable_question(question):
            for field in asked:
                field_actions[field] = "CONFIRM"
                markers.append(
                    {
                        "field": field,
                        "band": _band_for(parsed, field) or "low",
                        "action": "CONFIRM",
                        "label": _CONFIRM_LABELS.get(field, f"{field} was a guess — you can correct it later."),
                    }
                )
            asked = []
            question = None
            spoken = []
            kind = None
        else:
            overall = "ASK"
    if overall != "ASK":
        overall = "CONFIRM" if markers else "SILENT"

    return ConfirmationDecision(
        action=overall,
        field_actions=field_actions,
        asked_fields=asked,
        markers=markers,
        question=question,
        spoken_candidates=spoken,
        question_kind=kind,
        self_repaired=self_repaired,
    )


def attach_confirmation(
    parsed: dict,
    raw_input: str,
    *,
    self_repaired: bool = False,
) -> ConfirmationDecision:
    decision = evaluate_confirmation(parsed, raw_input, self_repaired=self_repaired)
    parsed["confirmation"] = decision.to_payload()
    return decision


def spoken_candidates_from_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except (json.JSONDecodeError, TypeError):
            continue
        confirmation = data.get("confirmation") or {}
        candidates = confirmation.get("spoken_candidates")
        if isinstance(candidates, list) and candidates:
            return [c for c in candidates if isinstance(c, dict)]
    return []


def _blob(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(k) or "")
        for k in ("name", "brand", "label", "serving_label", "food")
    ).lower()


def match_attribute_selection(text: str, candidates: list[dict]) -> dict | None:
    """Resolve 'the small one' / 'the grilled one' against this turn's list."""
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    t = re.sub(r"\s+one$", "", t).strip()
    if not t or not candidates:
        return None
    hits: list[tuple[int, dict]] = []
    for i, candidate in enumerate(candidates):
        blob = _blob(candidate)
        if t and t in blob:
            hits.append((i, candidate))
            continue
        tokens = t.split()
        if tokens and all(tok in blob for tok in tokens):
            hits.append((i, candidate))
    if len(hits) == 1:
        return {"type": "select", "index": hits[0][0] + 1, "candidate": hits[0][1]}
    return None


def resolve_confirmation_reply(text: str, spoken_candidates: list[dict]) -> dict | None:
    """Resolve a reply against the candidate list spoken this turn only."""
    command = parse_clarification_command(text)
    if command and command.get("type") == "select":
        index = int(command["index"])
        if 1 <= index <= len(spoken_candidates):
            return {
                "type": "select",
                "index": index,
                "candidate": spoken_candidates[index - 1],
            }
        return command
    if command and command.get("type") in {"repeat", "more", "confirm"}:
        return command
    return match_attribute_selection(text, spoken_candidates)
