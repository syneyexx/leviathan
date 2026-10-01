/**
 * Exact-token status classification for Brain / product-truth surfaces.
 * Never treat substrings (e.g. "ready" inside "NOT_READY") as success.
 */

export type StatusTruthTone = "success" | "warning" | "danger" | "muted" | "info";

export type StatusKind = "success" | "warning" | "danger" | "unmeasured" | "unknown";

export type ClassifiedStatus = {
  token: string;
  value: string;
  tone: StatusTruthTone;
  kind: StatusKind;
};

const SUCCESS_TOKENS = new Set(["ready", "running", "ok", "healthy"]);
const WARNING_TOKENS = new Set(["degraded", "partial"]);
const DANGER_TOKENS = new Set([
  "offline",
  "down",
  "fail",
  "failed",
  "error",
  "unhealthy",
  "not_ready",
  "not_ok",
  "not_running",
  "unready",
  "unavailable",
  "dead",
]);

/** Normalize a raw status string to a single exact comparable token. */
export function normalizeStatusToken(raw: string | null | undefined): string {
  return String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

/** Classify an already-normalized token with exact-set membership only. */
export function classifyStatusToken(token: string): ClassifiedStatus {
  if (!token) {
    return { token: "unknown", value: "UNKNOWN", tone: "muted", kind: "unknown" };
  }
  if (SUCCESS_TOKENS.has(token)) {
    return {
      token,
      value: token === "running" ? "Running" : "Ready",
      tone: "success",
      kind: "success",
    };
  }
  if (WARNING_TOKENS.has(token)) {
    return { token, value: "Degraded", tone: "warning", kind: "warning" };
  }
  if (DANGER_TOKENS.has(token)) {
    return { token, value: "Offline", tone: "danger", kind: "danger" };
  }
  return { token, value: "UNKNOWN", tone: "muted", kind: "unknown" };
}

/** Normalize + classify a raw component/status string. */
export function classifyRawStatus(raw: string | null | undefined): ClassifiedStatus {
  return classifyStatusToken(normalizeStatusToken(raw));
}

/**
 * Map a measured product-truth component status for sidebar rows.
 * `measured === false` → UNMEASURED; unknown tokens → UNKNOWN.
 */
export function mapMeasuredComponentStatus(
  status: string | null | undefined,
  measured?: boolean,
): { value: string; tone: StatusTruthTone } {
  if (measured === false) return { value: "UNMEASURED", tone: "muted" };
  const classified = classifyRawStatus(status);
  return { value: classified.value, tone: classified.tone };
}
