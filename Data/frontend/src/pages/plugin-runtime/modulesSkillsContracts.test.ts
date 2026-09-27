import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const modulesSrc = readFileSync(join(here, "ModulesPage.tsx"), "utf8");
const hookSrc = readFileSync(join(here, "modules", "useModulesWorkspace.ts"), "utf8");
const viewSrc = readFileSync(join(here, "modules", "viewModels.ts"), "utf8");
const skillsSrc = readFileSync(join(here, "SkillsPage.tsx"), "utf8");
const chatSrc = readFileSync(join(here, "..", "ChatPage.tsx"), "utf8");
const combined = `${modulesSrc}\n${hookSrc}\n${viewSrc}`;

describe("ModulesPage external fabric lifecycle", () => {
  it("wires Sweep Idle to api.sweepIdleModules", () => {
    expect(hookSrc).toContain("sweepIdleModules");
    expect(modulesSrc).toContain("Sweep Idle");
    expect(hookSrc).toContain('"sweep-idle"');
    expect(modulesSrc).toContain("/api/modules/sweep-idle");
  });

  it("exposes install/start/stop/restart/ensure-ready without inventing runtime truth", () => {
    expect(hookSrc).toContain("installModule");
    expect(hookSrc).toContain("startModule");
    expect(hookSrc).toContain("stopModule");
    expect(hookSrc).toContain("restartModule");
    expect(hookSrc).toContain("ensureReadyModule");
    expect(combined).not.toMatch(/status:\s*[\"']RUNNING[\"']/);
  });

  it("wires versions/logs/jobs lifecycle actions to api clients", () => {
    expect(hookSrc).toContain("moduleVersions");
    expect(hookSrc).toContain("moduleCheckUpdate");
    expect(hookSrc).toContain("installModuleVersion");
    expect(hookSrc).toContain("activateModuleVersion");
    expect(hookSrc).toContain("rollbackModuleVersion");
    expect(hookSrc).toContain("moduleLogs");
    expect(hookSrc).toContain("moduleJobs");
    expect(hookSrc).toContain('"versions"');
    expect(hookSrc).toContain('"check-update"');
    expect(hookSrc).toContain('"install-version"');
    expect(hookSrc).toContain('"activate-version"');
    expect(hookSrc).toContain('"rollback"');
    expect(hookSrc).toContain('"jobs"');
  });

  it("keeps execute path and refuses fake update KPIs", () => {
    expect(hookSrc).toContain("executeModule");
    expect(viewSrc).toContain("not_checked");
    expect(viewSrc).toContain("UNMEASURED");
    expect(modulesSrc).toContain("NOT CHECKED");
    expect(modulesSrc).not.toContain("342 ms");
    expect(modulesSrc).not.toContain("48.2 MB");
  });

  it("imports dedicated modules page styles and real hero asset", () => {
    expect(modulesSrc).toContain("modules-page.css");
    expect(modulesSrc).toContain("pluginRuntimeHeroes.modules");
  });
});

describe("SkillsPage catalog bounds", () => {
  it("searches with limit/offset and loads instructions on demand", () => {
    expect(skillsSrc).toContain("listSkills");
    expect(skillsSrc).toMatch(/limit\s*=\s*40/);
    expect(skillsSrc).toContain("offset");
    expect(skillsSrc).toContain("include_catalog");
    expect(skillsSrc).toContain("getSkill");
    expect(skillsSrc).toMatch(/instructions load on demand/i);
  });
});

describe("ChatPage job SSE labels", () => {
  it("formats job.* events with shared JobRuntime helpers", () => {
    expect(chatSrc).toContain("formatJobStateLabel");
    expect(chatSrc).toContain("normalizeJobStatus");
    expect(chatSrc).toContain("job.");
    expect(chatSrc).toContain("onCapabilityEvent");
  });
});
