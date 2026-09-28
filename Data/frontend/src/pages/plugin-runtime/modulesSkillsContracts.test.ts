import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const modulesSrc = readFileSync(join(here, "ModulesPage.tsx"), "utf8");
const skillsEntry = readFileSync(join(here, "SkillsPage.tsx"), "utf8");
const skillsPage = readFileSync(join(here, "skills/SkillsPage.tsx"), "utf8");
const skillsHook = readFileSync(join(here, "skills/hooks/useSkillsPage.ts"), "utf8");
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
  it("re-exports the rebuilt Skills page module", () => {
    expect(skillsEntry).toContain('from "./skills/SkillsPage"');
  });

  it("searches with limit/offset and loads instructions on demand", () => {
    expect(skillsHook).toContain("listSkills");
    expect(skillsHook).toMatch(/PAGE_LIMIT\s*=\s*40/);
    expect(skillsHook).toContain("offset");
    expect(skillsHook).toContain("include_catalog");
    expect(skillsHook).toContain("getSkill");
    expect(skillsHook).toContain("classification");
    expect(skillsPage).toMatch(/Load Instructions|loadInstructions/);
    expect(skillsPage + skillsHook).toMatch(/on demand|Load Instructions/i);
  });

  it("wires enable/disable/test without fabricating screenshot metrics", () => {
    expect(skillsHook).toContain("setSkillEnabled");
    expect(skillsHook).toContain("testSkill");
    expect(skillsHook).toContain("executeSkill");
    expect(skillsPage).not.toMatch(/128 Total Skills/);
    expect(skillsPage).not.toMatch(/Research Synthesis/);
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
