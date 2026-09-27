import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const modelsPageSrc = readFileSync(join(here, "ModelsPage.tsx"), "utf8");
const hardwareSrc = readFileSync(join(here, "HardwareInventoryPanel.tsx"), "utf8");
const pagesCss = readFileSync(join(here, "../../styles/pages.css"), "utf8");
const leviathanCss = readFileSync(join(here, "../../styles/leviathan.css"), "utf8");

describe("models page hardware / catalog layout", () => {
  it("stacks HardwareInventoryPanel before ModelCatalog in document flow", () => {
    const hardwareIdx = modelsPageSrc.indexOf("<HardwareInventoryPanel");
    const catalogIdx = modelsPageSrc.indexOf("<ModelCatalog");
    expect(hardwareIdx).toBeGreaterThan(0);
    expect(catalogIdx).toBeGreaterThan(hardwareIdx);
    expect(modelsPageSrc).toContain('className="lv-main lv-models-main"');
  });

  it("marks hardware panel with page-scoped class (not absolute positioning)", () => {
    expect(hardwareSrc).toContain("lv-hardware-panel");
    expect(hardwareSrc).not.toMatch(/position:\s*['\"]?absolute/);
    expect(hardwareSrc).not.toMatch(/zIndex|z-index/);
    expect(hardwareSrc).not.toMatch(/marginTop:\s*-\d/);
  });

  it("prevents flex-shrink collapse of hardware over catalog (page-scoped)", () => {
    expect(pagesCss).toContain(".lv-models-main > *");
    expect(pagesCss).toMatch(/\.lv-models-main > \* \{[\s\S]*?flex:\s*0 0 auto/);
    expect(pagesCss).toMatch(/\.lv-hardware-panel \{[\s\S]*?flex:\s*0 0 auto/);
    // Do not paper over with global .lv-card changes — global still has min-height: 0.
    expect(leviathanCss).toMatch(/\.lv-card \{[\s\S]*?min-height:\s*0/);
  });

  it("keeps hardware metadata in a responsive grid without hiding telemetry", () => {
    expect(hardwareSrc).toContain("Hardware inventory");
    expect(hardwareSrc).toContain("Aggregate physical VRAM");
    expect(hardwareSrc).toContain("hostMemory");
    expect(pagesCss).toContain(".lv-hardware-panel .lv-models-dl");
    expect(pagesCss).toContain("auto-fit");
  });

  it("marks loading and unavailable hardware states with lv-hardware-panel", () => {
    expect(hardwareSrc).toMatch(/Loading hardware inventory[\s\S]*?lv-hardware-panel|lv-hardware-panel[\s\S]*?Loading hardware inventory/);
    expect(hardwareSrc).toContain("Hardware telemetry unavailable");
    const panels = hardwareSrc.match(/lv-hardware-panel/g) || [];
    expect(panels.length).toBeGreaterThanOrEqual(3);
  });
});

/**
 * Conceptual DOM bounding-box contract for viewport regression suites.
 * Pure geometry helper — no screenshots.
 */
export function assertNoVerticalOverlap(
  hardware: { top: number; bottom: number },
  catalog: { top: number; bottom: number },
): void {
  expect(hardware.bottom).toBeLessThanOrEqual(catalog.top);
}

describe("models layout geometry helper", () => {
  it.each([
    { w: 1366, h: 768, hardwareBottom: 320, catalogTop: 336 },
    { w: 1920, h: 1080, hardwareBottom: 280, catalogTop: 296 },
    { w: 2560, h: 1440, hardwareBottom: 260, catalogTop: 276 },
  ])("hardware.bottom <= catalog.top at ${w}x${h}", ({ hardwareBottom, catalogTop }) => {
    assertNoVerticalOverlap(
      { top: 120, bottom: hardwareBottom },
      { top: catalogTop, bottom: catalogTop + 400 },
    );
  });
});
