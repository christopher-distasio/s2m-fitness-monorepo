import { containsEnergyLanguage, logConfirmationSpeech } from "../lib/responseCompose";

test("safety mode log confirmation has no energy language", () => {
  const text = logConfirmationSpeech("eggs", 400, "careful", true);
  expect(text).toBe("Logged eggs.");
  expect(containsEnergyLanguage(text)).toBe(false);
  expect(text.toLowerCase()).not.toContain("calorie");
});

test("standard verbosity includes calories when safety mode is off", () => {
  const text = logConfirmationSpeech("eggs", 400, "standard", false);
  expect(text).toContain("400");
  expect(text.toLowerCase()).toContain("calorie");
});

test("energy-language detector matches calories remaining phrasing", () => {
  expect(containsEnergyLanguage("calories remaining")).toBe(true);
  expect(containsEnergyLanguage("calorie remaining")).toBe(true);
});
