import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const modulesSrc = readFileSync(join(here, "ModulesPage.tsx"), "utf8");
const skillsSrc = readFileSync(join(here, "SkillsPage.tsx"), "utf8");
const chatSrc = readFileSync(join(here, "..", "ChatPage.tsx"), "utf8");

describe("ModulesPage external fabric lifecycle", () => {
  it("wires Sweep Idle to api.sweepIdleModules", () => {
    expect(modulesSrc).toContain("sweepIdleModules");
    expect(modulesSrc).toContain("Sweep Idle");
    expect(modulesSrc).toContain('"sweep-idle"');
    expect(modulesSrc).toContain("/api/modules/sweep-idle");
  });

  it("exposes install/start/stop/restart/ensure-ready without inventing runtime truth", () => {
    expect(modulesSrc).toContain("installModule");
    expect(modulesSrc).toContain("startModule");
    expect(modulesSrc).toContain("stopModule");
    expect(modulesSrc).toContain("restartModule");
    expect(modulesSrc).toContain("ensureReadyModule");
    expect(modulesSrc).not.toMatch(/status:\s*[\"']RUNNING[\"']/);
  });

  it("wires versions/logs/jobs lifecycle actions to api clients", () => {
    expect(modulesSrc).toContain("moduleVersions");
    expect(modulesSrc).toContain("moduleCheckUpdate");
    expect(modulesSrc).toContain("installModuleVersion");
    expect(modulesSrc).toContain("activateModuleVersion");
    expect(modulesSrc).toContain("rollbackModuleVersion");
    expect(modulesSrc).toContain("moduleLogs");
    expect(modulesSrc).toContain("moduleJobs");
    expect(modulesSrc).toContain('"versions"');
    expect(modulesSrc).toContain('"check-update"');
    expect(modulesSrc).toContain('"install-version"');
    expect(modulesSrc).toContain('"activate-version"');
    expect(modulesSrc).toContain('"rollback"');
    expect(modulesSrc).toContain('"jobs"');
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
