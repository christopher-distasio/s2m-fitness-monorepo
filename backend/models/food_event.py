"""Spec 1 canonical intake shapes: FoodEvent inside UtteranceResult.

FoodEvent is what parse → lookup → route → log carries. It is NOT the
top-level object — UtteranceResult wraps one utterance that may contain
several events ("eggs, toast, and coffee").
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Band = Literal["high", "medium", "low"]
ItemType = Literal["food", "beverage", "supplement"]
EntryMode = Literal["resolved", "direct_macro"]
Visibility = Literal["private", "shared_anonymous", "shared_attributed"]
QuantityKind = Literal["count", "measure"]
ResolutionStatus = Literal["resolved", "needs_clarification", "unresolved"]
ProvenanceValue = Literal[
    "user_stated",
    "user_approximate",
    "user_confirmed",
    "inferred",
    "record_default",
]
ThreeState = Literal["contains", "free", "unknown"]
EvidenceBasis = Literal[
    "declared_ingredient",
    "advisory_label_present",
    "certified",
    "not_assessed",
]
Intent = Literal[
    "LOG",
    "REPAIR",
    "QUERY",
    "CONTROL",
    "CONFIRM",
    "SETTING",
    "SAFETY",
]
InputModality = Literal["voice", "text", "photo", "barcode"]
Activation = Literal["push_to_talk", "wake_word", "ambient"]
RestrictionVerdictValue = Literal["allowed", "warn", "block"]

# Per-field confidence keys populated on every parse (Spec 1).
CONFIDENCE_FIELD_KEYS: tuple[str, ...] = (
    "food",
    "brand",
    "variant",
    "preparation",
    "amount",
    "unit",
    "negation",
    "allergen_match",
)


class VariantTag(BaseModel):
    type: str  # fat_content | grain_type | style | flavor | diet_formulation | size_class | ...
    value: str


class FieldConfidence(BaseModel):
    """ALL decision logic reads `band` only. Raw floats are telemetry."""

    band: Band = "low"
    asr: float | None = None
    semantic: float | None = None
    database: float | None = None
    database_gap: float | None = None


class NutrientValue(BaseModel):
    """Never store a bare number — units must travel with the value."""

    value: float | None = None
    unit: str
    usda_nutrient_id: int | None = None


class ResolutionAudit(BaseModel):
    raw_transcript: str | None = None
    parsed_interpretation: dict[str, Any] = Field(default_factory=dict)
    candidate_set_considered: list[dict[str, Any]] = Field(default_factory=list)
    record_selected: dict[str, Any] | None = None
    assumptions_applied: list[str] = Field(default_factory=list)
    user_confirmations: list[dict[str, Any]] = Field(default_factory=list)


class RestrictionHit(BaseModel):
    tag: str
    state: str
    evidence_basis: str = "not_assessed"
    severity: str | None = None
    kind: str = "allergen"


class RestrictionVerdict(BaseModel):
    verdict: RestrictionVerdictValue = "allowed"
    hits: list[RestrictionHit] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return self.verdict == "block"


class FoodEvent(BaseModel):
    item_type: ItemType = "food"
    entry_mode: EntryMode = "resolved"
    visibility: Visibility = "private"

    food: str | None = None
    brand: str | None = None
    upc: str | None = None
    variant_tags: list[VariantTag] = Field(default_factory=list)
    recipe_ref_id: str | None = None
    preparation: str | None = None

    quantity_kind: QuantityKind = "count"
    amount: float = 1.0
    unit: str = "count"
    unit_definition: dict[str, Any] | None = None
    hydration_state: Literal["dry", "cooked"] | None = None
    packing_medium_consumed: bool | None = None
    consumption_fraction: float = 1.0
    meal_slot: Literal["breakfast", "lunch", "dinner", "snack"] | None = None

    allergen_state: dict[str, ThreeState] = Field(default_factory=dict)
    restriction_tags: dict[str, str] = Field(default_factory=dict)
    certification_status: dict[str, str] = Field(default_factory=dict)

    confidence: dict[str, FieldConfidence] = Field(default_factory=dict)
    provenance: dict[str, ProvenanceValue] = Field(default_factory=dict)
    evidence_basis: dict[str, EvidenceBasis] = Field(default_factory=dict)

    resolution_status: ResolutionStatus = "resolved"

    calories: float | None = None
    macronutrients: dict[str, float | None] = Field(default_factory=dict)
    nutrients: dict[str, NutrientValue] = Field(default_factory=dict)
    serving_label: str | None = None
    serving_note: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    portion_options: list[dict[str, Any]] = Field(default_factory=list)
    used_dietary_fallback: bool = False
    quantity_used: float | None = None
    fdc_id: str | int | None = None
    source: str | None = None

    # Denormalized display values as logged (Spec 1 CHANGE 2).
    logged_food_name: str | None = None
    logged_brand: str | None = None
    logged_serving_label: str | None = None

    # Additive legacy fields the current UI still reads.
    serving_size: str | None = None
    notes: str | None = None
    reasoning: str | None = None
    alternatives: list[str] | None = None
    resolution: dict[str, Any] | None = None
    data_source: str | None = None
    modifiers: dict[str, Any] | None = None
    blocked_by_allergy: bool = False

    resolution_audit: ResolutionAudit = Field(default_factory=ResolutionAudit)

    def overall_band(self) -> Band:
        """Minimum band across populated fields. Decision logic reads bands only."""
        rank = {"high": 3, "medium": 2, "low": 1}
        bands = [fc.band for fc in self.confidence.values()]
        if not bands:
            return "low"
        return min(bands, key=lambda b: rank[b])

    def to_legacy_parsed(self) -> dict[str, Any]:
        """Additive frontend contract: existing keys keep names and shapes."""
        extras: dict[str, float] = {}
        for key, nv in self.nutrients.items():
            if nv.value is not None:
                extras[key] = nv.value

        allergens = [
            name for name, state in self.allergen_state.items() if state == "contains"
        ]
        out: dict[str, Any] = {
            "food": self.food,
            "brand": self.brand,
            "serving_size": self.serving_size or _serving_size_from_quantity(self),
            "calories": self.calories,
            "macronutrients": self.macronutrients
            or {
                "carbohydrates": None,
                "protein": None,
                "fats": None,
            },
            "nutrients": extras,
            "nutrients_typed": {
                k: v.model_dump() for k, v in self.nutrients.items()
            },
            "confidence": self.overall_band(),
            "confidence_detail": {
                k: v.model_dump() for k, v in self.confidence.items()
            },
            "notes": self.notes,
            "reasoning": self.reasoning,
            "alternatives": self.alternatives,
            "candidates": self.candidates,
            "portion_options": self.portion_options,
            "serving_label": self.serving_label,
            "serving_note": self.serving_note,
            "used_dietary_fallback": self.used_dietary_fallback,
            "quantity_used": self.quantity_used if self.quantity_used is not None else self.amount,
            "data_source": self.data_source,
            "modifiers": self.modifiers,
            "allergens": allergens,
            "allergen_state": self.allergen_state,
            "restriction_tags": self.restriction_tags,
            "certification_status": self.certification_status,
            "evidence_basis": self.evidence_basis,
            "provenance": self.provenance,
            "resolution_status": self.resolution_status,
            "entry_mode": self.entry_mode,
            "item_type": self.item_type,
            "visibility": self.visibility,
            "quantity_kind": self.quantity_kind,
            "amount": self.amount,
            "unit": self.unit,
            "unit_definition": self.unit_definition,
            "consumption_fraction": self.consumption_fraction,
            "fdc_id": self.fdc_id,
            "source": self.source,
            "logged_food_name": self.logged_food_name or self.food,
            "logged_brand": self.logged_brand or self.brand,
            "logged_serving_label": self.logged_serving_label or self.serving_label,
            "resolution": self.resolution
            or {"status": self.resolution_status},
        }
        if self.blocked_by_allergy:
            out["blocked_by_allergy"] = True
            out["confidence"] = "blocked"
        # Legacy per-allergen CONTAINS/FREE/UNKNOWN keys.
        for name, state in self.allergen_state.items():
            out[name] = state.upper()
        return out


class UtteranceResult(BaseModel):
    intent: Intent = "LOG"
    food_events: list[FoodEvent] = Field(default_factory=list)
    subject_user_id: str
    input_modality: InputModality = "text"
    activation: Activation | None = None
    raw_transcript: str | None = None

    def to_parse_response(self) -> dict[str, Any]:
        if not self.food_events:
            return {
                "error": "unparseable",
                "raw": self.raw_transcript,
                "intent": self.intent,
                "subject_user_id": self.subject_user_id,
                "input_modality": self.input_modality,
                "activation": self.activation,
                "food_events": [],
            }
        primary = self.food_events[0]
        out = primary.to_legacy_parsed()
        out["food_events"] = [event.model_dump(mode="python") for event in self.food_events]
        out["intent"] = self.intent
        out["subject_user_id"] = self.subject_user_id
        out["input_modality"] = self.input_modality
        out["activation"] = self.activation
        out["raw_transcript"] = self.raw_transcript
        if any(e.resolution_status == "unresolved" for e in self.food_events) and all(
            e.resolution_status == "unresolved" for e in self.food_events
        ):
            out["logged"] = False
        return out


def _serving_size_from_quantity(event: FoodEvent) -> str:
    amount = event.amount
    amount_str = str(int(amount)) if float(amount).is_integer() else str(amount)
    if event.quantity_kind == "count" and event.unit in ("count", "each", ""):
        return amount_str
    return f"{amount_str} {event.unit}".strip()


def empty_confidence_map(
    *,
    band: Band = "low",
    asr: float | None = None,
    semantic: float | None = None,
    database: float | None = None,
    database_gap: float | None = None,
) -> dict[str, FieldConfidence]:
    template = FieldConfidence(
        band=band,
        asr=asr,
        semantic=semantic,
        database=database,
        database_gap=database_gap,
    )
    return {key: template.model_copy() for key in CONFIDENCE_FIELD_KEYS}
