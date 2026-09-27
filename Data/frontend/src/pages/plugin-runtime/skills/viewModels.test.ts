import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildActionModels,
  buildFilterChips,
  buildInfoFields,
  buildKpiModels,
  displayMetric,
  hasFakeScreenshotMetrics,
  skillCategoryLabel,
  skillStateLabel,
  UNMEASURED,
  type SkillRecord,
  type SkillTotals,
} from "./viewModels";

const sample: SkillRecord = {
  skill_id: "skill:demo:abc",
  name: "demo-scroll",
  description: "cinematic scroll builder",
  enabled: true,
  catalog_only: false,
  version: "0.1.0",
  module_id: "fake-cli",
  required_capabilities: ["external.fake_cli.search"],
  script_refs: [],
  resource_refs: [],
  imported_at: "2026-01-01T00:00:00+00:00",
  metadata: {},
};

describe("Skills view models", () => {
  it("builds truthful KPIs without inventing unmeasured values", () => {
    const totals: SkillTotals = {
      installed: 2,
      catalog: 5,
      total: 7,
      available: 1,
      external_packs: 3,
      tools: 1,
      issues: 0,
      agent_skills: null,
      updates_available: null,
      classifications: { all: 7, core: 2, external: 5, tools: 1, agent: null },
    };
    const kpis = buildKpiModels(totals);
    expect(kpis).toHaveLength(6);
    expect(kpis[0]?.value).toBe("7");
    expect(kpis[1]?.value).toBe("1");
    expect(kpis[3]?.value).toBe(UNMEASURED);
    expect(kpis[3]?.measured).toBe(false);
    expect(kpis[5]?.value).toBe(UNMEASURED);
  });

  it("exposes classification chips with agent unmeasured", () => {
    const chips = buildFilterChips({
      installed: 2,
      catalog: 4,
      classifications: { all: 6, core: 2, external: 4, tools: 1, agent: null },
    });
    expect(chips.find((c) => c.id === "agent")?.count).toBe(UNMEASURED);
    expect(chips.find((c) => c.id === "agent")?.enabled).toBe(false);
    expect(chips.find((c) => c.id === "core")?.count).toBe("2");
  });

  it("derives action enablement from real skill contracts", () => {
    const actions = buildActionModels(sample);
    expect(actions.find((a) => a.id === "execute")?.enabled).toBe(true);
    expect(actions.find((a) => a.id === "edit")?.enabled).toBe(false);
    expect(actions.find((a) => a.id === "clone")?.enabled).toBe(false);
    expect(actions.find((a) => a.id === "disable")?.enabled).toBe(true);
    expect(actions.find((a) => a.id === "test")?.enabled).toBe(true);

    const catalogOnly: SkillRecord = { ...sample, catalog_only: true, required_capabilities: [] };
    const catalogActions = buildActionModels(catalogOnly);
    expect(catalogActions.find((a) => a.id === "execute")?.enabled).toBe(false);
    expect(catalogActions.find((a) => a.id === "disable")?.enabled).toBe(false);

    const instructionOnly: SkillRecord = { ...sample, required_capabilities: [] };
    expect(buildActionModels(instructionOnly).find((a) => a.id === "execute")?.reason).toMatch(
      /Instruction-only/,
    );
  });

  it("renders UNMEASURED for missing telemetry fields", () => {
    const fields = buildInfoFields(sample);
    expect(fields.find((f) => f.label === "Author")?.value).toBe("—");
    expect(fields.find((f) => f.label === "Usage Count")?.value).toBe(UNMEASURED);
    expect(fields.find((f) => f.label === "Success Rate")?.value).toBe(UNMEASURED);
    expect(skillStateLabel(sample)).toBe("AVAILABLE");
    expect(skillCategoryLabel(sample)).toBe("CORE");
  });

  it("displayMetric distinguishes null from zero", () => {
    expect(displayMetric(0)).toBe("0");
    expect(displayMetric(null)).toBe(UNMEASURED);
    expect(displayMetric(undefined)).toBe(UNMEASURED);
  });
});

describe("Skills page anti-fabrication guards", () => {
  it("does not hardcode screenshot KPI literals", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const page = readFileSync(join(here, "SkillsPage.tsx"), "utf8");
    const hero = readFileSync(join(here, "components/SkillsHero.tsx"), "utf8");
    const hook = readFileSync(join(here, "hooks/useSkillsPage.ts"), "utf8");
    const combined = `${page}\n${hero}\n${hook}`;
    expect(hasFakeScreenshotMetrics(combined)).toBe(false);
    expect(hook).toMatch(/getSkill\([^,]+,\s*true\)/);
    expect(hook).toContain("listSkills");
    expect(hook).toContain("getSkill");
    expect(hook).toContain("setSkillEnabled");
    expect(hook).toContain("testSkill");
    expect(hook).toMatch(/limit\s*=\s*40|PAGE_LIMIT\s*=\s*40/);
    expect(hook).toContain("classification");
    // Instructions are not loaded in the list path.
    expect(hook).not.toMatch(/listSkills\([\s\S]*includeInstructions\s*:\s*true/);
    expect(hook).not.toMatch(/listSkills\([\s\S]*include_instructions\s*:\s*true/);
  });

  it("loads instructions only via getSkill(..., true)", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const hook = readFileSync(join(here, "hooks/useSkillsPage.ts"), "utf8");
    expect(hook).toMatch(/getSkill\([^,]+,\s*false\)/);
    expect(hook).toMatch(/getSkill\([^,]+,\s*true\)/);
  });
});
