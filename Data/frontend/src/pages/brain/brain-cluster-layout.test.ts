import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ClusterRow, LiveBrainEdge, LiveBrainNode } from "./brain-live";
import { BrainClustersView } from "./BrainClustersView";
import {
  canonicalMapClusters,
  layoutClusterPositions,
  pruneDraggedPositions,
  resolveClusterPosition,
  visibleMapClusters,
} from "./brain-cluster-layout";
import { zoomCenteredViewBoxAt, centeredViewBox } from "./brain-geometry";

function cluster(id: string, nodes: number): ClusterRow {
  return { id, label: id, nodes, color: "#abc", sample: [], internalEdges: 0 };
}

describe("brain cluster layout stability", () => {
  const many = Array.from({ length: 14 }, (_, index) => cluster(`type.${index}`, 100 - index));

  it("keeps canonical top-N independent of selection", () => {
    const canonical = canonicalMapClusters(many, 10);
    expect(canonical).toHaveLength(10);
    expect(canonical.map((row) => row.id)).toEqual(many.slice(0, 10).map((row) => row.id));
  });

  it("does not reshuffle layout positions when selecting outside top-N", () => {
    const canonical = canonicalMapClusters(many, 10);
    const before = layoutClusterPositions(canonical);
    const withSelected = visibleMapClusters(canonical, many[12]);
    const after = layoutClusterPositions(canonical);
    expect(withSelected).toHaveLength(11);
    expect(withSelected.some((row) => row.id === "type.12")).toBe(true);
    for (const id of before.keys()) {
      expect(after.get(id)).toEqual(before.get(id));
    }
    const overflow = resolveClusterPosition("type.12", new Map(), before);
    expect(overflow).not.toBeNull();
    expect(before.has("type.12")).toBe(false);
  });

  it("clears stale dragged positions when a cluster disappears", () => {
    const dragged = new Map([
      ["type.0", { x: 1, y: 2 }],
      ["gone", { x: 3, y: 4 }],
    ]);
    const pruned = pruneDraggedPositions(dragged, new Set(["type.0"]));
    expect(pruned.has("type.0")).toBe(true);
    expect(pruned.has("gone")).toBe(false);
  });

  it("anchors wheel-style zoom around a cursor world point", () => {
    const oldScale = 1;
    const newScale = 1.5;
    const offset = { x: 10, y: -20 };
    const world = { x: 300, y: 120 };
    const next = zoomCenteredViewBoxAt(900, 410, oldScale, newScale, offset, world);
    const box = centeredViewBox(900, 410, newScale, next);
    expect((world.x - box.x) / box.width).toBeCloseTo((world.x - centeredViewBox(900, 410, oldScale, offset).x) / centeredViewBox(900, 410, oldScale, offset).width, 6);
  });
});

describe("BrainClustersView rendering contract", () => {
  it("renders overview + map controls from live projection nodes", () => {
    const nodes: LiveBrainNode[] = [
      { id: "a", type: "dataset", label: "OHLCV", created_at: null, meta: {} },
      { id: "b", type: "dataset", label: "Ticks", created_at: null, meta: {} },
      { id: "c", type: "memory", label: "Recall", created_at: null, meta: {} },
      { id: "d", type: "agent", label: "Scout", created_at: null, meta: {} },
    ];
    const edges: LiveBrainEdge[] = [
      { id: "e1", source: "a", target: "c", relation: "uses" },
      { id: "e2", source: "c", target: "d", relation: "supports" },
    ];
    const html = renderToStaticMarkup(createElement(BrainClustersView, { nodes, edges }));
    expect(html).toContain("Cluster Overview");
    expect(html).toContain("Cluster Visualization");
    expect(html).toContain("Select a cluster.");
    expect(html).toContain("Interactive cluster relationship network");
    expect(html).toContain("Zoom out");
    expect(html).toContain("Fit cluster map");
    expect(html).toContain("Search clusters");
    expect(html).toContain("Dataset");
    expect(html).toContain("Memory");
  });
});
