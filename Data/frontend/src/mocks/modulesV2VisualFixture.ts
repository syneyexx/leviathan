/**
 * TEST-ONLY Screen 1 Modules visual fixture.
 * Activated solely when window.__LV_V2_VISUAL_FIXTURE__ === 'modules'.
 * Never imported by production page defaults — useModulesWorkspace applies it
 * only behind that flag (Playwright / visual regression).
 */

export const MODULES_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26.000Z";

function mod(
  id: string,
  name: string,
  status: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const version =
    id === "fincept-terminal" ? "0.2.0" : typeof overrides.version === "string" ? overrides.version : "1.0.0";
  return {
    manifest: {
      module_id: id,
      name,
      version,
      isolation: "SUBPROCESS",
      source_path: `/opt/leviathan/modules/${id}`,
      capabilities: [
        {
          capability_id: `${id}.analyze`,
          name: "analyze",
          description: "Analyze",
          side_effects: ["READ", "NETWORK"],
        },
        {
          capability_id: `${id}.quant`,
          name: "quant",
          description: "Quant",
          side_effects: ["READ", "NETWORK"],
        },
        {
          capability_id: `${id}.stats`,
          name: "stats",
          description: "Stats",
          side_effects: ["READ"],
        },
        {
          capability_id: `${id}.fixed_income`,
          name: "fixed_income",
          description: "Fixed income",
          side_effects: ["READ", "NETWORK"],
        },
      ],
      metadata: {
        description:
          id === "fincept-terminal"
            ? "Institutional terminal analytics for markets, fixed income and quant research."
            : `${name} capability module`,
        tags: id.includes("fincept") ? ["analytics", "finance"] : ["runtime"],
        external: {
          adapter: overrides.adapter ?? "COMPOSITE",
          source: { type: "git", ref: "main" },
          resource_class: overrides.resource_class ?? "CPU_HEAVY",
          install: {
            strategies: ["GIT_CHECKOUT", "PYTHON_VENV"],
            dependencies: ["numpy", "pandas", "scipy", "statsmodels"],
          },
          runtime: {
            timeout_s: 300,
            working_directory:
              id === "fincept-terminal"
                ? "$INSTALL_ROOT/fincept-qt/scripts/Analytics"
                : `$INSTALL_ROOT/modules/${id}`,
            operations: [
              { name: "analyze", side_effects: ["READ", "NETWORK"] },
              { name: "quant", side_effects: ["READ", "NETWORK"] },
              { name: "stats", side_effects: ["READ"] },
              { name: "fixed_income", side_effects: ["READ", "NETWORK"] },
            ],
          },
        },
      },
    },
    status,
    runtime_state: status,
    desired_state: status === "DISCOVERED" || status === "NOT_INSTALLED" ? "STOPPED" : "ACTIVE",
    adapter: overrides.adapter ?? "COMPOSITE",
    active_jobs: id === "fincept-terminal" ? ["job-ft-1", "job-ft-2"] : status === "RUNNING" ? ["job-demo"] : [],
    health:
      status === "DEGRADED"
        ? { status: "DEGRADED", detail: "partial", checked_at: MODULES_V2_VISUAL_FROZEN_ISO, response_time_ms: 890, uptime: 92.1 }
        : status === "READY" || status === "RUNNING"
          ? {
              status: "READY",
              detail: "ok",
              checked_at: MODULES_V2_VISUAL_FROZEN_ISO,
              response_time_ms: 245,
              uptime: 99.7,
              active_jobs: id === "fincept-terminal" ? 2 : 0,
            }
          : null,
    health_freshness: status === "READY" || status === "RUNNING" || status === "DEGRADED" ? "FRESH" : "UNMEASURED",
    source_type: "git",
    source_ref: "main",
    resource_class: overrides.resource_class ?? "CPU_HEAVY",
    isolation: "SUBPROCESS",
    declared_side_effects: ["READ", "NETWORK"],
    allowed_actions: {
      can_install: status === "DISCOVERED" || status === "NOT_INSTALLED" || status === "FAILED",
      can_start: true,
      can_stop: status === "READY" || status === "RUNNING",
      can_restart: true,
      can_ensure_ready: true,
      can_execute: status === "READY" || status === "RUNNING",
      can_check_health: true,
      can_check_update: true,
      can_install_version: true,
      can_activate_version: true,
      can_rollback: true,
      can_jobs: true,
      can_logs: true,
      can_capabilities: true,
      can_versions: true,
    },
    blocked_reasons: {},
    update_evidence: overrides.update_available
      ? { update_available: true, checked_at: MODULES_V2_VISUAL_FROZEN_ISO }
      : { update_available: false, checked_at: MODULES_V2_VISUAL_FROZEN_ISO },
    truth: {
      snapshot_health_is_cached_not_live: true,
      discoverable_is_not_authorized: true,
    },
    ...overrides,
  };
}

/**
 * Screen 1 KPI strip targets (18 / 8 / 12 / 2 / 3).
 * installed=8 and executable=12 are not simultaneously derivable from
 * current isInstalled∩isExecutable sets — visual regression uses these
 * display overrides while the module list remains a truthful snapshot shape.
 */
export const MODULES_V2_VISUAL_DISPLAY_KPIS = {
  featureFlag: "ON" as const,
  totalModules: 18,
  executable: 12,
  healthIssues: 2,
  updateAvailable: { kind: "measured" as const, value: 3 },
  installedCount: 8,
  filterCounts: {
    all: 18,
    installed: 8,
    not_installed: 6,
    updates: 3,
  },
};

export const MODULES_V2_VISUAL_SPARKLINES = {
  total: [4, 6, 5, 8, 7, 9, 10, 12],
  executable: [3, 4, 5, 6, 7, 8, 10, 12],
  health: [0, 1, 1, 2, 1, 2, 2, 2],
  updates: [1, 1, 2, 2, 2, 3, 3, 3],
};

/** Fixture payload: ModuleSnapshot fields + activity for the detail feed. */
export const MODULES_V2_VISUAL_FIXTURE = {
  enabled: true,
  modules: [
    mod("fincept-terminal", "Fincept Terminal Analytics", "READY", { adapter: "COMPOSITE", update_available: true }),
    mod("desktop-commander", "Desktop Commander MCP", "RUNNING", { adapter: "MCP" }),
    mod("llm-agent-trader", "LLM Agent Trader", "READY", { adapter: "CLI" }),
    mod("financial-services", "Financial Services", "DISCOVERED", { adapter: "HTTP_OPENAPI" }),
    mod("claude-osint", "Claude OSINT", "DEGRADED", { adapter: "CLI", update_available: true }),
    mod("ghosttrack", "GhostTrack", "READY", { adapter: "SCRIPT_PACKAGE" }),
    mod("anthropic-skills", "Anthropic Skills", "NOT_INSTALLED", { adapter: "SKILL_PACK" }),
    mod("agent-reach", "Agent Reach", "READY", { adapter: "PROCESS_SERVICE" }),
    mod("mod-09", "Market Pulse", "READY"),
    mod("mod-10", "News Digest", "INSTALLED"),
    mod("mod-11", "Risk Scanner", "READY", { update_available: true }),
    mod("mod-12", "Broker Bridge", "DISCOVERED"),
    mod("mod-13", "Corpus Loader", "READY"),
    mod("mod-14", "Signal Fabric Hook", "STOPPED"),
    mod("mod-15", "Eval Harness Kit", "DISCOVERED"),
    mod("mod-16", "Dataset Linker", "READY"),
    mod("mod-17", "Voice Tools Pack", "DISCOVERED"),
    mod("mod-18", "Sandbox Tools", "FAILED"),
  ],
  telemetry: {},
  discovery_roots: ["/opt/leviathan/modules", "/var/lib/leviathan/external-modules"],
  truth: {
    module_manager_is_not_execution_gateway: true,
    snapshot_health_is_cached_not_live: true,
    allowed_actions_are_server_projected: true,
  },
  activity: [
    {
      event_id: "a1",
      label: "Module started",
      status: "OK",
      created_at_ms: Date.parse(MODULES_V2_VISUAL_FROZEN_ISO) - 14_000,
    },
    {
      event_id: "a2",
      label: "Health checked",
      status: "OK",
      created_at_ms: Date.parse(MODULES_V2_VISUAL_FROZEN_ISO) - 28_000,
    },
    {
      event_id: "a3",
      label: "Ensure ready completed",
      status: "OK",
      created_at_ms: Date.parse(MODULES_V2_VISUAL_FROZEN_ISO) - 106_000,
    },
    {
      event_id: "a4",
      label: "Jobs refreshed",
      status: "OK",
      created_at_ms: Date.parse(MODULES_V2_VISUAL_FROZEN_ISO) - 204_000,
    },
    {
      event_id: "a5",
      label: "Update check completed",
      status: "OK",
      created_at_ms: Date.parse(MODULES_V2_VISUAL_FROZEN_ISO) - 300_000,
    },
  ],
  selectedModuleId: "fincept-terminal",
  displayKpis: MODULES_V2_VISUAL_DISPLAY_KPIS,
  sparklines: MODULES_V2_VISUAL_SPARKLINES,
} as const;

export function isModulesVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  const flag = (window as Window & { __LV_V2_VISUAL_FIXTURE__?: unknown }).__LV_V2_VISUAL_FIXTURE__;
  return flag === "modules";
}
