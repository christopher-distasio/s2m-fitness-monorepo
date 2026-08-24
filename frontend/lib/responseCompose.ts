/**
 * Client fallback for Spec 3 copy. Backend `response_compose.py` is canonical;
 * this only covers UI-only strings that never hit the API (e.g. local summary
 * playback before a refetch). All playback still goes through `speak()`.
 */
export type VerbosityLevel = "quick" | "standard" | "careful";

const ENERGY_RE =
  /calories?\s+left|remaining\s+calories?|calorie\s+budget|energy\s+budget|calorie\s+goal|daily\s+goal|burn(?:ing)?\s+(?:off|it)|work\s+off|\boffset\b/i;

export function containsEnergyLanguage(text: string): boolean {
  return ENERGY_RE.test(text);
}

export function logConfirmationSpeech(
  food: string,
  calories: number | undefined,
  verbosity: VerbosityLevel,
  safetyMode: boolean,
): string {
  if (safetyMode) return `Logged ${food}.`;
  if (verbosity === "quick") return `Logged ${food}.`;
  const cal = Math.round(calories ?? 0);
  if (verbosity === "careful") {
    return `Logged ${food}, ${cal} calories.`;
  }
  return `Logged ${food}, ${cal} calories`;
}
