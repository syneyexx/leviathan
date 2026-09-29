/**
 * Pure dashboard view-model normalizers.
 * Missing / unknown measurements stay explicit — never invent production metrics.
 */

export type MeasuredValue =
  | { kind: "measured"; value: number }
  | { kind: "unmeasured" }
  | { kind: "unavailable" };

export type StatusTone = "success" | "warning" | "danger" | "muted" | "info";

export type BadgeTone =
  | "research"
  | "trading"
  | "training"
  | "data"
  | "system"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "muted";

const DUTCH_WEEKDAYS = ["Zo", "Ma", "Di", "Wo", "Do", "Vr", "Za"] as const;
const DUTCH_MONTHS = [
  "Jan",
  "Feb",
  "Mrt",
  "Apr",
  "Mei",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Okt",
  "Nov",
  "Dec",
] as const;

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

export function toMeasuredValue(
  value: number | null | undefined,
  available?: boolean,
): MeasuredValue {
  if (available === false) return { kind: "unavailable" };
  if (value == null || !Number.isFinite(value)) return { kind: "unmeasured" };
  return { kind: "measured", value };
}

export function clampPct(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 0) return 0;
  if (value > 100) return 100;
  return value;
}

/**
 * Format a utilization percentage for gauges.
 * Unavailable / null → "N/A" (never "0%" when unmeasured).
 * Measured zero stays "0%".
 */
export function formatPct(value: number | null | undefined, available?: boolean): string {
  if (available === false) return "N/A";
  if (value == null || !Number.isFinite(value)) return "N/A";
  const clamped = clampPct(value);
  if (clamped == null) return "N/A";
  return `${Math.round(clamped)}%`;
}

/** Format byte counts; missing → "—". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  let n = bytes;
  let unit = 0;
  while (n >= 1024 && unit < BYTE_UNITS.length - 1) {
    n /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || n >= 100 ? 0 : n >= 10 ? 1 : 1;
  const rounded = unit === 0 ? String(Math.round(n)) : n.toFixed(digits).replace(/\.0$/, "");
  return `${rounded} ${BYTE_UNITS[unit]}`;
}

/** Elapsed / ETA seconds → "2m 14s"; missing → "UNMEASURED". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "UNMEASURED";
  const total = Math.floor(seconds);
  if (total < 60) return `${total}s`;
  const hours = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    if (mins === 0 && secs === 0) return `${hours}h`;
    if (secs === 0) return `${hours}h ${mins}m`;
    return `${hours}h ${mins}m ${secs}s`;
  }
  if (secs === 0) return `${mins}m`;
  return `${mins}m ${secs}s`;
}

export function formatDutchDateTime(date: Date): { dateLine: string; timeLine: string } {
  const day = DUTCH_WEEKDAYS[date.getDay()] ?? "—";
  const month = DUTCH_MONTHS[date.getMonth()] ?? "—";
  const dateLine = `${day} ${date.getDate()} ${month} ${date.getFullYear()}`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return { dateLine, timeLine: `${hh}:${mm}:${ss}` };
}

type HealthLike = {
  ok?: boolean;
  llm?: { available?: boolean; model?: string | null; error?: string };
} | null;

/**
 * System operational label. "Operationeel" only when health.ok and the fetch did not error.
 */
export function normalizeSystemStatus(
  health: HealthLike,
  error?: string | null | boolean,
): { label: string; tone: StatusTone; operational: boolean } {
  const errored = Boolean(error);
  if (health?.ok === true && !errored) {
    return { label: "Operationeel", tone: "success", operational: true };
  }
  if (errored && health == null) {
    return { label: "Offline", tone: "danger", operational: false };
  }
  if (health?.ok === false || errored) {
    return { label: "Degraded", tone: "warning", operational: false };
  }
  if (health == null) {
    return { label: "Onbekend", tone: "muted", operational: false };
  }
  return { label: "Onbekend", tone: "muted", operational: false };
}

type ModelsStatusLike = {
  gatewayHealth?: string | null;
  activeModel?: string | null;
  runtime?: string | null;
} | null;

type ProviderLike = {
  id?: string;
  name?: string | null;
  kind?: string | null;
  type?: string | null;
  health?: string | null;
  reachable?: boolean | null;
} | null;

/**
 * LM Studio / local LLM sidebar row.
 * Prefer health.llm.available; never invent hardware product names.
 */
export function normalizeLmStudioStatus(
  health: HealthLike,
  modelsStatus?: ModelsStatusLike,
  providers?: ProviderLike[] | null,
): { label: string; value: string; tone: StatusTone } {
  const label = "LM Studio";

  if (health?.llm != null && typeof health.llm.available === "boolean") {
    if (health.llm.available) {
      const model = health.llm.model?.trim();
      return {
        label,
        value: model ? `Running · ${model}` : "Running",
        tone: "success",
      };
    }
    return { label, value: "Offline", tone: "danger" };
  }

  if (modelsStatus?.gatewayHealth) {
    const gh = String(modelsStatus.gatewayHealth).toLowerCase();
    if (gh === "ok" || gh === "healthy" || gh === "ready") {
      const model = modelsStatus.activeModel?.trim();
      return {
        label,
        value: model ? `Running · ${model}` : "Running",
        tone: "success",
      };
    }
    if (gh === "degraded" || gh === "partial") {
      return { label, value: "Degraded", tone: "warning" };
    }
    if (gh === "offline" || gh === "unavailable" || gh === "error") {
      return { label, value: "Offline", tone: "danger" };
    }
  }

  if (providers && providers.length > 0) {
    const local = providers.find((p) => {
      const kind = String(p?.kind || p?.type || "").toLowerCase();
      const id = String(p?.id || "").toLowerCase();
      const name = String(p?.name || "").toLowerCase();
      return (
        kind.includes("lmstudio") ||
        kind.includes("lm_studio") ||
        id.includes("lmstudio") ||
        name.includes("lm studio")
      );
    });
    if (local) {
      if (local.reachable === true || String(local.health || "").toLowerCase() === "healthy") {
        return { label, value: "Running", tone: "success" };
      }
      if (local.reachable === false) {
        return { label, value: "Offline", tone: "danger" };
      }
    }
  }

  return { label, value: "UNKNOWN", tone: "muted" };
}

export function domainBadgeTone(domain: string | null | undefined): BadgeTone {
  const d = String(domain || "")
    .trim()
    .toLowerCase();
  if (!d) return "muted";
  if (d.includes("research") || d.includes("onderzoek") || d.includes("brain")) return "research";
  if (d.includes("trad") || d.includes("market") || d.includes("paper")) return "trading";
  if (d.includes("train")) return "training";
  if (d.includes("data") || d.includes("dataset") || d.includes("ingest") || d.includes("source")) {
    return "data";
  }
  if (d.includes("system") || d.includes("worker") || d.includes("job") || d.includes("task")) {
    return "system";
  }
  if (d.includes("agent") || d.includes("chat") || d.includes("coding")) return "info";
  return "muted";
}

export function researchStatusTone(status: string): BadgeTone {
  const s = String(status || "")
    .trim()
    .toUpperCase();
  if (!s || s === "UNKNOWN" || s === "UNMEASURED") return "muted";
  if (s === "COMPLETED" || s === "DONE" || s === "READY" || s === "SUCCESS") return "success";
  if (
    s === "RUNNING" ||
    s === "ACTIVE" ||
    s === "IN_PROGRESS" ||
    s === "PLANNING" ||
    s === "QUEUED" ||
    s === "PENDING"
  ) {
    return "info";
  }
  if (s === "PAUSED" || s === "BLOCKED" || s === "DEGRADED" || s === "CANCELLED" || s === "CANCELED") {
    return "warning";
  }
  if (s === "FAILED" || s === "ERROR" || s === "CANCEL_REQUESTED") return "danger";
  return "muted";
}

export function workerStateTone(state: string | null | undefined): BadgeTone {
  const s = String(state || "")
    .trim()
    .toLowerCase();
  if (!s) return "muted";
  if (s === "busy" || s === "running" || s === "active") return "info";
  if (s === "ready" || s === "idle" || s === "online") return "success";
  if (s === "degraded" || s === "draining" || s === "starting") return "warning";
  if (s === "failed" || s === "error" || s === "dead") return "danger";
  return "muted";
}

/** Derive tasks/hour from completedToday when hours-so-far is valid; else null. */
export function deriveTasksPerHour(
  completedToday: number | null | undefined,
  now: Date = new Date(),
): number | null {
  if (completedToday == null || !Number.isFinite(completedToday) || completedToday < 0) return null;
  const hoursSoFar = now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600;
  if (hoursSoFar < 1 / 60) return null; // avoid divide-by-near-zero in first minute
  return completedToday / hoursSoFar;
}

export function extractUptimeLabel(runtime: Record<string, unknown> | null | undefined): string | null {
  if (!runtime || typeof runtime !== "object") return null;
  const candidates = [
    runtime.uptimeSeconds,
    runtime.uptime_seconds,
    runtime.uptimeSec,
    runtime.processUptimeSeconds,
  ];
  for (const c of candidates) {
    if (typeof c === "number" && Number.isFinite(c) && c >= 0) {
      return formatDuration(c);
    }
  }
  const startCandidates = [runtime.startedAt, runtime.started_at, runtime.processStartedAt];
  for (const raw of startCandidates) {
    if (typeof raw !== "string" || !raw.trim()) continue;
    const started = Date.parse(raw);
    if (!Number.isFinite(started)) continue;
    const elapsedSec = Math.max(0, (Date.now() - started) / 1000);
    return formatDuration(elapsedSec);
  }
  return null;
}
