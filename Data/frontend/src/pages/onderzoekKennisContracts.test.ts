import { describe, expect, it } from "vitest";
import { buildAnalytics, buildClusters, buildTimeline, buildTree } from "./brain/brain-live";

const nodes = [
  {
    id: "knowledge:document:1",
    type: "knowledge.document",
    label: "Doc A",
    created_at: "2026-01-02T00:00:00Z",
    meta: { status: "READY" },
  },
  {
    id: "memory:m1",
    type: "memory",
    label: "Prefer concise answers",
    created_at: "2026-01-03T00:00:00Z",
    meta: { kind: "PREFERENCE", status: "ACTIVE" },
  },
  {
    id: "evidence:e1",
    type: "evidence",
    label: "Claim",
    created_at: "2026-01-01T00:00:00Z",
    meta: { status: "VERIFIED" },
  },
];

const edges = [
  { id: "a", source: "memory:m1", target: "knowledge:document:1", relation: "related" },
];

describe("brain-live projections", () => {
  it("builds a typed tree from live nodes", () => {
    const tree = buildTree(nodes);
    expect(tree.id).toBe("leviathan");
    expect(tree.count).toBe(3);
    expect(tree.children?.some((c) => c.id === "type:memory")).toBe(true);
  });

  it("orders timeline by created_at desc", () => {
    const events = buildTimeline(nodes);
    expect(events[0]?.id).toBe("memory:m1");
    expect(events.length).toBe(3);
  });

  it("clusters by type", () => {
    const clusters = buildClusters(nodes, edges);
    expect(clusters[0]?.nodes).toBeGreaterThanOrEqual(1);
    expect(clusters.some((c) => c.id === "memory")).toBe(true);
  });

  it("analytics reflect live counts without fake growth inventing nodes", () => {
    const analytics = buildAnalytics(nodes, edges, { node_count: 3, edge_count: 1 });
    expect(analytics.nodeCount).toBe(3);
    expect(analytics.edgeCount).toBe(1);
    expect(analytics.typeCount).toBe(3);
  });
});
