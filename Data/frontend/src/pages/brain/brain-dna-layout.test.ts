import { describe, expect, it } from "vitest";
import { categoryForNodeType, filterNodesByCategory } from "./brain-categories";
import { layoutDnaNetwork, layoutDnaNetworkStable } from "./brain-dna-layout";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

function node(id: string, label: string, type: string): LiveBrainNode {
  return { id, label, type, created_at: "2025-01-01T00:00:00Z" };
}

function edge(id: string, source: string, target: string, relation = "related"): LiveBrainEdge {
  return { id, source, target, relation };
}

describe("brain-categories", () => {
  it("maps backend types into semantic categories without renaming them", () => {
    expect(categoryForNodeType("agent")).toBe("agent");
    expect(categoryForNodeType("knowledge.document")).toBe("document");
    expect(categoryForNodeType("evidence")).toBe("document");
    expect(categoryForNodeType("concept")).toBe("concept");
    expect(categoryForNodeType("memory")).toBe("concept");
    expect(categoryForNodeType("research.project")).toBe("entity");
  });

  it("filters by category without mutating input", () => {
    const nodes = [
      node("a", "A", "agent"),
      node("b", "B", "concept"),
      node("c", "C", "knowledge.document"),
    ];
    const filtered = filterNodesByCategory(nodes, "agent");
    expect(filtered.map((n) => n.id)).toEqual(["a"]);
    expect(nodes).toHaveLength(3);
  });
});

describe("brain-dna-layout", () => {
  const nodes: LiveBrainNode[] = [
    node("focal", "AI Agents", "agent"),
    node("btc", "Bitcoin", "concept"),
    node("eth", "Ethereum", "concept"),
    node("doc1", "Market Report", "knowledge.document"),
    node("mem1", "Risk Memory", "memory"),
    node("ent1", "Web3", "research.project"),
  ];
  const edges: LiveBrainEdge[] = [
    edge("e1", "focal", "btc"),
    edge("e2", "focal", "eth"),
    edge("e3", "btc", "eth"),
    edge("e4", "btc", "doc1"),
    edge("e5", "eth", "mem1"),
  ];

  it("is deterministic for the same input", () => {
    const a = layoutDnaNetwork(nodes, edges, {
      width: 800,
      height: 360,
      preferredFocalId: "focal",
    });
    const b = layoutDnaNetwork(nodes, edges, {
      width: 800,
      height: 360,
      preferredFocalId: "focal",
    });
    expect(a.nodes).toEqual(b.nodes);
    expect(a.edges).toEqual(b.edges);
    expect(a.focalId).toBe("focal");
  });

  it("is stable across input order", () => {
    const reversed = layoutDnaNetworkStable([...nodes].reverse(), [...edges].reverse(), {
      width: 800,
      height: 360,
    });
    const forward = layoutDnaNetworkStable(nodes, edges, { width: 800, height: 360 });
    expect(reversed.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y }))).toEqual(
      forward.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y })),
    );
  });

  it("has no NaN/Infinity and respects bounds", () => {
    const result = layoutDnaNetwork(nodes, edges, { width: 640, height: 300 });
    for (const n of result.nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(640);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(300);
      expect(n.r).toBeGreaterThan(0);
    }
  });

  it("centers the focal node", () => {
    const result = layoutDnaNetwork(nodes, edges, { width: 800, height: 400, preferredFocalId: "focal" });
    const focal = result.nodes.find((n) => n.focal);
    expect(focal).toBeDefined();
    expect(focal!.x).toBe(400);
    expect(focal!.y).toBe(200);
  });

  it("supports empty and single-node graphs", () => {
    expect(layoutDnaNetwork([], [], { width: 400, height: 200 }).nodes).toEqual([]);
    const one = layoutDnaNetwork([node("only", "Only", "concept")], [], {
      width: 400,
      height: 200,
    });
    expect(one.nodes).toHaveLength(1);
    expect(one.nodes[0].focal).toBe(true);
    expect(one.nodes[0].x).toBe(200);
    expect(one.nodes[0].y).toBe(100);
  });

  it("supports a large bounded graph without blowing up", () => {
    const many = Array.from({ length: 120 }, (_, i) =>
      node(`n${i}`, `Node ${i}`, i % 4 === 0 ? "agent" : i % 4 === 1 ? "concept" : i % 4 === 2 ? "knowledge.document" : "research.project"),
    );
    const manyEdges = Array.from({ length: 200 }, (_, i) =>
      edge(`e${i}`, `n${i % 120}`, `n${(i * 7) % 120}`),
    );
    const result = layoutDnaNetwork(many, manyEdges, { width: 900, height: 400, maxPrimary: 48 });
    expect(result.nodes.length).toBeLessThanOrEqual(49);
    expect(result.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });

  it("honors preferredFocalId when present", () => {
    const result = layoutDnaNetwork(nodes, edges, {
      width: 800,
      height: 360,
      preferredFocalId: "btc",
    });
    expect(result.focalId).toBe("btc");
  });
});
