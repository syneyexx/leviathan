/** Shared operational job/mission status semantics for LLM control-plane pages. */

export type UiJobTone = "ok" | "warn" | "err" | "idle" | "run";

const ACTIVE = new Set([
  "queued",
  "starting",
  "running",
  "preflight",
  "evaluating",
  "exporting",
  "cancelling",
  "pausing",
  "busy",
]);

const TERMINAL_OK = new Set(["completed", "succeeded", "ready"]);
const TERMINAL_BAD = new Set(["failed", "error", "interrupted", "unverified"]);
const TERMINAL_CANCEL = new Set(["cancelled", "canceled"]);
const DISABLED = new Set(["disabled", "archived", "unavailable"]);

export function normalizeJobStatus(status: string | null | undefined): string {
  return String(status || "unknown").trim().toLowerCase();
}

export function isActiveJobStatus(status: string | null | undefined): boolean {
  return ACTIVE.has(normalizeJobStatus(status));
}

export function isTerminalJobStatus(status: string | null | undefined): boolean {
  const s = normalizeJobStatus(status);
  return TERMINAL_OK.has(s) || TERMINAL_BAD.has(s) || TERMINAL_CANCEL.has(s) || DISABLED.has(s);
}

export function jobStatusTone(status: string | null | undefined): UiJobTone {
  const s = normalizeJobStatus(status);
  if (TERMINAL_OK.has(s) || s === "idle" || s === "online") return "ok";
  if (ACTIVE.has(s)) return "run";
  if (TERMINAL_CANCEL.has(s) || s === "paused" || s === "warn") return "warn";
  if (TERMINAL_BAD.has(s) || DISABLED.has(s) || s === "offline" || s === "error") return "err";
  return "idle";
}

export function formatElapsed(fromIso: string | null | undefined, toIso?: string | null): string {
  if (!fromIso) return "—";
  const start = Date.parse(fromIso);
  if (Number.isNaN(start)) return "—";
  const end = toIso ? Date.parse(toIso) : Date.now();
  if (Number.isNaN(end)) return "—";
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
