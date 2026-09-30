/**
 * Analytics page contracts — fixture isolation + nav label.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MAIN_MENU } from "../navigation/menu";
import { isAnalyticsVisualFixtureActive } from "../mocks/analyticsV2VisualFixture";

const here = dirname(fileURLToPath(import.meta.url));

describe("Analytics V2 contracts", () => {
  it("MAIN_MENU label is Statistieken under LLM", () => {
    const llm = MAIN_MENU.find((m) => m.id === "llm");
    expect(llm).toBeTruthy();
    const stats = llm?.submenu.find((s) => s.to === "/analytics");
    expect(stats?.label).toBe("Statistieken");
    expect(stats?.label).not.toBe("Statestieken");
  });

  it("visual fixture gate is inactive in default runtime", () => {
    expect(isAnalyticsVisualFixtureActive()).toBe(false);
  });

  it("AnalyticsPage does not import fixture as production fallback", () => {
    const src = readFileSync(join(here, "AnalyticsPage.tsx"), "utf8");
    expect(src).toContain('variant="v2"');
    expect(src).toContain("LLM / Statistieken");
    expect(src).not.toMatch(/catch[\s\S]*ANALYTICS_V2_VISUAL_FIXTURE/);
  });

  it("workspace only activates fixture behind explicit flag", () => {
    const src = readFileSync(join(here, "analytics/useAnalyticsWorkspace.ts"), "utf8");
    expect(src).toContain("isAnalyticsVisualFixtureActive");
    expect(src).toContain("ANALYTICS_V2_VISUAL_FIXTURE");
    expect(src).toMatch(/lastGoodRef/);
    expect(src).not.toMatch(/catch[\s\S]{0,80}ANALYTICS_V2_VISUAL_FIXTURE/);
  });
});
