from beanie import Document
from pydantic import Field, BaseModel
from typing import Optional, List, Literal, Dict
from datetime import datetime, timezone

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
    quantity: Optional[str] = None
    confidence: Optional[str] = None       # "high" | "medium" | "low"
    reasoning: Optional[str] = None
    alternatives: Optional[List[str]] = None
    logged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: Optional[datetime] = None

    class Settings:
        name = "food_logs"


class UserProfile(Document):
    user_id: str
    calorie_goal: float = 2000.0
    first_name: str = ""
    last_name: str = ""
    screen_name: str = ""
    voice: str = "alloy"

    dietary_preferences: DietaryPreferences = Field(default_factory=DietaryPreferences)

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