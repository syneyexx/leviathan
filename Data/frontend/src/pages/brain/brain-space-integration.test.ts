import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "../..");

function read(rel: string): string {
  return readFileSync(resolve(root, rel), "utf8");
}

describe("Brain celestial Graph integration contracts", () => {
  const page = read("pages/BrainPage.tsx");
  const canvas = read("pages/brain/BrainSpaceCanvas.tsx");
  const space = read("pages/brain/brain-space.ts");
  const main = read("main.tsx");
  const css = read("styles/brain-space.css");

  it("defaults Graph content to Celestial without a Space top-level tab", () => {
    expect(page).toContain('useState<GraphPresentation>("celestial")');
    expect(page).toContain("BrainSpaceCanvas");
    expect(page).toContain("BrainGraphCanvas");
    expect(page).toContain("Celestial");
    expect(page).toContain("Technical");
    expect(page).not.toMatch(/setView\(["']Space["']\)/);
    expect(page).not.toMatch(/BrainView.*Space/);
    expect(page).not.toContain("BrainSpacePrototypeView");
    expect(page).not.toContain("createMockBrainData");
  });

  it("keeps left filters and Node Details ownership on BrainPage", () => {
    expect(page).toContain("lv-gv-filters");
    expect(page).toContain("Node Details");
    expect(page).toContain("visibleNodes");
    expect(page).toContain("visibleEdges");
    expect(page).toContain("setSelectedId");
    expect(page).toContain("Orbit Motion");
    expect(page).toContain('graphPresentation === "celestial" ? "Orbit Motion" : "Physics Layout"');
    // Technical mode still uses the engineering graph.
    expect(page).toContain("physicsLayout={orbitMotion}");
    // Celestial Pause and left Orbit Motion share orbitMotion — one owner.
    expect(page).toContain("paused={!orbitMotion}");
  });

  it("wires celestial selection through existing BrainPage path", () => {
    expect(page).toMatch(/onSelect=\{\(id\) => \{\s*setSelectedId\(id\);\s*setDetailTab\("Overview"\);/);
    expect(page).toContain("knowledgeAge");
    expect(page).toContain("KNOWLEDGE AGE");
    expect(page).toContain("Clear focus");
  });

  it("loads celestial styles and does not import prototype mock brain-live stub", () => {
    expect(main).toContain('import "./styles/brain-space.css"');
    expect(space).toContain('from "./brain-live"');
    expect(space).not.toContain("createMockBrainData");
    expect(space).toContain("createBrainSpaceAnimationLoop");
    expect(space).toContain("cancelAnimationFrame");
    expect(canvas).toContain("createBrainSpaceAnimationLoop");
    expect(canvas).toContain("ResizeObserver");
    expect(canvas).toContain("No nodes in current Brain projection / filter");
    expect(css).toContain(".lv-brain-space-");
    expect(css).not.toMatch(/^\.panel\b/m);
    expect(css).not.toMatch(/^\.planet\b/m);
  });

  it("keeps Tree/Timeline/Clusters/Analytics imports intact", () => {
    expect(page).toContain("BrainTreeView");
    expect(page).toContain("BrainTimelineView");
    expect(page).toContain("BrainClustersView");
    expect(page).toContain("BrainAnalyticsView");
  });
});
