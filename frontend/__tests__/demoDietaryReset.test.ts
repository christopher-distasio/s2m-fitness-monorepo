import {
  FDA_ALLERGENS,
  TIER1_DIET_OPTIONS,
  TIER2_OPTIONS,
  defaultDietaryPreferences,
  dietaryPreferencesPayload,
  putDefaultDietaryPreferences,
} from "../lib/dietaryPreferences";

const DEMO_USER_ID = "c0daaa18-4a82-4022-be8e-e21224683f88";

test("default dietary payload has nothing enabled", () => {
  const payload = dietaryPreferencesPayload(defaultDietaryPreferences());

  for (const key of FDA_ALLERGENS) {
    expect(payload.tier_1.allergens[key].enabled).toBe(false);
  }
  for (const { key } of TIER1_DIET_OPTIONS) {
    expect(payload.tier_1[key]).toBe(false);
  }
  for (const { key } of TIER2_OPTIONS) {
    expect(payload.tier_2[key]).toBe(false);
  }
  expect(payload.optional.low_fodmap).toBe(false);
});

test("putDefaultDietaryPreferences PUTs empty defaults for the shared demo user", async () => {
  const fetchMock = jest.fn().mockResolvedValue({ ok: true });
  const originalFetch = global.fetch;
  global.fetch = fetchMock as unknown as typeof fetch;

  try {
    const ok = await putDefaultDietaryPreferences(
      "http://localhost:8000",
      DEMO_USER_ID,
    );
    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://localhost:8000/user/${DEMO_USER_ID}/dietary-preferences`,
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.tier_1.allergens.egg.enabled).toBe(false);
    expect(body.tier_1.allergens.milk.enabled).toBe(false);
    expect(body.tier_1.lactose_free).toBe(false);
    expect(body.tier_2.keto).toBe(false);
  } finally {
    global.fetch = originalFetch;
  }
});
