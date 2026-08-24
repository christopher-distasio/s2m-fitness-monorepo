import { fireEvent, render, screen } from "@testing-library/react";
import { RecapturePanel } from "../components/RecapturePanel";

test("recapture panel names the caught food and offers type-instead when asked", () => {
  const onTypeInstead = jest.fn();
  const onDismiss = jest.fn();
  render(
    <RecapturePanel
      prompt="I caught 'chicken sandwich' but missed what came after."
      capturedFood="chicken sandwich"
      modalitySwitch
      onTypeInstead={onTypeInstead}
      onDismiss={onDismiss}
    />,
  );

  expect(
    screen.getByRole("region", { name: /fill that in/i }),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/chicken sandwich/i).length).toBeGreaterThan(0);
  expect(
    screen.getByText(/missed what came after/i),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /type instead/i }));
  expect(onTypeInstead).toHaveBeenCalled();
});
