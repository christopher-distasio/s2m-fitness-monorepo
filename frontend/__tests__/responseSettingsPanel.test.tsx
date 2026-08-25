import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ResponseSettingsPanel } from "../components/ResponseSettingsPanel";
import type { VerbosityLevel } from "../lib/responseCompose";

function VerbosityHarness({
  initial = "standard" as VerbosityLevel,
  onPersist,
}: {
  initial?: VerbosityLevel;
  onPersist?: (level: VerbosityLevel) => void;
}) {
  const [verbosityLevel, setVerbosityLevel] = useState<VerbosityLevel>(initial);
  const [safetyModeEnabled, setSafetyModeEnabled] = useState(false);
  return (
    <ResponseSettingsPanel
      verbosityLevel={verbosityLevel}
      safetyModeEnabled={safetyModeEnabled}
      onVerbosityChange={(level) => {
        setVerbosityLevel(level);
        onPersist?.(level);
      }}
      onSafetyModeChange={setSafetyModeEnabled}
    />
  );
}

test("verbosity and Safety Mode are always available, not paywalled", () => {
  const onVerbosityChange = jest.fn();
  const onSafetyModeChange = jest.fn();
  render(
    <ResponseSettingsPanel
      verbosityLevel="standard"
      safetyModeEnabled={false}
      onVerbosityChange={onVerbosityChange}
      onSafetyModeChange={onSafetyModeChange}
    />,
  );

  expect(screen.getByRole("radio", { name: /quick/i })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /standard/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("radio", { name: /careful/i })).toBeInTheDocument();
  expect(screen.queryByText(/upgrade|subscribe|premium/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("switch", { name: /safety mode/i }));
  expect(onSafetyModeChange).toHaveBeenCalledWith(true);
});

test("selecting a verbosity level deselects the others and keeps the persisted choice", () => {
  const persisted: VerbosityLevel[] = [];
  render(<VerbosityHarness onPersist={(level) => persisted.push(level)} />);

  expect(screen.getByRole("radio", { name: /standard/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("radio", { name: /quick/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: /careful/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );

  fireEvent.click(screen.getByRole("radio", { name: /quick/i }));
  expect(screen.getByRole("radio", { name: /quick/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("radio", { name: /standard/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: /careful/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(persisted).toEqual(["quick"]);

  fireEvent.click(screen.getByRole("radio", { name: /careful/i }));
  expect(screen.getByRole("radio", { name: /careful/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("radio", { name: /quick/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: /standard/i })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(persisted).toEqual(["quick", "careful"]);
});

test("Safety Mode copy uses plural calories remaining", () => {
  render(<VerbosityHarness />);
  expect(screen.getByText(/Hides calories remaining/i)).toBeInTheDocument();
  expect(screen.queryByText(/Hides calorie remaining/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("switch", { name: /safety mode/i }));
  expect(
    screen.getByText(/On — calories remaining and energy-budget language is hidden/i),
  ).toBeInTheDocument();
  expect(screen.queryByText(/calorie remaining/i)).not.toBeInTheDocument();
});
