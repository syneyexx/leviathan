/** Pure view-model helpers for Modules page — derived only from real API payloads. */

import type { ModuleSnapshot } from "../../../types/api";

export type ManagedModuleRow = NonNullable<ModuleSnapshot["modules"]>[number];

export type ModuleFilterId = "all" | "installed" | "not_installed" | "updates";

export type StatusTone = "ok" | "warn" | "err" | "muted" | "gold" | "cyan";

export type DetailTabId =
  | "configuration"
  | "health"
  | "runtime"
  | "dependencies"
  | "jobs"
  | "logs"
  | "manifest"
  | "execute"
  | "versions"
  | "capabilities";

export type MeasuredValue<T> =
  | { kind: "measured"; value: T }
  | { kind: "unmeasured" }
  | { kind: "not_checked" }
  | { kind: "not_available" };

export type ModuleKpis = {
  featureFlag: "ON" | "OFF";
  totalModules: number;
  executable: number;
  healthIssues: number;
  updateAvailable: MeasuredValue<number>;
};

export type ActionAvailability = {
  canInstall: boolean;
  canStart: boolean;
  canStop: boolean;
  canRestart: boolean;
  canEnsureReady: boolean;
  canHealth: boolean;
  canJobs: boolean;
  canLogs: boolean;
  canCapabilities: boolean;
  canVersions: boolean;
  canCheckUpdate: boolean;
  canInstallVersion: boolean;
  canActivateVersion: boolean;
  canRollback: boolean;
  canExecute: boolean;
  installReason?: string;
  startReason?: string;
  stopReason?: string;
  restartReason?: string;
  ensureReadyReason?: string;
  executeReason?: string;
  activateReason?: string;
};

export type CapabilityItem = {
  capabilityId: string;
  name: string;
  description: string;
  sideEffects: string[];
};

export type LocalNavItem = {
  id: string;
  label: string;
  to?: string;
  active?: boolean;
  disabled?: boolean;
  title?: string;
};

export const DETAIL_TABS: readonly { id: DetailTabId; label: string }[] = [
  { id: "configuration", label: "Configuration" },
  { id: "health", label: "Health Details" },
  { id: "runtime", label: "Runtime Info" },
  { id: "dependencies", label: "Dependencies" },
  { id: "jobs", label: "Jobs" },
  { id: "logs", label: "Logs" },
  { id: "manifest", label: "Manifest" },
] as const;

/** Real sibling routes under Plugin & Runtime; unsupported items stay disabled. */
export const LOCAL_NAV: readonly LocalNavItem[] = [
  {
    id: "overview",
    label: "Overview",
    to: "/performance",
    title: "Open Performance overview",
  },
  { id: "modules", label: "Modules", to: "/modules", active: true },
  {
    id: "runtimes",
    label: "Runtimes",
    disabled: true,
    title: "Runtimes view is not available yet",
  },
  {
    id: "installation",
    label: "Installation",
    disabled: true,
    title: "Installation workspace is not available yet",
  },
  {
    id: "environments",
    label: "Environments",
    disabled: true,
    title: "Environments view is not available yet",
  },
  { id: "settings", label: "Settings", to: "/settings", title: "Open Settings" },
] as const;

const INSTALLED_STATUSES = new Set([
  "INSTALLED",
  "LOADED",
  "INITIALIZED",
  "READY",
  "RUNNING",
  "BUSY",
  "EXECUTING",
  "STARTING",
  "STOPPING",
  "STOPPED",
  "DEGRADED",
]);

const EXECUTABLE_STATUSES = new Set(["READY", "RUNNING", "BUSY", "EXECUTING", "INITIALIZED", "INSTALLED"]);

const HEALTH_ISSUE_STATUSES = new Set(["ERROR", "FAILED", "DEGRADED"]);

const SECRET_KEY_RE = /(password|secret|token|api[_-]?key|credential|private[_-]?key|auth)/i;

export function moduleId(row: ManagedModuleRow | null | undefined): string {
  return row?.manifest?.module_id ?? "unknown";
}

export function moduleName(row: ManagedModuleRow | null | undefined): string {
  if (!row) return "—";
  return row.manifest?.name?.trim() || moduleId(row);
}

export function moduleVersion(row: ManagedModuleRow | null | undefined): string | null {
  const v = row?.manifest?.version?.trim();
  return v || null;
}

export function moduleDescription(row: ManagedModuleRow | null | undefined): string {
  const meta = row?.manifest?.metadata;
  if (meta && typeof meta === "object") {
    const desc = (meta as Record<string, unknown>).description;
    if (typeof desc === "string" && desc.trim()) return desc.trim();
  }
  const caps = row?.manifest?.capabilities;
  if (Array.isArray(caps) && caps.length > 0) {
    const first = caps[0];
    if (first && typeof first === "object") {
      const d = (first as Record<string, unknown>).description;
      if (typeof d === "string" && d.trim()) return d.trim();
    }
  }
  return "";
}

export function statusUpper(status?: string | null): string {
  return (status ?? "").toUpperCase();
}

export function statusTone(status?: string | null): StatusTone {
  const s = statusUpper(status);
  if (s === "READY" || s === "RUNNING" || s === "INSTALLED") return "ok";
  if (s === "ERROR" || s === "FAILED") return "err";
  if (s === "DEGRADED") return "warn";
  if (s === "EXECUTING" || s === "BUSY" || s === "STARTING" || s === "LOADED" || s === "INITIALIZED") return "gold";
  if (s === "DISCOVERED" || s === "STOPPED" || s === "DISABLED") return "cyan";
  if (s === "SHUTDOWN" || s === "NOT_INSTALLED") return "muted";
  return "muted";
}

export function isInstalled(row: ManagedModuleRow): boolean {
  return INSTALLED_STATUSES.has(statusUpper(row.status));
}

export function isExecutable(row: ManagedModuleRow): boolean {
  return EXECUTABLE_STATUSES.has(statusUpper(row.status));
}

export function isReady(row: ManagedModuleRow): boolean {
  const s = statusUpper(row.status);
  return s === "READY" || s === "RUNNING" || s === "BUSY" || s === "EXECUTING";
}

export function hasHealthIssue(row: ManagedModuleRow): boolean {
  const s = statusUpper(row.status);
  if (HEALTH_ISSUE_STATUSES.has(s)) return true;
  const hs = statusUpper(
    row.health && typeof row.health === "object" ? String((row.health as Record<string, unknown>).status ?? "") : "",
  );
  return HEALTH_ISSUE_STATUSES.has(hs);
}

export function canLifecycle(row: ManagedModuleRow): boolean {
  return Boolean(row.adapter || row.manifest?.metadata?.external);
}

export function isBusyStatus(row: ManagedModuleRow): boolean {
  const s = statusUpper(row.status);
  return s === "BUSY" || s === "EXECUTING" || s === "STARTING" || s === "STOPPING";
}

/** Update availability is only measured after check-update evidence exists. */
export function updateAvailableFromEvidence(
  evidence: Record<string, unknown> | null | undefined,
): MeasuredValue<boolean> {
  if (!evidence || typeof evidence !== "object") return { kind: "not_checked" };
  if (!("update_available" in evidence)) return { kind: "not_checked" };
  const v = evidence.update_available;
  if (typeof v === "boolean") return { kind: "measured", value: v };
  if (v == null) return { kind: "unmeasured" };
  return { kind: "measured", value: Boolean(v) };
}

export function deriveKpis(
  snapshot: ModuleSnapshot | null,
  updateEvidenceByModule: Record<string, Record<string, unknown> | null | undefined>,
): ModuleKpis {
  const modules = snapshot?.modules ?? [];
  const managerOn = snapshot == null ? true : snapshot.enabled !== false;
  let measuredUpdates = 0;
  let anyChecked = false;
  for (const row of modules) {
    const id = moduleId(row);
    const evidence = updateEvidenceByModule[id];
    const avail = updateAvailableFromEvidence(evidence);
    if (avail.kind === "measured") {
      anyChecked = true;
      if (avail.value) measuredUpdates += 1;
    }
  }
  return {
    featureFlag: managerOn ? "ON" : "OFF",
    totalModules: modules.length,
    executable: modules.filter(isExecutable).length,
    healthIssues: modules.filter(hasHealthIssue).length,
    updateAvailable: anyChecked
      ? { kind: "measured", value: measuredUpdates }
      : { kind: "not_checked" },
  };
}

export function filterCounts(
  modules: ManagedModuleRow[],
  updateEvidenceByModule: Record<string, Record<string, unknown> | null | undefined>,
): Record<ModuleFilterId, number> {
  let installed = 0;
  let notInstalled = 0;
  let updates = 0;
  for (const row of modules) {
    if (isInstalled(row)) installed += 1;
    else notInstalled += 1;
    const avail = updateAvailableFromEvidence(updateEvidenceByModule[moduleId(row)]);
    if (avail.kind === "measured" && avail.value) updates += 1;
  }
  return {
    all: modules.length,
    installed,
    not_installed: notInstalled,
    updates,
  };
}

export function filterModules(
  modules: ManagedModuleRow[],
  query: string,
  filter: ModuleFilterId,
  updateEvidenceByModule: Record<string, Record<string, unknown> | null | undefined>,
): ManagedModuleRow[] {
  const q = query.trim().toLowerCase();
  return modules.filter((row) => {
    if (filter === "installed" && !isInstalled(row)) return false;
    if (filter === "not_installed" && isInstalled(row)) return false;
    if (filter === "updates") {
      const avail = updateAvailableFromEvidence(updateEvidenceByModule[moduleId(row)]);
      if (!(avail.kind === "measured" && avail.value)) return false;
    }
    if (!q) return true;
    const metadata = row.manifest?.metadata;
    const tagValue =
      metadata && typeof metadata === "object" ? (metadata as Record<string, unknown>).tags : undefined;
    const tags = Array.isArray(tagValue) ? tagValue.join(" ") : "";
    const hay = [
      moduleId(row),
      moduleName(row),
      row.status ?? "",
      row.runtime_state ?? "",
      row.adapter ?? "",
      row.error ?? "",
      moduleDescription(row),
      tags,
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

export function actionAvailability(
  row: ManagedModuleRow | null,
  opts: { managerEnabled: boolean; lifecycleBusy: boolean; hasVersionId: boolean },
): ActionAvailability {
  if (!row) {
    return {
      canInstall: false,
      canStart: false,
      canStop: false,
      canRestart: false,
      canEnsureReady: false,
      canHealth: false,
      canJobs: false,
      canLogs: false,
      canCapabilities: false,
      canVersions: false,
      canCheckUpdate: false,
      canInstallVersion: false,
      canActivateVersion: false,
      canRollback: false,
      canExecute: false,
      executeReason: "No module selected",
    };
  }
  const s = statusUpper(row.status);
  const lifecycle = canLifecycle(row);
  const busy = opts.lifecycleBusy || isBusyStatus(row);
  const managerOff = !opts.managerEnabled;
  const baseDisabled = managerOff || !lifecycle || busy;

  const notInstalled = s === "DISCOVERED" || s === "NOT_INSTALLED" || (!isInstalled(row) && s !== "READY");
  const canStart =
    !baseDisabled && (s === "INSTALLED" || s === "STOPPED" || s === "READY" || s === "DISCOVERED" || s === "LOADED");
  const canStop = !baseDisabled && (s === "READY" || s === "RUNNING" || s === "BUSY" || s === "INSTALLED");
  const canRestart = !baseDisabled && isInstalled(row);
  const canEnsureReady = !baseDisabled && lifecycle;
  const canInstall = !baseDisabled && (notInstalled || s === "DISCOVERED" || s === "FAILED" || s === "ERROR");
  const canExecute = opts.managerEnabled && isReady(row) && !busy;

  return {
    canInstall,
    canStart,
    canStop,
    canRestart,
    canEnsureReady,
    canHealth: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canJobs: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canLogs: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canCapabilities: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canVersions: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canCheckUpdate: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canInstallVersion: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canActivateVersion: opts.managerEnabled && lifecycle && !opts.lifecycleBusy && opts.hasVersionId,
    canRollback: opts.managerEnabled && lifecycle && !opts.lifecycleBusy,
    canExecute,
    installReason: managerOff
      ? "Module manager feature flag OFF"
      : !lifecycle
        ? "Lifecycle not supported for this module"
        : busy
          ? "Module is busy"
          : !canInstall
            ? `Install not available (status: ${s || "unknown"})`
            : undefined,
    startReason: !canStart ? `Start not available (status: ${s || "unknown"})` : undefined,
    stopReason: !canStop ? `Stop not available (status: ${s || "unknown"})` : undefined,
    restartReason: !canRestart ? `Restart not available (status: ${s || "unknown"})` : undefined,
    ensureReadyReason: !canEnsureReady ? "Ensure Ready not available" : undefined,
    executeReason: !canExecute
      ? managerOff
        ? "Module manager feature flag OFF"
        : `Requires READY/RUNNING (current: ${s || "unknown"})`
      : undefined,
    activateReason: !opts.hasVersionId ? "version_id is required to activate" : undefined,
  };
}

export function parseCapabilities(raw: unknown): CapabilityItem[] {
  if (!Array.isArray(raw)) return [];
  const out: CapabilityItem[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const capabilityId = String(rec.capability_id ?? rec.id ?? "").trim();
    const name = String(rec.name ?? (capabilityId || "capability")).trim();
    if (!capabilityId && !name) continue;
    const description = typeof rec.description === "string" ? rec.description : "";
    const sideEffects = Array.isArray(rec.side_effects)
      ? rec.side_effects.map((x) => String(x))
      : [];
    out.push({
      capabilityId: capabilityId || name,
      name: name || capabilityId,
      description,
      sideEffects,
    });
  }
  return out;
}

export function capabilitiesFromRow(row: ManagedModuleRow | null): CapabilityItem[] {
  if (!row) return [];
  return parseCapabilities(row.manifest?.capabilities);
}

export function tryParseArgs(raw: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Arguments must be a JSON object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Invalid JSON arguments" };
  }
}

/** Strip secret-looking keys from configuration for safe display. */
export function redactSecrets(value: unknown, depth = 0): unknown {
  if (depth > 8) return "[truncated]";
  if (Array.isArray(value)) return value.map((v) => redactSecrets(v, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SECRET_KEY_RE.test(k)) {
        out[k] = "[REDACTED]";
      } else {
        out[k] = redactSecrets(v, depth + 1);
      }
    }
    return out;
  }
  return value;
}

export function safeConfiguration(row: ManagedModuleRow | null): Record<string, unknown> {
  if (!row) return {};
  const meta = row.manifest?.metadata;
  const external =
    meta && typeof meta === "object" && "external" in meta
      ? redactSecrets((meta as Record<string, unknown>).external)
      : undefined;
  return {
    module_id: moduleId(row),
    name: moduleName(row),
    version: moduleVersion(row),
    status: row.status ?? null,
    runtime_state: row.runtime_state ?? null,
    desired_state: row.desired_state ?? null,
    adapter: row.adapter ?? null,
    source_path: row.manifest?.source_path ?? null,
    isolation: row.manifest?.isolation ?? null,
    capabilities: capabilitiesFromRow(row).map((c) => ({
      capability_id: c.capabilityId,
      name: c.name,
      side_effects: c.sideEffects,
    })),
    external: external ?? null,
    truth: row.truth ?? null,
  };
}

export function healthLabel(row: ManagedModuleRow | null): { label: string; tone: StatusTone; detail: string } {
  if (!row) return { label: "UNMEASURED", tone: "muted", detail: "No module selected" };
  const hs =
    row.health && typeof row.health === "object"
      ? statusUpper(String((row.health as Record<string, unknown>).status ?? ""))
      : "";
  const s = hs || statusUpper(row.status);
  if (!s) return { label: "UNMEASURED", tone: "muted", detail: "Health not measured" };
  if (s === "READY" || s === "RUNNING" || s === "INSTALLED") {
    return {
      label: s === "INSTALLED" ? "Installed" : "Healthy",
      tone: "ok",
      detail:
        row.health && typeof row.health === "object" && typeof (row.health as Record<string, unknown>).detail === "string"
          ? String((row.health as Record<string, unknown>).detail)
          : "Lifecycle status healthy",
    };
  }
  if (s === "DEGRADED") {
    return { label: "Degraded", tone: "warn", detail: row.error || "Partial composite health" };
  }
  if (s === "ERROR" || s === "FAILED") {
    return { label: "Unhealthy", tone: "err", detail: row.error || "Health reported failure" };
  }
  if (s === "DISCOVERED" || s === "NOT_INSTALLED") {
    return { label: "Discovered", tone: "cyan", detail: "Not installed yet" };
  }
  if (s === "BUSY" || s === "EXECUTING" || s === "STARTING") {
    return { label: "Busy", tone: "gold", detail: "Lifecycle in progress" };
  }
  return { label: s, tone: statusTone(s), detail: row.error || "—" };
}

export function measuredFromHealth(
  health: Record<string, unknown> | null | undefined,
  key: string,
): MeasuredValue<string | number> {
  if (!health) return { kind: "unmeasured" };
  const telemetry = health.telemetry;
  const sources: Record<string, unknown>[] = [health];
  if (telemetry && typeof telemetry === "object") sources.push(telemetry as Record<string, unknown>);
  for (const src of sources) {
    if (key in src && src[key] != null && src[key] !== "") {
      const v = src[key];
      if (typeof v === "string" || typeof v === "number") return { kind: "measured", value: v };
      return { kind: "measured", value: String(v) };
    }
  }
  return { kind: "unmeasured" };
}

export function formatMeasured(m: MeasuredValue<string | number | boolean>, fallback = "UNMEASURED"): string {
  if (m.kind === "measured") return String(m.value);
  if (m.kind === "not_checked") return "NOT CHECKED";
  if (m.kind === "not_available") return "NOT AVAILABLE";
  return fallback;
}

export function lifecycleBadges(row: ManagedModuleRow): { label: string; tone: StatusTone }[] {
  const badges: { label: string; tone: StatusTone }[] = [];
  const s = statusUpper(row.status);
  if (s === "DISCOVERED" || !isInstalled(row)) {
    badges.push({ label: "DISCOVERED", tone: "cyan" });
  }
  if (isInstalled(row)) {
    badges.push({ label: "INSTALLED", tone: "ok" });
  }
  if (s && s !== "DISCOVERED" && s !== "INSTALLED" && s !== "NOT_INSTALLED") {
    badges.push({ label: s, tone: statusTone(s) });
  }
  if (row.adapter) {
    badges.push({ label: row.adapter.toUpperCase(), tone: "muted" });
  }
  return badges;
}

export function declaredOperations(row: ManagedModuleRow | null): string[] {
  if (!row) return [];
  const meta = row.manifest?.metadata;
  const external = meta && typeof meta === "object" ? (meta as Record<string, unknown>).external : null;
  const runtime =
    external && typeof external === "object" ? (external as Record<string, unknown>).runtime : null;
  const ops = runtime && typeof runtime === "object" ? (runtime as Record<string, unknown>).operations : null;
  if (!Array.isArray(ops)) {
    const caps = capabilitiesFromRow(row);
    return caps.map((c) => c.capabilityId.split(".").pop() || c.name).filter(Boolean);
  }
  const names: string[] = [];
  for (const op of ops) {
    if (op && typeof op === "object") {
      const n = String((op as Record<string, unknown>).name ?? (op as Record<string, unknown>).operation ?? "").trim();
      if (n) names.push(n);
    }
  }
  return names;
}

export function dependenciesFromRow(row: ManagedModuleRow | null): MeasuredValue<unknown[]> {
  if (!row) return { kind: "not_available" };
  const meta = row.manifest?.metadata;
  const external = meta && typeof meta === "object" ? (meta as Record<string, unknown>).external : null;
  const install =
    external && typeof external === "object" ? (external as Record<string, unknown>).install : null;
  if (!install || typeof install !== "object") return { kind: "unmeasured" };
  const deps = (install as Record<string, unknown>).dependencies ?? (install as Record<string, unknown>).requires;
  if (Array.isArray(deps)) return { kind: "measured", value: deps };
  if (deps && typeof deps === "object") return { kind: "measured", value: Object.entries(deps as Record<string, unknown>) };
  return { kind: "unmeasured" };
}
