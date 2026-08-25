import {
  applyFetchedDietaryPreferences,
  defaultDietaryPreferences,
} from "../lib/dietaryPreferences";
import {
  applyFetchedResponseSettings,
  isVerbosityLevel,
} from "../lib/responseCompose";

test("fetched verbosity is ignored while a local save is in flight", () => {
  const local = { verbosityLevel: "quick" as const, safetyModeEnabled: true };
  const applied = applyFetchedResponseSettings(
    { verbosity_level: "standard", safety_mode_enabled: false },
    local,
    true,
  );
  expect(applied).toEqual(local);
});

test("fetched verbosity applies when nothing is dirty", () => {
  const applied = applyFetchedResponseSettings(
    { verbosity_level: "careful", safety_mode_enabled: true },
    { verbosityLevel: "standard", safetyModeEnabled: false },
    false,
  );
  expect(applied).toEqual({
    verbosityLevel: "careful",
    safetyModeEnabled: true,
  });
  expect(isVerbosityLevel("standard")).toBe(true);
  expect(isVerbosityLevel("loud")).toBe(false);
});

test("fetched dietary preferences do not clobber dirty local allergy toggles", () => {
  const local = defaultDietaryPreferences();
  local.tier_1.allergens.milk = { enabled: true, severity: "severe" };

  const fromServer = applyFetchedDietaryPreferences(
    defaultDietaryPreferences(),
    local,
    true,
  );
  expect(fromServer.tier_1.allergens.milk).toEqual({
    enabled: true,
    severity: "severe",
  });

  const clean = applyFetchedDietaryPreferences(
    defaultDietaryPreferences(),
    local,
    false,
  );
  expect(clean.tier_1.allergens.milk).toEqual({
    enabled: false,
    severity: "moderate",
  });
});
