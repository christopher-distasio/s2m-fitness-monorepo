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
