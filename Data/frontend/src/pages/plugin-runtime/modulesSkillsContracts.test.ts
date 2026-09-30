import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const modulesSrc = readFileSync(join(here, "ModulesPage.tsx"), "utf8");
const hookSrc = readFileSync(join(here, "modules", "useModulesWorkspace.ts"), "utf8");
const viewSrc = readFileSync(join(here, "modules", "viewModels.ts"), "utf8");
const heroSrc = readFileSync(join(here, "../../components/modules/ModulesHero.tsx"), "utf8");
const installPanelSrc = readFileSync(join(here, "../../components/modules/ModulesInstallPanel.tsx"), "utf8");
const metricsSrc = readFileSync(join(here, "../../components/modules/ModulesMetrics.tsx"), "utf8");
const skillsEntry = readFileSync(join(here, "SkillsPage.tsx"), "utf8");
const skillsPage = readFileSync(join(here, "skills/SkillsPage.tsx"), "utf8");
const skillsHook = readFileSync(join(here, "skills/hooks/useSkillsPage.ts"), "utf8");
const chatSrc = readFileSync(join(here, "..", "ChatPage.tsx"), "utf8");
const combined = `${modulesSrc}\n${hookSrc}\n${viewSrc}\n${installPanelSrc}\n${metricsSrc}`;

describe("ModulesPage V2 external fabric lifecycle", () => {
  it("wires Sweep Idle to api.sweepIdleModules via workspace hook", () => {
    expect(hookSrc).toContain("sweepIdleModules");
    expect(hookSrc).toContain('"sweep-idle"');
    expect(modulesSrc).toContain("onSweepIdle");
    expect(modulesSrc).toContain("sweep-idle");
  });

  it("does not treat a queued install as a completed install", () => {
    expect(viewSrc).toContain("Install queued");
    expect(viewSrc).toContain("Version install queued");
    expect(viewSrc).toContain("Approval required");
    expect(hookSrc).toContain("installActionText");
    expect(hookSrc).toContain("lifecycleFailureText");
    expect(hookSrc).toContain("awaitJob");
    expect(hookSrc).toContain("getJob");
    expect(hookSrc).toContain("isTerminalJobStatus");
  });

  it("wires dependency-aware install plan and approve-everything CTA", () => {
    expect(hookSrc).toContain("approveAndInstallEverything");
    expect(hookSrc).toContain("moduleInstallState");
    expect(hookSrc).toContain("approveApproval");
    expect(hookSrc).toContain("plan_hash");
    expect(hookSrc).toContain("approval_id");
    expect(hookSrc).toContain("primaryInstallCta");
    expect(modulesSrc).toContain("ModulesInstallPanel");
    expect(modulesSrc).toContain("primaryInstallCta");
    expect(installPanelSrc).toContain("Install plan");
    expect(viewSrc).toContain("parseInstallPlan");
    expect(viewSrc).toContain("APPROVE & INSTALL EVERYTHING");
    expect(viewSrc).toContain("MISSING — WILL INSTALL");
    expect(viewSrc).toContain("RETRY INSTALL");
    expect(combined).not.toMatch(/Magic install failed/);
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
    expect(viewSrc).toContain("NOT CHECKED");
    expect(modulesSrc).not.toContain("342 ms");
    expect(modulesSrc).not.toContain("48.2 MB");
  });

  it("uses global V2 shell and shared styles — no legacy modules-page.css", () => {
    expect(modulesSrc).not.toContain("modules-page.css");
    expect(modulesSrc).toContain('variant="v2"');
    expect(modulesSrc).toContain("lv-v2-page--modules");
    expect(modulesSrc).toContain("Runtime & Tools / Modules");
    expect(heroSrc).toContain("pluginRuntimeHeroes.modules");
  });

  it("exposes Runtimes/Installation/Environments URL projections", () => {
    expect(hookSrc).toContain('viewParam === "runtimes"');
    expect(hookSrc).toContain('viewParam === "installation"');
    expect(hookSrc).toContain('viewParam === "environments"');
    expect(modulesSrc).toContain("ModulesProjectionViews");
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
