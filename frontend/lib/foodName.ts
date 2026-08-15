/**
 * Join brand + name for display/speech without duplicating brand.
 * Pinecone branded `name` often already starts with brand_name
 * (e.g. "GREAT VALUE POTATO CHIPS"); prepending brand again yields
 * "Great Value Great Value…". Case-insensitive substring match.
 */
export function formatBrandedName(
  name: string | null | undefined,
  brand: string | null | undefined,
): string {
  const n = (name || "").trim();
  const b = (brand || "").trim();
  if (!b) return n;
  if (n.toLowerCase().includes(b.toLowerCase())) return n;
  return `${b} ${n}`;
}

const PLACEHOLDER_FOOD_NAME_RE =
  /^\d+(\.\d+)?\s*(g|gram|grams|oz|onz|ounce|ounces|ml|l|cup|cups|piece|pieces)?\.?$/i;

function candidateCalories(c: {
  calories?: number | null;
}): number {
  const n = Number(c.calories ?? 0);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

function candidateDisplayName(c: {
  name?: string | null;
  brand?: string | null;
}): string {
  return formatBrandedName(c.name, c.brand).trim();
}

function candidateSoftKey(c: {
  name?: string | null;
  brand?: string | null;
  calories?: number | null;
}): string {
  return `${candidateDisplayName(c).toLowerCase()}|${candidateCalories(c)}`;
}

function isJunkClarificationCandidate(
  c: { name?: string | null; brand?: string | null; calories?: number | null },
  allowZeroCal: boolean,
): boolean {
  const name = (c.name || "").trim();
  const display = candidateDisplayName(c);
  if (!name || !display || display.length < 2) return true;
  if (PLACEHOLDER_FOOD_NAME_RE.test(name) || PLACEHOLDER_FOOD_NAME_RE.test(display)) {
    return true;
  }
  if (!allowZeroCal && candidateCalories(c) <= 0) return true;
  return false;
}

/**
 * Client-side safety net mirroring backend clean_clarification_candidates:
 * drop junk/0-cal rows, exclude the primary pick, dedupe display clones.
 */
export function cleanClarificationCandidates<
  T extends {
    fdc_id?: string | number;
    name?: string | null;
    brand?: string | null;
    serving_label?: string | null;
    calories?: number | null;
  },
>(
  candidates: T[],
  primary: {
    food?: string | null;
    brand?: string | null;
    serving_label?: string | null;
    calories?: number | null;
    fdc_id?: string | number;
  },
  options?: { allowZeroCal?: boolean },
): T[] {
  const allowZeroCal = Boolean(options?.allowZeroCal);
  const primaryDisplay = formatBrandedName(primary.food, primary.brand)
    .trim()
    .toLowerCase();
  const primarySoft = primaryDisplay
    ? `${primaryDisplay}|${candidateCalories(primary)}`
    : "";
  const primaryId =
    primary.fdc_id != null ? String(primary.fdc_id) : null;

  const seenSoft = new Set<string>();
  const out: T[] = [];
  for (const c of candidates) {
    if (primaryId != null && String(c.fdc_id) === primaryId) continue;
    if (isJunkClarificationCandidate(c, allowZeroCal)) continue;
    const soft = candidateSoftKey(c);
    if (primarySoft && soft === primarySoft) continue;
    if (seenSoft.has(soft)) continue;
    seenSoft.add(soft);
    out.push(c);
  }
  return out;
}
