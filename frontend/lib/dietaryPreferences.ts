/** Mirrors backend DietaryPreferences (models.py). */

export type AllergySeverity = "severe" | "moderate";

export type FdaAllergen =
  | "milk"
  | "egg"
  | "fish"
  | "shellfish"
  | "tree_nut"
  | "peanut"
  | "wheat"
  | "soy"
  | "sesame";

export interface AllergyConstraint {
  enabled: boolean;
  severity: AllergySeverity;
}

export interface Tier1Preferences {
  allergens: Record<FdaAllergen, AllergyConstraint>;
  gluten_free: boolean;
  lactose_free: boolean;
  vegan: boolean;
  vegetarian: boolean;
  kosher: boolean;
  halal: boolean;
  sulfite_free: boolean;
}

export interface Tier2Preferences {
  keto: boolean;
  low_carb: boolean;
  paleo: boolean;
  organic: boolean;
  non_gmo: boolean;
  grass_fed: boolean;
  pasture_raised: boolean;
  cage_free: boolean;
}

export interface OptionalPreferences {
  low_fodmap: boolean;
  nightshade_free: boolean;
  histamine_friendly: boolean;
}

export interface DietaryPreferences {
  tier_1: Tier1Preferences;
  tier_2: Tier2Preferences;
  optional: OptionalPreferences;
  updated_at?: string;
}

export const FDA_ALLERGENS: FdaAllergen[] = [
  "milk",
  "egg",
  "fish",
  "shellfish",
  "tree_nut",
  "peanut",
  "wheat",
  "soy",
  "sesame",
];

export const ALLERGEN_LABELS: Record<FdaAllergen, string> = {
  milk: "Milk",
  egg: "Egg",
  fish: "Fish",
  shellfish: "Shellfish",
  tree_nut: "Tree nuts",
  peanut: "Peanut",
  wheat: "Wheat",
  soy: "Soy",
  sesame: "Sesame",
};

export const TIER1_DIET_OPTIONS: {
  key: keyof Omit<Tier1Preferences, "allergens">;
  label: string;
  disabled?: boolean;
  hint?: string;
}[] = [
  { key: "gluten_free", label: "Gluten-free" },
  { key: "lactose_free", label: "Lactose-free" },
  { key: "vegan", label: "Vegan" },
  { key: "vegetarian", label: "Vegetarian" },
  { key: "kosher", label: "Kosher" },
  { key: "halal", label: "Halal" },
  {
    key: "sulfite_free",
    label: "Sulfite-free",
    disabled: true,
    hint: "Coming soon — not applied to search yet",
  },
];

export const TIER2_OPTIONS: { key: keyof Tier2Preferences; label: string }[] = [
  { key: "keto", label: "Keto" },
  { key: "low_carb", label: "Low-carb" },
  { key: "paleo", label: "Paleo" },
  { key: "organic", label: "Organic" },
  { key: "non_gmo", label: "Non-GMO" },
  { key: "grass_fed", label: "Grass-fed" },
  { key: "pasture_raised", label: "Pasture-raised" },
  { key: "cage_free", label: "Cage-free" },
];

export const OPTIONAL_OPTIONS: {
  key: keyof OptionalPreferences;
  label: string;
}[] = [
  { key: "low_fodmap", label: "Low-FODMAP" },
  { key: "nightshade_free", label: "Nightshade-free" },
  { key: "histamine_friendly", label: "Histamine-friendly" },
];

function allergyDefault(): AllergyConstraint {
  return { enabled: false, severity: "moderate" };
}

export function defaultDietaryPreferences(): DietaryPreferences {
  const allergens = {} as Record<FdaAllergen, AllergyConstraint>;
  for (const key of FDA_ALLERGENS) {
    allergens[key] = allergyDefault();
  }
  return {
    tier_1: {
      allergens,
      gluten_free: false,
      lactose_free: false,
      vegan: false,
      vegetarian: false,
      kosher: false,
      halal: false,
      sulfite_free: false,
    },
    tier_2: {
      keto: false,
      low_carb: false,
      paleo: false,
      organic: false,
      non_gmo: false,
      grass_fed: false,
      pasture_raised: false,
      cage_free: false,
    },
    optional: {
      low_fodmap: false,
      nightshade_free: false,
      histamine_friendly: false,
    },
  };
}

/** Merge API payload with defaults so every allergen key exists. */
export function normalizeDietaryPreferences(
  raw: Partial<DietaryPreferences> | null | undefined,
): DietaryPreferences {
  const base = defaultDietaryPreferences();
  if (!raw) return base;

  const allergens = { ...base.tier_1.allergens };
  const incoming = (raw.tier_1?.allergens ?? {}) as Partial<
    Record<FdaAllergen, Partial<AllergyConstraint>>
  >;
  for (const key of FDA_ALLERGENS) {
    const row = incoming[key];
    if (row && typeof row === "object") {
      allergens[key] = {
        enabled: Boolean(row.enabled),
        severity: row.severity === "severe" ? "severe" : "moderate",
      };
    }
  }

  return {
    tier_1: {
      ...base.tier_1,
      ...(raw.tier_1 ?? {}),
      allergens,
    },
    tier_2: {
      ...base.tier_2,
      ...(raw.tier_2 ?? {}),
    },
    optional: {
      ...base.optional,
      ...(raw.optional ?? {}),
    },
    updated_at: raw.updated_at,
  };
}

/**
 * Apply a GET snapshot without wiping in-progress edits.
 * Spurious refetches (voice-setup effect, overlapping loads) must not
 * clobber toggles the user has already flipped.
 */
export function applyFetchedDietaryPreferences(
  raw: Partial<DietaryPreferences> | null | undefined,
  local: DietaryPreferences,
  dirty: boolean,
): DietaryPreferences {
  return dirty ? local : normalizeDietaryPreferences(raw);
}

/** Body for PUT — omit client-only noise; server sets updated_at. */
export function dietaryPreferencesPayload(
  prefs: DietaryPreferences,
): Omit<DietaryPreferences, "updated_at"> {
  return {
    tier_1: prefs.tier_1,
    tier_2: prefs.tier_2,
    optional: prefs.optional,
  };
}

/** Wipe allergens/diet flags back to empty defaults (shared demo account). */
export async function putDefaultDietaryPreferences(
  apiBase: string,
  userId: string,
): Promise<boolean> {
  const res = await fetch(`${apiBase}/user/${userId}/dietary-preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(dietaryPreferencesPayload(defaultDietaryPreferences())),
  });
  return res.ok;
}
