import { formatBrandedName } from "../lib/foodName";

describe("formatBrandedName", () => {
  it("does not double-prepend when name already contains brand", () => {
    expect(
      formatBrandedName("GREAT VALUE POTATO CHIPS", "GREAT VALUE"),
    ).toBe("GREAT VALUE POTATO CHIPS");
  });

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
});
