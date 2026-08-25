import {
  conversationHistoryAfterDismissRecapture,
  recaptureFailuresFromHistory,
} from "../lib/recaptureSession";

test("dismissPending recapture path does not inherit the prior failure count", () => {
  const history = [
    {
      role: "assistant",
      content: JSON.stringify({
        recapture: { pending: true, failures: 2, missing_field: "food" },
      }),
    },
  ];
  expect(recaptureFailuresFromHistory(history)).toBe(2);

  const afterDismiss = conversationHistoryAfterDismissRecapture();
  expect(afterDismiss).toEqual([]);
  expect(recaptureFailuresFromHistory(afterDismiss)).toBe(0);
});
