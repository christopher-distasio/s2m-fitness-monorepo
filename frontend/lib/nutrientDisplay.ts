/** Display catalog for Today's Summary nutrient toggles.
 *  Mirrors backend/services/nutrient_fields.py (keep labels/units in sync).
 */

export type CoreMacroKey = "protein" | "carbs" | "fat";

export type MacroExtraKey =
  | "fiber"
  | "sugar"
  | "saturated_fat"
  | "trans_fat"
  | "cholesterol";

export type MicroKey =
  | "sodium"
  | "calcium"
  | "iron"
  | "magnesium"
  | "potassium"
  | "zinc"
  | "phosphorus"
  | "copper"
  | "manganese"
  | "selenium"
  | "iodine"
  | "chromium"
  | "molybdenum"
  | "vitamin_a_rae_mcg"
  | "vitamin_c"
  | "vitamin_d_mcg"
  | "vitamin_e_mg"
  | "vitamin_k"
  | "vitamin_b1"
  | "vitamin_b2"
  | "vitamin_b3"
  | "vitamin_b6"
  | "folate_dfe_mcg"
  | "pantothenic_acid"
  | "vitamin_b12"
  | "biotin"
  | "choline"
  | "caffeine";

export type NutrientDisplayKey = CoreMacroKey | MacroExtraKey | MicroKey;

export const CORE_MACRO_KEYS: CoreMacroKey[] = ["protein", "carbs", "fat"];

export const MACRO_EXTRA_KEYS: MacroExtraKey[] = [
  "fiber",
  "sugar",
  "saturated_fat",
  "trans_fat",
  "cholesterol",
];

/** Macros shown as switches in the summary box (core + extras). */
export const MACRO_DISPLAY_KEYS: NutrientDisplayKey[] = [
  ...CORE_MACRO_KEYS,
  ...MACRO_EXTRA_KEYS,
];

export const MICRO_KEYS: MicroKey[] = [
  "sodium",
  "calcium",
  "iron",
  "magnesium",
  "potassium",
  "zinc",
  "phosphorus",
  "copper",
  "manganese",
  "selenium",
  "iodine",
  "chromium",
  "molybdenum",
  "vitamin_a_rae_mcg",
  "vitamin_c",
  "vitamin_d_mcg",
  "vitamin_e_mg",
  "vitamin_k",
  "vitamin_b1",
  "vitamin_b2",
  "vitamin_b3",
  "vitamin_b6",
  "folate_dfe_mcg",
  "pantothenic_acid",
  "vitamin_b12",
  "biotin",
  "choline",
  "caffeine",
];

export const NUTRIENT_META: Record<
  NutrientDisplayKey,
  { label: string; unit: string }
> = {
  protein: { label: "Protein", unit: "g" },
  carbs: { label: "Carbs", unit: "g" },
  fat: { label: "Fat", unit: "g" },
  fiber: { label: "Fiber", unit: "g" },
  sugar: { label: "Sugar", unit: "g" },
  saturated_fat: { label: "Sat. fat", unit: "g" },
  trans_fat: { label: "Trans fat", unit: "g" },
  cholesterol: { label: "Cholesterol", unit: "mg" },
  sodium: { label: "Sodium", unit: "mg" },
  calcium: { label: "Calcium", unit: "mg" },
  iron: { label: "Iron", unit: "mg" },
  magnesium: { label: "Magnesium", unit: "mg" },
  potassium: { label: "Potassium", unit: "mg" },
  zinc: { label: "Zinc", unit: "mg" },
  phosphorus: { label: "Phosphorus", unit: "mg" },
  copper: { label: "Copper", unit: "mg" },
  manganese: { label: "Manganese", unit: "mg" },
  selenium: { label: "Selenium", unit: "mcg" },
  iodine: { label: "Iodine", unit: "mcg" },
  chromium: { label: "Chromium", unit: "mcg" },
  molybdenum: { label: "Molybdenum", unit: "mcg" },
  vitamin_a_rae_mcg: { label: "Vitamin A", unit: "mcg" },
  vitamin_c: { label: "Vitamin C", unit: "mg" },
  vitamin_d_mcg: { label: "Vitamin D", unit: "mcg" },
  vitamin_e_mg: { label: "Vitamin E", unit: "mg" },
  vitamin_k: { label: "Vitamin K", unit: "mcg" },
  vitamin_b1: { label: "Thiamin (B1)", unit: "mg" },
  vitamin_b2: { label: "Riboflavin (B2)", unit: "mg" },
  vitamin_b3: { label: "Niacin (B3)", unit: "mg" },
  vitamin_b6: { label: "Vitamin B6", unit: "mg" },
  folate_dfe_mcg: { label: "Folate", unit: "mcg" },
  pantothenic_acid: { label: "Pantothenic acid", unit: "mg" },
  vitamin_b12: { label: "Vitamin B12", unit: "mcg" },
  biotin: { label: "Biotin", unit: "mcg" },
  choline: { label: "Choline", unit: "mg" },
  caffeine: { label: "Caffeine", unit: "mg" },
};

export type ShowNutrientsState = Record<NutrientDisplayKey, boolean>;

export function defaultShowNutrients(): ShowNutrientsState {
  const state = {} as ShowNutrientsState;
  for (const key of MACRO_DISPLAY_KEYS) state[key] = false;
  for (const key of MICRO_KEYS) state[key] = false;
  return state;
}

const STORAGE_KEY = "speak2me_show_nutrients";

export function readStoredShowNutrients(): ShowNutrientsState {
  const base = defaultShowNutrients();
  if (typeof window === "undefined") return base;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw) as Partial<ShowNutrientsState>;
    for (const key of Object.keys(base) as NutrientDisplayKey[]) {
      if (typeof parsed[key] === "boolean") base[key] = parsed[key]!;
    }
  } catch {
    /* ignore corrupt storage */
  }
  return base;
}

export function persistShowNutrients(state: ShowNutrientsState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

const CORE_PICK = new Set(["calories", "protein", "carbs", "fat"]);

/** Pull extra nutrient fields off a candidate / portion option for resolved log. */
export function extrasFromNutrientPick(
  pick: Record<string, unknown>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, val] of Object.entries(pick)) {
    if (CORE_PICK.has(key) || val == null) continue;
    if (
      !(MACRO_EXTRA_KEYS as string[]).includes(key) &&
      !(MICRO_KEYS as string[]).includes(key)
    ) {
      continue;
    }
    const n = Number(val);
    if (!Number.isNaN(n)) out[key] = n;
  }
  return out;
}
