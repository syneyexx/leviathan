import { describe, expect, it } from "vitest";
import { detailMessage } from "../../../api/http";
import {
  actionAvailability,
  deriveKpis,
  filterCounts,
  filterModules,
  formatMeasured,
  healthLabel,
  installActionText,
  isExecutable,
  isInstalled,
  lifecycleBadges,
  lifecycleFailureText,
  moduleId,
  parseCapabilities,
  redactSecrets,
  safeConfiguration,
  statusTone,
  tryParseArgs,
  updateAvailableFromEvidence,
  type ManagedModuleRow,
} from "./viewModels";

function row(partial: Partial<ManagedModuleRow> & { id?: string }): ManagedModuleRow {
  const id = partial.id ?? "mod-a";
  return {
    manifest: {
      module_id: id,
      name: partial.manifest?.name ?? id,
      version: partial.manifest?.version ?? "1.0.0",
      capabilities: partial.manifest?.capabilities ?? [],
      source_path: partial.manifest?.source_path,
      metadata: partial.manifest?.metadata,
      ...partial.manifest,
    },
    status: partial.status ?? "DISCOVERED",
    runtime_state: partial.runtime_state,
    adapter: partial.adapter ?? "CLI",
    error: partial.error,
    health: partial.health,
    active_jobs: partial.active_jobs,
    last_result: partial.last_result,
    truth: partial.truth,
  };
}

describe("Modules view models", () => {
  it("maps status tones without inventing READY", () => {
    expect(statusTone("READY")).toBe("ok");
    expect(statusTone("DISCOVERED")).toBe("cyan");
    expect(statusTone("ERROR")).toBe("err");
    expect(statusTone("DEGRADED")).toBe("warn");
    expect(statusTone("BUSY")).toBe("gold");
  });

  it("derives KPIs from snapshot without fake update counts", () => {
    const modules = [
      row({ id: "a", status: "READY" }),
      row({ id: "b", status: "ERROR" }),
      row({ id: "c", status: "DISCOVERED", adapter: null }),
    ];
    const kpis = deriveKpis({ enabled: true, modules }, {});
    expect(kpis.featureFlag).toBe("ON");
    expect(kpis.totalModules).toBe(3);
    expect(kpis.executable).toBe(1);
    expect(kpis.healthIssues).toBe(1);
    expect(kpis.updateAvailable.kind).toBe("not_checked");
    expect(formatMeasured(kpis.updateAvailable)).toBe("NOT CHECKED");
  });

  it("does not invent KPIs when snapshot is missing", () => {
    const kpis = deriveKpis(null, {});
    expect(kpis.featureFlag).toBeNull();
    expect(kpis.totalModules).toBeNull();
    expect(kpis.updateAvailable.kind).toBe("not_available");
  });

  it("counts updates only after check-update evidence", () => {
    const modules = [row({ id: "a", status: "READY" }), row({ id: "b", status: "READY" })];
    const evidence = {
      a: { update_available: true },
      b: { update_available: false },
    };
    const kpis = deriveKpis({ enabled: true, modules }, evidence);
    expect(kpis.updateAvailable).toEqual({ kind: "measured", value: 1 });
    expect(filterCounts(modules, evidence).updates).toBe(1);
  });

  it("filters by search and installed/not-installed", () => {
    const modules = [
      row({ id: "feynman", status: "INSTALLED", manifest: { name: "Feynman Research", module_id: "feynman" } }),
      row({ id: "agent-reach", status: "DISCOVERED", manifest: { name: "Agent Reach", module_id: "agent-reach" } }),
    ];
    expect(filterModules(modules, "feyn", "all", {}).map(moduleId)).toEqual(["feynman"]);
    expect(filterModules(modules, "", "installed", {}).map(moduleId)).toEqual(["feynman"]);
    expect(filterModules(modules, "", "not_installed", {}).map(moduleId)).toEqual(["agent-reach"]);
  });

  it("enables lifecycle actions from real status", () => {
    const discovered = actionAvailability(row({ status: "DISCOVERED", adapter: "COMPOSITE" }), {
      managerEnabled: true,
      lifecycleBusy: false,
      hasVersionId: false,
    });
    expect(discovered.canInstall).toBe(true);
    expect(discovered.canExecute).toBe(false);
    expect(discovered.canActivateVersion).toBe(false);
    expect(discovered.activateReason).toMatch(/version_id/i);

    const ready = actionAvailability(row({ status: "READY", adapter: "CLI" }), {
      managerEnabled: true,
      lifecycleBusy: false,
      hasVersionId: true,
    });
    expect(ready.canExecute).toBe(true);
    expect(ready.canStop).toBe(true);
    expect(ready.canEnsureReady).toBe(true);
    expect(ready.canActivateVersion).toBe(true);
  });

  it("validates execute JSON arguments", () => {
    expect(tryParseArgs("{}").ok).toBe(true);
    expect(tryParseArgs('{"q":1}')).toEqual({ ok: true, value: { q: 1 } });
    expect(tryParseArgs("[1]").ok).toBe(false);
    expect(tryParseArgs("{").ok).toBe(false);
  });

  it("redacts secrets from configuration", () => {
    const cfg = safeConfiguration(
      row({
        id: "x",
        status: "READY",
        manifest: {
          module_id: "x",
          name: "X",
          metadata: { external: { api_key: "secret", runtime: { command: ["echo"] } } },
        },
      }),
    );
    expect((cfg.external as Record<string, unknown>).api_key).toBe("[REDACTED]");
    expect(((cfg.external as Record<string, unknown>).runtime as Record<string, unknown>).command).toEqual(["echo"]);
    expect(redactSecrets({ token: "abc", ok: 1 })).toEqual({ token: "[REDACTED]", ok: 1 });
  });

  it("parses capabilities and health labels truthfully", () => {
    const caps = parseCapabilities([
      { capability_id: "external.x.search", name: "Search", description: "Find", side_effects: ["READ"] },
    ]);
    expect(caps[0]?.capabilityId).toBe("external.x.search");
    expect(healthLabel(row({ status: "DISCOVERED" })).tone).toBe("cyan");
    expect(healthLabel(row({ status: "ERROR", error: "boom" })).label).toBe("Unhealthy");
    expect(isInstalled(row({ status: "READY" }))).toBe(true);
    expect(isExecutable(row({ status: "DISCOVERED" }))).toBe(false);
  });

  it("updateAvailableFromEvidence stays NOT CHECKED without evidence", () => {
    expect(updateAvailableFromEvidence(null).kind).toBe("not_checked");
    expect(updateAvailableFromEvidence({}).kind).toBe("not_checked");
    expect(updateAvailableFromEvidence({ update_available: true })).toEqual({ kind: "measured", value: true });
  });

  it("feature flag OFF derives OFF KPI", () => {
    const kpis = deriveKpis({ enabled: false, modules: [] }, {});
    expect(kpis.featureFlag).toBe("OFF");
    expect(kpis.totalModules).toBe(0);
  });

  it("does not present a queued install as installed", () => {
    expect(installActionText("install", { status: "QUEUED", job_id: "job-1" })).toBe("Install queued");
    expect(installActionText("install-version", { status: "QUEUED", job_id: "job-2" })).toBe(
      "Version install queued",
    );
    expect(installActionText("install", { result: { status: "INSTALLED" } })).toBe("Installed successfully");
    expect(installActionText("install-version", { result: { status: "INSTALLED" } })).toBe("Version installed");
  });

  it("surfaces backend lifecycle detail instead of a generic HTTP failure", () => {
    const message = detailMessage(
      {
        detail: {
          code: "DEPENDENCY_MISSING",
          message: "missing dependencies: curl",
          module_id: "ghosttrack",
          action: "install",
        },
      },
      424,
    );
    const text = lifecycleFailureText("install", message);
    expect(text).toBe("Install failed — DEPENDENCY_MISSING: missing dependencies: curl");
    expect(text).not.toContain("Request failed (500)");
    expect(lifecycleFailureText("install-version", message)).toBe(
      "Version install failed — DEPENDENCY_MISSING: missing dependencies: curl",
    );
  });

  it("shows FAILED instead of only DISCOVERED after an install failure", () => {
    const badges = lifecycleBadges(row({ status: "FAILED", error: "DEPENDENCY_MISSING: curl" }));
    expect(badges.map((badge) => badge.label)).toContain("FAILED");
    expect(badges.map((badge) => badge.label)).not.toContain("DISCOVERED");
  });
});
