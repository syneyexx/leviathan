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
  const dna = read("pages/brain/BrainDnaNetwork.tsx");

  it("defaults V2 Graph to DNA while keeping Celestial/Technical reachable", () => {
    expect(page).toContain('useState<GraphPresentation>("dna")');
    expect(page).toContain("BrainSpaceCanvas");
    expect(page).toContain("BrainGraphCanvas");
    expect(page).toContain("Celestial");
    expect(page).toContain("Technical");
    expect(page).toContain("DNA");
    expect(dna).toContain("BrainLivingNetworkCanvas");
    expect(dna).toContain("helix canvas");
    expect(page).not.toMatch(/setView\(["']Space["']\)/);
    expect(page).not.toMatch(/BrainView.*Space/);
    expect(page).not.toContain("BrainSpacePrototypeView");
    expect(page).not.toContain("createMockBrainData");
  });

  it("preserves advanced graph controls and selection ownership", () => {
    expect(page).toContain("variant=\"v2\"");
    expect(page).toContain("overview.setSelectedId");
    expect(page).toContain("visibleEdges");
    expect(page).toContain("Orbit");
    expect(page).toContain("physicsLayout={orbitMotion}");
    expect(page).toContain("paused={!orbitMotion}");
    expect(page).toContain("showLabels");
    expect(page).toContain("showClusters");
    expect(page).toContain("showDepth");
  });

  it("wires celestial selection and knowledge-age through advanced Graph path", () => {
    expect(page).toContain("onSelect={overview.setSelectedId}");
    expect(page).toContain("knowledgeAge");
    expect(page).toContain("KNOWLEDGE AGE");
    expect(page).toContain("isolatedDomain");
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
