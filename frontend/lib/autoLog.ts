/** Minimal parse shape for the auto-log vs clarify decision. */
export type AutoLogParsed = {
  confidence?: "high" | "medium" | "low" | "blocked";
  resolution_status?: string;
  resolution?: { status?: string; axis?: string | null } | null;
  confirmation?: { action?: string } | null;
};

export function clarificationAxis(
  parsed: AutoLogParsed,
): "amount" | "identity" | "brand" | null {
  const axis = parsed.resolution?.axis;
  if (axis === "amount" || axis === "identity" || axis === "brand") {
    return axis;
  }
  return null;
}

export function needsLookupClarification(parsed: AutoLogParsed): boolean {
  return (
    parsed.resolution_status === "needs_clarification" ||
    parsed.resolution?.status === "needs_clarification"
  );
}

/**
 * True when the client should log the headline match without asking.
 *
 * Lookup identity/amount questions (`needs_clarification`) take priority over
 * Spec 2 SILENT/CONFIRM and over a high overall confidence band. Otherwise a
 * branded banana search (high band + SILENT confirmation, but several SKUs)
 * auto-logs the top hit instead of showing the candidate list.
 */
export function shouldAutoLog(parsed: AutoLogParsed): boolean {
  if (
    parsed.resolution_status === "unresolved" ||
    parsed.resolution?.status === "unresolved"
  ) {
    return false;
  }
  if (parsed.resolution?.status === "needs_brand_choice") {
    return false;
  }
  if (parsed.confirmation?.action === "ASK") {
    return false;
  }
  if (needsLookupClarification(parsed)) {
    return false;
  }
  const action = parsed.confirmation?.action;
  if (action === "SILENT" || action === "CONFIRM") return true;
  return parsed.confidence === "high";
}
