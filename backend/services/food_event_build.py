"""Assemble FoodEvent from a parse dict + confidence signals (Spec 1)."""

from __future__ import annotations

import re
from typing import Any, Literal

from backend.models.food_event import (
    CONFIDENCE_FIELD_KEYS,
    FoodEvent,
    NutrientValue,
    ResolutionAudit,
    UtteranceResult,
    VariantTag,
    empty_confidence_map,
)
from backend.services.confidence import field_confidence
from backend.services.dietary_filters import FDA_ALLERGENS, NON_ALLERGEN_TIER_1
from backend.services.nutrient_fields import wrap_nutrient_map

_HEDGE_RE = re.compile(
    r"\b(i think|i thought|maybe|not sure|probably|might have been|kind of|sort of)\b",
    re.IGNORECASE,
)
_MEASURE_UNITS = {
    "cup",
    "cups",
    "tbsp",
    "tablespoon",
    "tablespoons",
    "tsp",
    "teaspoon",
    "teaspoons",
    "oz",
    "ounce",
    "ounces",
    "g",
    "gram",
    "grams",
    "ml",
    "l",
    "liter",
    "liters",
    "lb",
    "pound",
    "pounds",
    "slice",
    "slices",
    "serving",
    "servings",
}

# Hard rule 4 — documented constant. Lookup/extraction must map advisory
# language to unknown, never contains, never free.
ADVISORY_LANGUAGE_STATE = "unknown"


def is_hedged_input(raw_input: str | None) -> bool:
    if not raw_input:
        return False
    return bool(_HEDGE_RE.search(raw_input))


def _three_state(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"contains", "free", "unknown"}:
        return text
    return None


def _allergen_state_from_parsed(parsed: dict) -> dict[str, str]:
    states: dict[str, str] = {}
    nested = parsed.get("allergen_state") or {}
    if isinstance(nested, dict):
        for key, val in nested.items():
            normalized = _three_state(val)
            if normalized:
                states[str(key)] = normalized
    for name in FDA_ALLERGENS:
        if name in states:
            continue
        normalized = _three_state(parsed.get(name))
        if normalized:
            states[name] = normalized
        elif name in (parsed.get("allergens") or []):
            states[name] = "contains"
    return states


def _evidence_from_state(states: dict[str, str]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for key, state in states.items():
        if state == "contains":
            evidence[key] = "declared_ingredient"
        elif state == "unknown":
            evidence[key] = "not_assessed"
        else:
            evidence[key] = "not_assessed"
    return evidence


def _quantity_kind_and_unit(parsed: dict, amount: float) -> tuple[str, str]:
    if parsed.get("quantity_kind") in ("count", "measure"):
        unit = parsed.get("unit") or ("count" if parsed["quantity_kind"] == "count" else "serving")
        return parsed["quantity_kind"], unit
    serving = str(parsed.get("serving_size") or "").strip().lower()
    tokens = serving.split()
    for token in tokens:
        cleaned = token.strip(".,")
        if cleaned in _MEASURE_UNITS:
            return "measure", cleaned
    return "count", "count"


def _typed_nutrients(parsed: dict) -> dict[str, NutrientValue]:
    raw = parsed.get("nutrients_typed") or parsed.get("nutrients") or {}
    wrapped = wrap_nutrient_map(raw)
    out: dict[str, NutrientValue] = {}
    for key, payload in wrapped.items():
        out[key] = NutrientValue.model_validate(payload)
    return out


def _restriction_tags(parsed: dict) -> dict[str, str]:
    tags = dict(parsed.get("restriction_tags") or {})
    for name in NON_ALLERGEN_TIER_1:
        val = parsed.get(name)
        normalized = _three_state(val)
        if normalized:
            tags[name] = normalized
    return tags


def _resolution_status(parsed: dict) -> str:
    if parsed.get("resolution_status") in {"resolved", "needs_clarification", "unresolved"}:
        return parsed["resolution_status"]
    status = (parsed.get("resolution") or {}).get("status")
    if status == "needs_brand_choice":
        return "needs_clarification"
    if status in {"resolved", "needs_clarification", "unresolved"}:
        return status
    if parsed.get("blocked_by_allergy") or parsed.get("confidence") == "blocked":
        return "needs_clarification"
    if parsed.get("calories") is None and parsed.get("data_source") in {None, "gpt_fallback"}:
        if parsed.get("confidence") == "low" and not parsed.get("candidates"):
            return "unresolved"
    return "resolved"


def food_event_from_parsed(
    parsed: dict,
    *,
    raw_input: str | None = None,
    asr: float | None = None,
    semantic: float | None = None,
    extraction_failed: bool = False,
) -> FoodEvent:
    amount = parsed.get("amount")
    if amount is None:
        amount = parsed.get("quantity_used", 1.0)
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        amount_f = 1.0

    quantity_kind, unit = _quantity_kind_and_unit(parsed, amount_f)
    allergen_state = _allergen_state_from_parsed(parsed)
    hedged = parsed.get("hedged") or is_hedged_input(raw_input)
    field_prov: Literal["user_approximate", "user_stated", "inferred", "record_default"]
    field_prov = "user_approximate" if hedged else "user_stated"

    sanity = parsed.get("confidence") if parsed.get("confidence") in {"high", "medium", "low"} else None
    database = parsed.get("database_score")
    database_gap = parsed.get("database_score_gap")
    try:
        conf = empty_confidence_map()
        for key in CONFIDENCE_FIELD_KEYS:
            db = database if key in {"food", "brand", "variant", "allergen_match"} else None
            gap = database_gap if db is not None else None
            conf[key] = field_confidence(
                asr=asr,
                semantic=semantic,
                database=db,
                database_gap=gap,
                extraction_failed=extraction_failed,
                fallback=sanity,
            )
    except Exception:
        conf = empty_confidence_map(band="low", asr=asr, semantic=semantic)

    provenance = {
        "food": field_prov if parsed.get("food") else "inferred",
        "brand": field_prov if parsed.get("brand") else "inferred",
        "variant": "inferred",
        "preparation": field_prov if parsed.get("preparation") else "inferred",
        "amount": field_prov,
        "unit": field_prov,
        "negation": "inferred",
        "allergen_match": "record_default",
    }
    # consumption_fraction is user-stated only — never infer != 1.0
    consumption = parsed.get("consumption_fraction", 1.0)
    try:
        consumption_f = float(consumption)
    except (TypeError, ValueError):
        consumption_f = 1.0
    if consumption_f != 1.0 and parsed.get("consumption_fraction_stated") is not True:
        consumption_f = 1.0

    variants = []
    for tag in parsed.get("variant_tags") or []:
        if isinstance(tag, VariantTag):
            variants.append(tag)
        elif isinstance(tag, dict) and tag.get("type") and tag.get("value"):
            variants.append(VariantTag(type=tag["type"], value=tag["value"]))

    entry_mode = parsed.get("entry_mode") or "resolved"
    food = parsed.get("food")
    if entry_mode == "direct_macro":
        food = food or None
        resolution_status = "resolved"
    else:
        resolution_status = _resolution_status(parsed)

    macros = parsed.get("macronutrients") or {}
    audit = ResolutionAudit(
        raw_transcript=raw_input,
        parsed_interpretation={
            "food": food,
            "brand": parsed.get("brand"),
            "serving_size": parsed.get("serving_size"),
            "amount": amount_f,
            "unit": unit,
        },
        candidate_set_considered=list(parsed.get("candidates") or []),
        record_selected=(
            {
                "fdc_id": parsed.get("fdc_id"),
                "source": parsed.get("source") or parsed.get("data_source"),
                "name": parsed.get("food"),
                "brand": parsed.get("brand"),
            }
            if parsed.get("fdc_id") or parsed.get("food")
            else None
        ),
        assumptions_applied=[
            note
            for note in [parsed.get("notes"), parsed.get("serving_note")]
            if note
        ],
        user_confirmations=[],
    )

    cert = dict(parsed.get("certification_status") or {})
    # Never infer certification from ingredients — default unknown if a key exists with no source.
    for key, val in list(cert.items()):
        if val not in {"certified", "not_certified", "unknown"}:
            cert[key] = "unknown"

    return FoodEvent(
        item_type=parsed.get("item_type") or "food",
        entry_mode=entry_mode,
        visibility=parsed.get("visibility") or "private",
        food=food,
        brand=parsed.get("brand") or None,
        upc=parsed.get("upc"),
        variant_tags=variants,
        preparation=parsed.get("preparation"),
        quantity_kind=quantity_kind,  # type: ignore[arg-type]
        amount=amount_f,
        unit=unit,
        unit_definition=parsed.get("unit_definition"),
        hydration_state=parsed.get("hydration_state"),
        packing_medium_consumed=parsed.get("packing_medium_consumed"),
        consumption_fraction=consumption_f,
        meal_slot=parsed.get("meal_slot"),
        allergen_state=allergen_state,  # type: ignore[arg-type]
        restriction_tags=_restriction_tags(parsed),
        certification_status=cert,
        confidence=conf,
        provenance=provenance,  # type: ignore[arg-type]
        evidence_basis=_evidence_from_state(allergen_state),  # type: ignore[arg-type]
        resolution_status=resolution_status,  # type: ignore[arg-type]
        calories=parsed.get("calories"),
        macronutrients=macros,
        nutrients=_typed_nutrients(parsed),
        serving_label=parsed.get("serving_label"),
        serving_note=parsed.get("serving_note"),
        candidates=list(parsed.get("candidates") or []),
        portion_options=list(parsed.get("portion_options") or []),
        used_dietary_fallback=bool(parsed.get("used_dietary_fallback")),
        quantity_used=parsed.get("quantity_used", amount_f),
        fdc_id=parsed.get("fdc_id"),
        source=parsed.get("source") or parsed.get("data_source"),
        logged_food_name=parsed.get("food"),
        logged_brand=parsed.get("brand") or None,
        logged_serving_label=parsed.get("serving_label"),
        serving_size=parsed.get("serving_size"),
        notes=parsed.get("notes"),
        reasoning=parsed.get("reasoning"),
        alternatives=parsed.get("alternatives"),
        resolution=parsed.get("resolution"),
        data_source=parsed.get("data_source"),
        modifiers=parsed.get("modifiers"),
        blocked_by_allergy=bool(parsed.get("blocked_by_allergy")),
        resolution_audit=audit,
    )


def utterance_from_parsed_events(
    events: list[FoodEvent],
    *,
    subject_user_id: str,
    raw_input: str | None,
    input_modality: str = "text",
    activation: str | None = None,
) -> UtteranceResult:
    modality = input_modality if input_modality in {"voice", "text", "photo", "barcode"} else "text"
    act = activation if modality == "voice" else None
    if modality == "voice" and act is None:
        act = "push_to_talk"
    return UtteranceResult(
        intent="LOG",
        food_events=events,
        subject_user_id=subject_user_id,
        input_modality=modality,  # type: ignore[arg-type]
        activation=act,  # type: ignore[arg-type]
        raw_transcript=raw_input,
    )
