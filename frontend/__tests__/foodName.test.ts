import { formatBrandedName } from "../lib/foodName";

/**
 * Mirror of consecutive-brand detection used in backend regressions.
 * Ensures the TS helper is a general fix, not Great-Value-only.
 */
function consecutiveBrandDuplication(name: string, brand: string): boolean {
  const n = name
    .trim()
    .toLowerCase()
    .replace(/,/g, " ")
    .replace(/\s+/g, " ");
  const b = brand
    .trim()
    .toLowerCase()
    .replace(/,/g, " ")
    .replace(/\s+/g, " ");
  if (!n || !b) return false;
  return n.startsWith(`${b} ${b}`) || n.startsWith(`${b}, ${b}`);
}

describe("formatBrandedName", () => {
  const alreadyHasBrand: Array<[string, string]> = [
    ["GREAT VALUE", "GREAT VALUE POTATO CHIPS"],
    ["KROGER", "KROGER SMOKED DELI STYLE LEAN HAM, SMOKED"],
    ["CHOBANI", "CHOBANI NONFAT PLAIN YOGURT"],
    ["GOOD & GATHER", "GOOD & GATHER ROASTED ALMONDS"],
    ["MEMBER'S MARK", "MEMBER'S MARK TRAIL MIX"],
    ["KIRKLAND", "KIRKLAND SIGNATURE PROTEIN BAR"],
  ];

  it.each(alreadyHasBrand)(
    "does not double-prepend for %s (general pattern)",
    (brand, name) => {
      expect(formatBrandedName(name, brand)).toBe(name);
      expect(consecutiveBrandDuplication(formatBrandedName(name, brand), brand)).toBe(
        false,
      );
    },
  );

  it("is case-insensitive", () => {
    expect(
      formatBrandedName("Great Value Potato Chips", "GREAT VALUE"),
    ).toBe("Great Value Potato Chips");
  });

  it("prepends when brand is absent from name", () => {
    expect(formatBrandedName("POTATO CHIPS", "GREAT VALUE")).toBe(
      "GREAT VALUE POTATO CHIPS",
    );
  });

  it("returns name alone when brand is empty", () => {
    expect(formatBrandedName("Banana", "")).toBe("Banana");
    expect(formatBrandedName("Banana", null)).toBe("Banana");
  });

  it("skips owner prepend when name already starts with owner", () => {
    expect(
      formatBrandedName(
        "Wal-Mart Stores, Inc. GREAT VALUE, POTATO CHIPS",
        "Wal-Mart Stores, Inc.",
      ),
    ).toBe("Wal-Mart Stores, Inc. GREAT VALUE, POTATO CHIPS");
  });

  it("does not strip legitimate non-brand repeated words", () => {
    expect(formatBrandedName("HOT HOT SAUCE", "TABASCO")).toBe(
      "TABASCO HOT HOT SAUCE",
    );
    expect(
      formatBrandedName("GREAT VALUE MAYO MAYONNAISE", "GREAT VALUE"),
    ).toBe("GREAT VALUE MAYO MAYONNAISE");
  });

  it("spoken Great Value path has no audible brand brand repeat", () => {
    const name = formatBrandedName("GREAT VALUE POTATO CHIPS", "GREAT VALUE");
    const speech = `${name}, 1 oz, 150 calories`;
    expect(speech.toLowerCase()).not.toContain("great value great value");
  });
});
