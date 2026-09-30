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
  featureFlag: "ON" | "OFF" | null;
  totalModules: number | null;
  executable: number | null;
  healthIssues: number | null;
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
  healthReason?: string;
  checkUpdateReason?: string;
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

/** Real sibling routes / addressable workspace views under Runtime & Tools. */
export function localNavItems(activeView: string): LocalNavItem[] {
  return [
    {
      id: "overview",
      label: "Overview",
      to: "/performance",
      title: "Open Performance overview",
    },
    {
      id: "modules",
      label: "Modules",
      to: "/modules",
      active: activeView === "modules",
      title: "Modules library",
    },
    {
      id: "runtimes",
      label: "Runtimes",
      to: "/modules?view=runtimes",
      active: activeView === "runtimes",
      title: "Runtime projection of ModuleManager + JobRuntime",
    },
    {
      id: "installation",
      label: "Installation",
      to: "/modules?view=installation",
      active: activeView === "installation",
      title: "Install plans, operations and version history",
    },
    {
      id: "environments",
      label: "Environments",
      to: "/modules?view=environments",
      active: activeView === "environments",
      title: "External module environment isolation projection",
    },
    { id: "settings", label: "Settings", to: "/settings", title: "Open Settings" },
  ];
}

/** @deprecated Prefer localNavItems(activeView) for URL-addressable views. */
export const LOCAL_NAV: readonly LocalNavItem[] = localNavItems("modules");

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
  if (snapshot == null) {
    return {
      featureFlag: null,
      totalModules: null,
      executable: null,
      healthIssues: null,
      updateAvailable: { kind: "not_available" },
    };
  }
  const modules = snapshot.modules ?? [];
  const managerOn = snapshot.enabled !== false;
  let measuredUpdates = 0;
  let anyChecked = false;
  let anyPartial = false;
  for (const row of modules) {
    const id = moduleId(row);
    const evidence = updateEvidenceByModule[id] ?? row.update_evidence ?? null;
    const avail = updateAvailableFromEvidence(evidence);
    if (avail.kind === "measured") {
      anyChecked = true;
      if (avail.value) measuredUpdates += 1;
    } else if (avail.kind === "unmeasured") {
      anyPartial = true;
    }
  }
  return {
    featureFlag: managerOn ? "ON" : "OFF",
    totalModules: modules.length,
    executable: modules.filter(isExecutable).length,
    healthIssues: modules.filter(hasHealthIssue).length,
    updateAvailable: anyChecked
      ? { kind: "measured", value: measuredUpdates }
      : anyPartial
        ? { kind: "unmeasured" }
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

  // Prefer server-projected lifecycle capability state when present.
  const server = row.allowed_actions;
  const blocked = row.blocked_reasons ?? {};
  if (server && typeof server === "object") {
    const busyOverride = opts.lifecycleBusy;
    const bool = (key: string, fallback: boolean) => {
      if (busyOverride && ["can_install", "can_start", "can_stop", "can_restart", "can_ensure_ready", "can_execute", "can_install_version", "can_activate_version", "can_rollback"].includes(key)) {
        return false;
      }
      const v = (server as Record<string, unknown>)[key];
      return typeof v === "boolean" ? v : fallback;
    };
    const reason = (key: string, fallback?: string) => {
      if (busyOverride && ["can_install", "can_start", "can_stop", "can_restart", "can_ensure_ready", "can_execute"].includes(key)) {
        return "Lifecycle operation in progress";
      }
      const r = blocked[key];
      return typeof r === "string" ? r : fallback;
    };
    const canActivate =
      bool("can_activate_version", false) && opts.hasVersionId && !busyOverride;
    return {
      canInstall: bool("can_install", false),
      canStart: bool("can_start", false),
      canStop: bool("can_stop", false),
      canRestart: bool("can_restart", false),
      canEnsureReady: bool("can_ensure_ready", false),
      canHealth: bool("can_check_health", opts.managerEnabled),
      canJobs: bool("can_jobs", opts.managerEnabled),
      canLogs: bool("can_logs", opts.managerEnabled),
      canCapabilities: bool("can_capabilities", opts.managerEnabled),
      canVersions: bool("can_versions", opts.managerEnabled),
      canCheckUpdate: bool("can_check_update", opts.managerEnabled),
      canInstallVersion: bool("can_install_version", false),
      canActivateVersion: canActivate,
      canRollback: bool("can_rollback", false),
      canExecute: bool("can_execute", false),
      installReason: reason("can_install"),
      startReason: reason("can_start"),
      stopReason: reason("can_stop"),
      restartReason: reason("can_restart"),
      ensureReadyReason: reason("can_ensure_ready"),
      executeReason: reason("can_execute"),
      activateReason: !opts.hasVersionId
        ? "version_id is required to activate"
        : reason("can_activate_version"),
      healthReason: reason("can_check_health"),
      checkUpdateReason: reason("can_check_update"),
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
  const freshness = String(row.health_freshness ?? "").toUpperCase();
  if (freshness === "STALE") {
    return { label: "STALE", tone: "warn", detail: "Cached health is stale — refresh with Health" };
  }
  if (freshness === "UNMEASURED" && !row.health) {
    return { label: "UNMEASURED", tone: "muted", detail: "Health not measured" };
  }
  const hs =
    row.health && typeof row.health === "object"
      ? statusUpper(String((row.health as Record<string, unknown>).status ?? ""))
      : "";
  const s = hs || statusUpper(row.status);
  if (!s) return { label: "UNMEASURED", tone: "muted", detail: "Health not measured" };
  if (s === "STALE") {
    return { label: "STALE", tone: "warn", detail: "Cached health is stale — refresh with Health" };
  }
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
  if (m.kind === "not_available") return "—";
  if (m.kind === "unmeasured") return "Partieel";
  return fallback;
}

export function installActionText(
  action: "install" | "install-version",
  response: { status?: unknown; job_id?: unknown; result?: unknown } | null | undefined,
): string {
  const status = String(response?.status ?? "").toUpperCase();
  if (status === "APPROVAL_REQUIRED") {
    return "Approval required — review the install plan";
  }
  const inFlight = status === "QUEUED" || status === "RUNNING" || status === "CREATED" || status === "RETRY_WAIT";
  const jobWithoutResult =
    Boolean(response?.job_id) &&
    response?.result == null &&
    status !== "COMPLETED" &&
    status !== "INSTALLED" &&
    status !== "READY";
  const queued = inFlight || jobWithoutResult;
  if (queued) {
    return action === "install" ? "Install queued" : "Version install queued";
  }
  if (status === "READY" || status === "INSTALLED" || status === "COMPLETED") {
    return action === "install" ? "Installed successfully" : "Version installed";
  }
  if (response?.result != null) {
    return action === "install" ? "Installed successfully" : "Version installed";
  }
  return action === "install" ? "Install response received" : "Version install response received";
}

export type InstallObservationRow = {
  dependencyId: string;
  state: string;
  detail: string | null;
  packages: string[];
  packageManager: string | null;
};

export type InstallPlanView = {
  moduleId: string;
  requestedRef: string;
  strategies: string[];
  packageManager: string | null;
  privilegeState: string | null;
  requiresApproval: boolean;
  installable: boolean;
  planHash: string;
  missingDependencies: string[];
  observations: InstallObservationRow[];
  privilegedMutations: Array<Record<string, unknown>>;
  applicationActions: Array<Record<string, unknown>>;
  blockers: Array<Record<string, unknown>>;
  source: Record<string, unknown>;
};

export type InstallOperationView = {
  operationId: string | null;
  status: string;
  phase: string | null;
  progress: number | null;
  jobId: string | null;
  approvalId: string | null;
  planHash: string | null;
  errorCode: string | null;
  errorDetail: string | null;
  retryable: boolean;
  plan: InstallPlanView | null;
};

const INSTALL_PHASE_ORDER = [
  "PLANNING",
  "APPROVAL_REQUIRED",
  "QUEUED",
  "PREPARING",
  "INSTALLING_SYSTEM_DEPENDENCIES",
  "VERIFYING_SYSTEM_DEPENDENCIES",
  "FETCHING_SOURCE",
  "PREPARING_RUNTIME",
  "INSTALLING_APPLICATION_DEPENDENCIES",
  "POST_INSTALL",
  "VERIFYING_INSTALLATION",
  "ACTIVATING",
  "READY",
] as const;

export function parseInstallPlan(raw: unknown): InstallPlanView | null {
  if (!raw || typeof raw !== "object") return null;
  const p = raw as Record<string, unknown>;
  const observationsRaw = Array.isArray(p.observations) ? p.observations : [];
  const observations: InstallObservationRow[] = observationsRaw
    .filter((o): o is Record<string, unknown> => !!o && typeof o === "object")
    .map((o) => ({
      dependencyId: String(o.dependency_id ?? ""),
      state: String(o.state ?? "UNMEASURED"),
      detail: o.detail == null ? null : String(o.detail),
      packages: Array.isArray(o.install_packages) ? o.install_packages.map(String) : [],
      packageManager: o.package_manager == null ? null : String(o.package_manager),
    }))
    .filter((o) => o.dependencyId);
  return {
    moduleId: String(p.module_id ?? ""),
    requestedRef: String(p.requested_ref ?? "main"),
    strategies: Array.isArray(p.strategies) ? p.strategies.map(String) : [],
    packageManager: p.package_manager == null ? null : String(p.package_manager),
    privilegeState: p.privilege_state == null ? null : String(p.privilege_state),
    requiresApproval: Boolean(p.requires_approval),
    installable: p.installable !== false,
    planHash: String(p.plan_hash ?? ""),
    missingDependencies: Array.isArray(p.missing_dependencies) ? p.missing_dependencies.map(String) : [],
    observations,
    privilegedMutations: Array.isArray(p.privileged_mutations)
      ? (p.privileged_mutations as Array<Record<string, unknown>>)
      : [],
    applicationActions: Array.isArray(p.application_actions)
      ? (p.application_actions as Array<Record<string, unknown>>)
      : [],
    blockers: Array.isArray(p.blockers) ? (p.blockers as Array<Record<string, unknown>>) : [],
    source: p.source && typeof p.source === "object" ? (p.source as Record<string, unknown>) : {},
  };
}

export function parseInstallOperation(raw: unknown): InstallOperationView | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const planRaw = r.plan && typeof r.plan === "object" ? r.plan : null;
  const status = String(r.status ?? "").toUpperCase();
  return {
    operationId: r.operation_id == null ? null : String(r.operation_id),
    status,
    phase: r.phase == null ? null : String(r.phase).toUpperCase(),
    progress: typeof r.progress === "number" ? r.progress : null,
    jobId: r.job_id == null ? null : String(r.job_id),
    approvalId:
      r.approval_id == null
        ? r.approval && typeof r.approval === "object"
          ? String((r.approval as Record<string, unknown>).approval_id ?? "") || null
          : null
        : String(r.approval_id),
    planHash: r.plan_hash == null ? (planRaw ? String((planRaw as Record<string, unknown>).plan_hash ?? "") : null) : String(r.plan_hash),
    errorCode: r.error_code == null ? null : String(r.error_code),
    errorDetail: r.error_detail == null ? (r.detail == null ? null : String(r.detail)) : String(r.error_detail),
    retryable: Boolean(r.retryable),
    plan: parseInstallPlan(planRaw ?? r),
  };
}

export function dependencyStateLabel(state: string): string {
  const s = state.toUpperCase();
  if (s === "SATISFIED") return "INSTALLED";
  if (s === "MISSING_INSTALLABLE") return "MISSING — WILL INSTALL";
  if (s === "MISSING_UNSUPPORTED") return "MISSING — UNSUPPORTED";
  if (s === "VERSION_MISMATCH_INSTALLABLE") return "VERSION MISMATCH";
  if (s === "VERSION_MISMATCH_UNSUPPORTED") return "VERSION MISMATCH";
  if (s === "BLOCKED_PRIVILEGE") return "PRIVILEGE REQUIRED";
  if (s === "UNMEASURED") return "UNMEASURED";
  return s || "UNMEASURED";
}

export function dependencyStateTone(state: string): StatusTone {
  const s = state.toUpperCase();
  if (s === "SATISFIED") return "ok";
  if (s === "MISSING_INSTALLABLE") return "warn";
  if (s === "BLOCKED_PRIVILEGE" || s === "MISSING_UNSUPPORTED") return "err";
  return "muted";
}

export function installPhaseSteps(currentPhase: string | null): Array<{ id: string; label: string; state: "done" | "active" | "pending" | "failed" }> {
  const phase = (currentPhase || "").toUpperCase();
  if (phase === "FAILED" || phase === "CANCELLED") {
    return INSTALL_PHASE_ORDER.map((id) => ({
      id,
      label: id.replaceAll("_", " "),
      state: "pending" as const,
    }));
  }
  const idx = INSTALL_PHASE_ORDER.indexOf(phase as (typeof INSTALL_PHASE_ORDER)[number]);
  return INSTALL_PHASE_ORDER.map((id, i) => {
    let state: "done" | "active" | "pending" = "pending";
    if (idx < 0) state = "pending";
    else if (i < idx) state = "done";
    else if (i === idx) state = phase === "READY" ? "done" : "active";
    return { id, label: id.replaceAll("_", " "), state };
  });
}

export function primaryInstallCta(plan: InstallPlanView | null, status: string | null): string {
  const s = (status || "").toUpperCase();
  if (s === "FAILED") return "RETRY INSTALL";
  if (s === "QUEUED" || s === "RUNNING" || s === "CREATED" || s === "RETRY_WAIT") return "INSTALL IN PROGRESS";
  if (s === "READY" || s === "INSTALLED" || s === "COMPLETED") return "INSTALLED";
  if (!plan) return "INSTALL";
  if (plan.requiresApproval || s === "APPROVAL_REQUIRED") return "APPROVE & INSTALL EVERYTHING";
  return "INSTALL EVERYTHING";
}

export function lifecycleFailureText(action: string, detail: string): string {
  const label =
    action === "install" ? "Install failed" : action === "install-version" ? "Version install failed" : "";
  const body = detail.trim();
  if (!label) return body || "Request failed";
  if (!body) return label;
  if (body.toLowerCase().startsWith(label.toLowerCase())) return body;
  return `${label} — ${body}`;
}

export function lifecycleBadges(row: ManagedModuleRow): { label: string; tone: StatusTone }[] {
  const badges: { label: string; tone: StatusTone }[] = [];
  const s = statusUpper(row.status);
  const failed = s === "FAILED" || s === "ERROR";
  if (!failed && (s === "DISCOVERED" || s === "NOT_INSTALLED" || (!isInstalled(row) && !s))) {
    badges.push({ label: s === "NOT_INSTALLED" ? "NOT INSTALLED" : "DISCOVERED", tone: "cyan" });
  } else if (s && s !== "INSTALLED") {
    // Prefer live lifecycle status (READY/RUNNING/DEGRADED/…) over a redundant INSTALLED chip.
    badges.push({ label: s === "NOT_INSTALLED" ? "NOT INSTALLED" : s, tone: statusTone(s) });
  } else if (isInstalled(row)) {
    badges.push({ label: "INSTALLED", tone: "ok" });
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
