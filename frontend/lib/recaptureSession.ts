/**
 * Recapture attempt state that lives in conversation history.
 * dismissPending() drops the history so a later recapture cannot inherit
 * the prior failure count.
 */

export type RecaptureHistoryMessage = {
  role: "user" | "assistant" | string;
  content: string;
};

export function recaptureFailuresFromHistory(
  history: RecaptureHistoryMessage[] | null | undefined,
): number {
  if (!history?.length) return 0;
  for (let i = history.length - 1; i >= 0; i--) {
    const message = history[i];
    if (message.role !== "assistant") continue;
    try {
      const data = JSON.parse(message.content || "");
      const recapture = data.recapture;
      if (recapture && typeof recapture === "object" && recapture.pending) {
        return Number(recapture.failures) || 0;
      }
      return 0;
    } catch {
      return 0;
    }
  }
  return 0;
}

/** History after dismissPending() — the recapture attempt is abandoned. */
export function conversationHistoryAfterDismissRecapture(): Array<{
  role: "user" | "assistant";
  content: string;
}> {
  return [];
}
