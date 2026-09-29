import { describe, expect, it } from "vitest";
import { buildDnaLayout } from "./brain-dna-layout";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

function node(id: string, type = "concept", label = id): LiveBrainNode {
  return { id, type, label, created_at: null, meta: {} };
}

function edge(id: string, source: string, target: string, relation = "related"): LiveBrainEdge {
  return { id, source, target, relation };
}

const colorForType = (type: string) => `#${type.length.toString(16).padStart(6, "0")}`;

describe("buildDnaLayout", () => {
  it("is deterministic: same input → same positions", () => {
    const nodes = [node("b"), node("a"), node("c"), node("d")];
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "c"), edge("e3", "c", "d")];
    const opts = {
      nodes,
      edges,
      width: 800,
      height: 480,
      colorForType,
      maxLabels: 8,
    };
    const a = buildDnaLayout(opts);
    const b = buildDnaLayout(opts);
    expect(a.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y, r: n.r, strand: n.strand }))).toEqual(
      b.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y, r: n.r, strand: n.strand })),
    );
    expect(a.scaffold).toEqual(b.scaffold);
    expect(a.centerNodeId).toBe(b.centerNodeId);
  });

  it("never includes scaffold ids in semanticEdges", () => {
    const nodes = [node("n1"), node("n2"), node("n3"), node("n4"), node("n5"), node("n6")];
    const edges = [edge("real:1", "n1", "n2"), edge("real:2", "n3", "n4")];
    const layout = buildDnaLayout({
      nodes,
      edges,
      width: 900,
      height: 500,
      colorForType,
    });
    expect(layout.scaffold.length).toBeGreaterThan(0);
    const semanticIds = new Set(layout.semanticEdges.map((e) => e.id));
    for (const segment of layout.scaffold) {
      expect(semanticIds.has(segment.id)).toBe(false);
      expect(segment.id.startsWith("scaffold:")).toBe(true);
    }
    expect(layout.semanticEdges.map((e) => e.id).sort()).toEqual(["real:1", "real:2"]);
  });

  it("uses selected node as center when provided", () => {
    const nodes = [node("hub"), node("leaf-a"), node("leaf-b"), node("picked")];
    const edges = [
      edge("e1", "hub", "leaf-a"),
      edge("e2", "hub", "leaf-b"),
      edge("e3", "hub", "picked"),
    ];
    const without = buildDnaLayout({
      nodes,
      edges,
      width: 700,
      height: 400,
      colorForType,
    });
    expect(without.centerNodeId).toBe("hub");

    const withSelected = buildDnaLayout({
      nodes,
      edges,
      width: 700,
      height: 400,
      selectedId: "picked",
      colorForType,
    });
    expect(withSelected.centerNodeId).toBe("picked");
    const center = withSelected.nodes.find((n) => n.id === "picked");
    expect(center?.showLabel).toBe(true);
  });

  it("returns empty layout for empty nodes", () => {
    const layout = buildDnaLayout({
      nodes: [],
      edges: [edge("orphan", "a", "b")],
      width: 640,
      height: 360,
      colorForType,
    });
    expect(layout.nodes).toEqual([]);
    expect(layout.semanticEdges).toEqual([]);
    expect(layout.scaffold).toEqual([]);
    expect(layout.centerNodeId).toBeNull();
    expect(layout.width).toBe(640);
    expect(layout.height).toBe(360);
  });

  it("stable-sorts by id and alternates strands", () => {
    const nodes = [node("z"), node("a"), node("m")];
    const layout = buildDnaLayout({
      nodes,
      edges: [],
      width: 600,
      height: 300,
      colorForType,
    });
    expect(layout.nodes.map((n) => n.id)).toEqual(["a", "m", "z"]);
    expect(layout.nodes.map((n) => n.strand)).toEqual([0, 1, 0]);
  });
});
