import {
  clarificationAxis,
  needsLookupClarification,
  shouldAutoLog,
} from "../lib/autoLog";

const bananaBrandParse = {
  food: "banana",
  brand: "NUTTY & FRUITY",
  calories: 94.08,
  confidence: "high" as const,
  resolution_status: "needs_clarification",
  resolution: {
    status: "needs_clarification",
    axis: "identity",
  },
  confirmation: {
    action: "SILENT",
    asked_fields: [] as string[],
  },
  candidates: [
    { name: "BANANAS", brand: "NEXT ORGANICS", calories: 170 },
    { name: "BETTER'N PEANUT BUTTER BANANA", calories: 99.84 },
    { name: "CASALI CHOCO-BANANAS", brand: "CASALI", calories: 100 },
  ],
};

describe("shouldAutoLog", () => {
  it("does not auto-log a branded banana parse that still needs identity clarification", () => {
    expect(needsLookupClarification(bananaBrandParse)).toBe(true);
    expect(shouldAutoLog(bananaBrandParse)).toBe(false);
  });

  it("does not auto-log an unresolved phantom/not-recognized parse", () => {
    expect(
      shouldAutoLog({
        confidence: "high",
        resolution_status: "unresolved",
        resolution: { status: "unresolved" },
        confirmation: { action: "SILENT" },
      }),
    ).toBe(false);
  });

  it("still auto-logs a resolved high-confidence SILENT parse", () => {
    expect(
      shouldAutoLog({
        confidence: "high",
        resolution_status: "resolved",
        resolution: { status: "resolved" },
        confirmation: { action: "SILENT" },
      }),
    ).toBe(true);
  });

  it("does not auto-log the brand-vs-general gate", () => {
    expect(
      shouldAutoLog({
        confidence: "high",
        confirmation: { action: "SILENT" },
        resolution: { status: "needs_brand_choice" },
      }),
    ).toBe(false);
  });

  it("does not auto-log Spec 2 ASK", () => {
    expect(
      shouldAutoLog({
        confidence: "high",
        resolution_status: "resolved",
        confirmation: { action: "ASK" },
      }),
    ).toBe(false);
  });

  it("does not auto-log CONFIRM when lookup still needs clarification", () => {
    expect(
      shouldAutoLog({
        confidence: "high",
        resolution_status: "needs_clarification",
        resolution: { status: "needs_clarification" },
        confirmation: { action: "CONFIRM" },
      }),
    ).toBe(false);
  });

  it("auto-logs Spec 2 CONFIRM once lookup is resolved", () => {
    expect(
      shouldAutoLog({
        confidence: "medium",
        resolution_status: "resolved",
        resolution: { status: "resolved" },
        confirmation: { action: "CONFIRM" },
      }),
    ).toBe(true);
  });
});

describe("clarificationAxis", () => {
  it("treats yogurt NFS as amount-only, not soy vs almond identity", () => {
    expect(
      clarificationAxis({
        resolution: { status: "needs_clarification", axis: "amount" },
      }),
    ).toBe("amount");
  });
});
