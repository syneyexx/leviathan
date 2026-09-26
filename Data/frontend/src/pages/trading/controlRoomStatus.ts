/** Honest status display helpers for Control Room (no fake green). */

const GREENISH = new Set(["PASS", "MEASURED", "OBSERVED"]);
const BADISH = new Set(["FAIL", "DEGRADED", "BLOCKED"]);
const NEUTRAL = new Set([
  "UNMEASURED",
  "EMPTY",
  "UNAVAILABLE",
  "NOT_IMPLEMENTED",
  "ASSUMED",
  "ESTIMATED",
  "INFEASIBLE",
  "INSUFFICIENT_HISTORY",
  "FEATURE_GATED",
]);

export function controlRoomStatusTone(status: string | null | undefined): "good" | "bad" | "neutral" {
  const value = String(status || "UNMEASURED").trim().toUpperCase();
  if (GREENISH.has(value)) return "good";
  if (BADISH.has(value)) return "bad";
  if (NEUTRAL.has(value) || !value) return "neutral";
  return "neutral";
}

export function controlRoomStatusLabel(status: string | null | undefined): string {
  const value = String(status || "UNMEASURED").trim().toUpperCase() || "UNMEASURED";
  return value;
}

export function isHonestNonGreen(status: string | null | undefined): boolean {
  return controlRoomStatusTone(status) !== "good";
}
