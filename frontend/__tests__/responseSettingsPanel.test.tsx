import { fireEvent, render, screen } from "@testing-library/react";
import { ResponseSettingsPanel } from "../components/ResponseSettingsPanel";

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
  expect(screen.getByRole("radio", { name: /standard/i })).toBeChecked();
  expect(screen.getByRole("radio", { name: /careful/i })).toBeInTheDocument();
  expect(screen.queryByText(/upgrade|subscribe|premium/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("switch", { name: /safety mode/i }));
  expect(onSafetyModeChange).toHaveBeenCalledWith(true);
});
