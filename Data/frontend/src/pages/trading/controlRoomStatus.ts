/** Honest status display helpers for Control Room (no fake green). */

export type ControlRoomTone = "good" | "bad" | "warn" | "neutral" | "info";

const GREENISH = new Set([
  "PASS",
  "MEASURED",
  "OBSERVED",
  "READY",
  "HEALTHY",
  "VALID",
  "CERTIFIED",
]);
const BADISH = new Set([
  "FAIL",
  "DEGRADED",
  "BLOCKED",
  "BREACH",
  "ERROR",
  "BROKEN",
]);
const WARNISH = new Set([
  "PARTIAL",
  "IN_PROGRESS",
  "FEATURE_GATED",
  "NOT_CHECKED",
  "PENDING",
  "OPEN",
  "ESTIMATED",
]);
const INFOISH = new Set(["AVAILABLE"]);
const NEUTRAL = new Set([
  "UNMEASURED",
  "EMPTY",
  "UNAVAILABLE",
  "NOT_IMPLEMENTED",
  "ASSUMED",
  "INFEASIBLE",
  "INSUFFICIENT_HISTORY",
]);

export function controlRoomStatusTone(status: string | null | undefined): ControlRoomTone {
  const value = String(status || "UNMEASURED").trim().toUpperCase();
  if (GREENISH.has(value)) return "good";
  if (BADISH.has(value)) return "bad";
  if (WARNISH.has(value)) return "warn";
  if (INFOISH.has(value)) return "info";
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

/** Catalog declarations are not probed health. Never promote them to green. */
export function catalogStatusTone(status: string | null | undefined, catalogIsNotRuntimeProof: boolean): ControlRoomTone {
  const tone = controlRoomStatusTone(status);
  if (catalogIsNotRuntimeProof && tone === "good") return "neutral";
  return tone;
}
