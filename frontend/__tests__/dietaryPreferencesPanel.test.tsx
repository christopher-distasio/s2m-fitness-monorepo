import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { DietaryPreferencesPanel } from "../components/DietaryPreferencesPanel";
import {
  defaultDietaryPreferences,
  dietaryPreferencesPayload,
  type DietaryPreferences,
} from "../lib/dietaryPreferences";

function DietaryHarness({
  onPersist,
}: {
  onPersist?: (prefs: DietaryPreferences) => void;
}) {
  const [value, setValue] = useState<DietaryPreferences>(() =>
    defaultDietaryPreferences(),
  );
  return (
    <DietaryPreferencesPanel
      value={value}
      onChange={setValue}
      onSave={() => onPersist?.(value)}
    />
  );
}

test("allergy toggle stays on and severity choices remain visible", () => {
  render(<DietaryHarness />);

  const milkSwitch = screen.getByRole("switch", { name: /milk/i });
  expect(milkSwitch).toHaveAttribute("aria-checked", "false");
  expect(
    screen.queryByRole("radiogroup", { name: /milk severity/i }),
  ).not.toBeInTheDocument();

  fireEvent.click(milkSwitch);

  expect(screen.getByRole("switch", { name: /milk/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  const severity = screen.getByRole("radiogroup", { name: /milk severity/i });
  expect(severity).toBeInTheDocument();
  expect(within(severity).getByRole("radio", { name: /severe/i })).toBeVisible();
  expect(within(severity).getByRole("radio", { name: /moderate/i })).toBeVisible();
});

test("allergy severity selection stays selected and does not clear the toggle", () => {
  render(<DietaryHarness />);

  fireEvent.click(screen.getByRole("switch", { name: /egg/i }));
  const severity = screen.getByRole("radiogroup", { name: /egg severity/i });
  fireEvent.click(within(severity).getByRole("radio", { name: /severe/i }));

  expect(screen.getByRole("switch", { name: /egg/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(within(severity).getByRole("radio", { name: /severe/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(
    within(severity).getByRole("radio", { name: /moderate/i }),
  ).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("radiogroup", { name: /egg severity/i }),
  ).toBeInTheDocument();
});

test("save persists allergy toggle and severity", () => {
  const persisted: DietaryPreferences[] = [];
  render(<DietaryHarness onPersist={(prefs) => persisted.push(prefs)} />);

  fireEvent.click(screen.getByRole("switch", { name: /milk/i }));
  fireEvent.click(
    within(screen.getByRole("radiogroup", { name: /milk severity/i })).getByRole(
      "radio",
      { name: /severe/i },
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /save dietary preferences/i }));

  expect(persisted).toHaveLength(1);
  const payload = dietaryPreferencesPayload(persisted[0]);
  expect(payload.tier_1.allergens.milk).toEqual({
    enabled: true,
    severity: "severe",
  });
  expect(payload.tier_1.allergens.egg.enabled).toBe(false);
});
