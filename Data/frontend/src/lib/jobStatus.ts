/** Shared operational job/mission status semantics for LLM control-plane pages. */

import {
  isActiveJobState,
  isTerminalJobState,
  parseJobState,
  type JobState,
} from "./executionFabric";

export type { JobState };
export {
  ACTIVE_JOB_STATES,
  JOB_STATES,
  TERMINAL_JOB_STATES,
  isActiveJobState,
  isTerminalJobState,
  parseJobState,
  progressFromJob,
  type JobRecord,
  type ProgressEnvelope,
  type ResourceWait,
  type WorkerInstance,
  type WorkerInstanceState,
  type WorkerPoolStatus,
} from "./executionFabric";

export type UiJobTone = "ok" | "warn" | "err" | "idle" | "run";

const ACTIVE = new Set([
  "queued",
  "starting",
  "running",
  "preflight",
  "evaluating",
  "exporting",
  "cancelling",
  "cancel_requested",
  "retry_wait",
  "pausing",
  "busy",
]);

const TERMINAL_OK = new Set(["completed", "succeeded", "ready"]);
const TERMINAL_BAD = new Set(["failed", "error", "interrupted", "unverified"]);
const TERMINAL_CANCEL = new Set(["cancelled", "canceled"]);
const DISABLED = new Set(["disabled", "archived", "unavailable"]);

export function normalizeJobStatus(status: string | null | undefined): string {
  return String(status || "unknown")
    .trim()
    .toLowerCase()
    .replace(/-/g, "_");
}

export function isActiveJobStatus(status: string | null | undefined): boolean {
  const s = normalizeJobStatus(status);
  if (ACTIVE.has(s)) return true;
  return isActiveJobState(status);
}

export function isTerminalJobStatus(status: string | null | undefined): boolean {
  const s = normalizeJobStatus(status);
  if (TERMINAL_OK.has(s) || TERMINAL_BAD.has(s) || TERMINAL_CANCEL.has(s) || DISABLED.has(s)) {
    return true;
  }
  return isTerminalJobState(status);
}

export function jobStatusTone(status: string | null | undefined): UiJobTone {
  const s = normalizeJobStatus(status);
  if (TERMINAL_OK.has(s) || s === "idle" || s === "online") return "ok";
  if (s === "retry_wait") return "warn";
  if (s === "cancel_requested" || s === "cancelling") return "warn";
  if (ACTIVE.has(s) || isActiveJobState(status)) return "run";
  if (TERMINAL_CANCEL.has(s) || s === "paused" || s === "warn") return "warn";
  if (TERMINAL_BAD.has(s) || DISABLED.has(s) || s === "offline" || s === "error") return "err";
  return "idle";
}

/** Human label for fabric JobState values without redesigning page chrome. */
export function formatJobStateLabel(status: string | null | undefined): string {
  const parsed = parseJobState(status);
  if (!parsed) {
    const s = normalizeJobStatus(status);
    if (!s || s === "unknown") return "Unknown";
    return s
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }
  switch (parsed) {
    case "RETRY_WAIT":
      return "Retry wait";
    case "CANCEL_REQUESTED":
      return "Cancel requested";
    default:
      return parsed
        .split("_")
        .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
        .join(" ");
  }
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
