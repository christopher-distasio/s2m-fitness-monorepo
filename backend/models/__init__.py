from beanie import Document
from pydantic import Field, BaseModel
from typing import Optional, List, Literal, Dict
from datetime import datetime, timezone

from backend.models.food_event import (  # noqa: F401
    CONFIDENCE_FIELD_KEYS,
    FieldConfidence,
    FoodEvent,
    NutrientValue,
    ResolutionAudit,
    RestrictionHit,
    RestrictionVerdict,
    UtteranceResult,
    VariantTag,
    empty_confidence_map,
)

# ============================================================================
# DIETARY PREFERENCES (Tier 1/2/Optional)
# ============================================================================

class AllergyConstraint(BaseModel):
    """
    One allergen's setting for a user. Backed by the three-state Qdrant
    payload model (CONTAINS/FREE/UNKNOWN) validated 2026-08-04.

    severity determines fallback/filter behavior:
      severe   -> only FREE passes; UNKNOWN and any may_contain flag are
                  excluded. Zero results means zero results -- never relaxed.
      moderate -> only CONTAINS is excluded; UNKNOWN passes through with a
                  spoken caveat at the application layer.
    """
    enabled: bool = False
    severity: Literal["severe", "moderate"] = "moderate"


class Tier1Preferences(BaseModel):
    """Hard constraints -- user can't eat these types of foods."""

    # 9 FDA major allergens (FALCPA/FASTER Act). Extraction validated against
    # 500 real branded_food.csv records with 0 genuine false positives.
    allergens: Dict[str, AllergyConstraint] = Field(default_factory=lambda: {
        "milk": AllergyConstraint(),
        "egg": AllergyConstraint(),
        "fish": AllergyConstraint(),
        "shellfish": AllergyConstraint(),  # crustacean + mollusk combined
        "tree_nut": AllergyConstraint(),
        "peanut": AllergyConstraint(),
        "wheat": AllergyConstraint(),
        "soy": AllergyConstraint(),
        "sesame": AllergyConstraint(),
    })

    # Non-allergen hard constraints -- simple bool, matched against
    # modifier-name-as-value in Qdrant payload (e.g. {"vegan": "vegan"})
    gluten_free: bool = False
    lactose_free: bool = False
    vegan: bool = False
    vegetarian: bool = False
    kosher: bool = False
    halal: bool = False

    # PLACEHOLDER: no extraction logic built/validated for this yet.
    # Field exists so the UI/schema shape is stable; setting it currently
    # has no effect on search results until sulfite extraction is scoped.
    sulfite_free: bool = False


class Tier2Preferences(BaseModel):
    """Soft preferences -- rank these higher, but not required."""
    keto: bool = False
    low_carb: bool = False
    paleo: bool = False
    organic: bool = False
    non_gmo: bool = False
    grass_fed: bool = False
    pasture_raised: bool = False
    cage_free: bool = False


class OptionalPreferences(BaseModel):
    """Optional toggles for niche medical conditions (UI: collapsed "More options" section)."""
    low_fodmap: bool = False
    nightshade_free: bool = False
    histamine_friendly: bool = False


class DietaryPreferences(BaseModel):
    """Complete dietary preferences object."""
    tier_1: Tier1Preferences = Field(default_factory=Tier1Preferences)
    tier_2: Tier2Preferences = Field(default_factory=Tier2Preferences)
    optional: OptionalPreferences = Field(default_factory=OptionalPreferences)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NutrientCeiling(BaseModel):
    """User-set numeric ceiling with neutral reporting only (D3).

    Separate from calorie_goal / energy budgets so Safety Mode can suppress
    energy-budget language without touching ceiling display.
    """
    nutrient: str
    limit: float
    unit: str = "mg"


# ============================================================================
# DOCUMENTS
# ============================================================================

class FoodLog(Document):
    user_id: str
    raw_input: str
    food_name: str
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    # Fiber, sugar, micros, etc. — keys from nutrient_fields.EXTRA_NUTRIENT_FIELDS
    extra_nutrients: Optional[Dict[str, float]] = None
    quantity: Optional[str] = None
    confidence: Optional[str] = None       # "high" | "medium" | "low"
    reasoning: Optional[str] = None
    alternatives: Optional[List[str]] = None
    logged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: Optional[datetime] = None

    # Spec 1 — full FoodEvent / utterance stored alongside legacy fields.
    food_event: Optional[Dict] = None
    utterance: Optional[Dict] = None
    resolution_audit: Optional[Dict] = None

    class Settings:
        name = "food_logs"


class UserProfile(Document):
    user_id: str
    # Energy budget — kept SEPARATE from nutrient_ceilings (D3 / Safety Mode).
    calorie_goal: float = 2000.0
    first_name: str = ""
    last_name: str = ""
    screen_name: str = ""
    voice: str = "alloy"

    dietary_preferences: DietaryPreferences = Field(default_factory=DietaryPreferences)

    # Spec 1 reserved / v1 fields
    subscription_tier: Optional[str] = None  # unused until billing; a11y never gated on this
    wake_word_enabled: bool = False  # default OFF; opt-in with privacy disclaimer
    nutrient_display_preferences: List[str] = Field(default_factory=list)
    contribution_consent: bool = False  # consumption data is never shared regardless
    timezone: str = "UTC"
    nutrient_ceilings: List[NutrientCeiling] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "user_profiles"


class Correction(Document):
    user_id: str
    log_id: str
    original_food: str
    original_calories: Optional[float]
    original_confidence: Optional[str]
    corrected_food: Optional[str] = None
    corrected_calories: Optional[float] = None
    correction_type: Optional[str] = None  # "food" | "quantity" | "both"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "corrections"
