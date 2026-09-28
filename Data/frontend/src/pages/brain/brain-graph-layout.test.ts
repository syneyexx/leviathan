import { describe, expect, it } from "vitest";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import {
  buildBrainGraphLayout,
  graphCanvasSize,
  layoutSpreadStats,
  mergeDraggedGraphPositions,
  resolveCollisionsSpatial,
} from "./brain-graph-layout";

function node(id: string, type: string, label = id): LiveBrainNode {
  return { id, type, label, created_at: null, meta: {} };
}

function fixture(count: number, options: { types?: string[]; isolated?: boolean; giant?: boolean; manySmall?: boolean } = {}): {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
} {
  const types = options.types ?? [
    "dataset",
    "memory",
    "agent",
    "model",
    "capability",
    "knowledge.document",
    "concept",
    "research.project",
  ];
  const nodes: LiveBrainNode[] = Array.from({ length: count }, (_, index) => {
    if (options.isolated) {
      return node(`iso:${index}`, `unique.${index}`, `Isolated ${index}`);
    }
    if (options.giant) {
      return node(`g:${index}`, "knowledge.document", `Doc ${index}`);
    }
    if (options.manySmall) {
      return node(`s:${index}`, `type.${index % Math.max(1, Math.floor(count / 3))}`, `Node ${index}`);
    }
    return node(`n:${index}`, types[index % types.length], `Node ${index}`);
  });
  const edges: LiveBrainEdge[] = [];
  if (!options.isolated) {
    const edgeCount = Math.min(count * 2, Math.max(0, count - 1) * 3);
    for (let index = 0; index < edgeCount; index += 1) {
      edges.push({
        id: `e:${index}`,
        source: nodes[index % nodes.length].id,
        target: nodes[(index * 5 + 3) % nodes.length].id,
        relation: "uses",
      });
    }
  }
  return { nodes, edges };
}

describe("brain graph layout spacing + collision", () => {
  it.each([10, 50, 250] as const)("layouts %i mixed nodes without NaN and with usable spacing", (count) => {
    const { nodes, edges } = fixture(count);
    const { width, height } = graphCanvasSize(count);
    const layout = buildBrainGraphLayout(nodes, edges, true, width, height);
    expect(layout).toHaveLength(count);
    for (const placed of layout) {
      expect(Number.isFinite(placed.x)).toBe(true);
      expect(Number.isFinite(placed.y)).toBe(true);
      expect(placed.r).toBeGreaterThan(0);
    }
    const stats = layoutSpreadStats(layout);
    // Soft floor: spatial collision should keep most pairs from stacking.
    expect(stats.minPairDistance).toBeGreaterThan(2);
    if (count >= 50) {
      expect(stats.minClusterDistance).toBeGreaterThan(40);
    }
  });

  it("keeps isolated nodes separated without edges", () => {
    const { nodes, edges } = fixture(40, { isolated: true });
    const { width, height } = graphCanvasSize(nodes.length);
    const layout = buildBrainGraphLayout(nodes, edges, true, width, height);
    const stats = layoutSpreadStats(layout);
    expect(layout).toHaveLength(40);
    expect(stats.clusterCenters.size).toBe(40);
    expect(stats.minClusterDistance).toBeGreaterThan(20);
  });

  it("packs a giant single cluster without collapsing to a point", () => {
    const { nodes, edges } = fixture(120, { giant: true });
    const { width, height } = graphCanvasSize(nodes.length);
    const layout = buildBrainGraphLayout(nodes, edges, true, width, height);
    const xs = layout.map((node) => node.x);
    const ys = layout.map((node) => node.y);
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(120);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(80);
    expect(layoutSpreadStats(layout).minPairDistance).toBeGreaterThan(2);
  });

  it("spaces many small clusters apart from each other", () => {
    const { nodes, edges } = fixture(60, { manySmall: true });
    const { width, height } = graphCanvasSize(nodes.length);
    const layout = buildBrainGraphLayout(nodes, edges, true, width, height);
    const stats = layoutSpreadStats(layout);
    expect(stats.clusterCenters.size).toBeGreaterThan(10);
    expect(stats.minClusterDistance).toBeGreaterThan(30);
  });

  it("spatial collision is cheaper than O(n²) pairwise for 250 nodes", () => {
    const { nodes } = fixture(250, { giant: true });
    const { width, height } = graphCanvasSize(nodes.length);
    const layout = buildBrainGraphLayout(nodes, [], false, width, height);
    const started = performance.now();
    resolveCollisionsSpatial(layout, { iterations: 12 });
    const elapsed = performance.now() - started;
    // Generous CI budget — the regression is algorithmic, not a hard realtime SLA.
    expect(elapsed).toBeLessThan(2_500);
    expect(layout.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y))).toBe(true);
  });

  it("preserves dragged positions across layout rebuilds", () => {
    const { nodes, edges } = fixture(20);
    const { width, height } = graphCanvasSize(nodes.length);
    const layoutA = buildBrainGraphLayout(nodes, edges, true, width, height);
    const previous = new Map(layoutA.map((node) => [node.id, { x: node.x, y: node.y }]));
    previous.set(layoutA[0].id, { x: 12, y: 34 });
    const layoutB = buildBrainGraphLayout(nodes, edges, false, width, height);
    const merged = mergeDraggedGraphPositions(layoutB, previous, new Set([layoutA[0].id]));
    expect(merged.get(layoutA[0].id)).toEqual({ x: 12, y: 34 });
    expect(merged.get(layoutA[1].id)).toEqual({ x: layoutB[1].x, y: layoutB[1].y });
  });
});
