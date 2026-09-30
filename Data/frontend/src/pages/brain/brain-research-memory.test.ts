import { describe, expect, it } from "vitest";
import {
  EMPTY_KNOWLEDGE_ACTIVATION,
  parseKnowledgeActivationEvent,
  reduceKnowledgeActivation,
} from "./brain-activation";
import type { RuntimeEvent } from "../../types/api";
import {
  assignStableHelixSlots,
  hitTestEdge,
  hitTestNode,
  isClaimEvidenceRelation,
  projectNodes,
  strandRoleForType,
} from "./brain-helix-engine";
import {
  compareInsights,
  evidenceViewForEdge,
  findKnowledgeGaps,
  freshnessForNode,
  impactedDependents,
} from "./brain-knowledge-model";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

function evt(
  partial: Partial<RuntimeEvent> & Pick<RuntimeEvent, "sequence" | "event_id">,
): RuntimeEvent {
  return {
    created_at_ms: 1_000_000 + partial.sequence,
    level: "INFO",
    category: "brain",
    subsystem: "brain",
    name: "knowledge_activation",
    message: "brain.knowledge_activation",
    payload: {},
    source: "test",
    ...partial,
  };
}

describe("brain-activation", () => {
  it("activates only retrieval-backed node ids", () => {
    const a = parseKnowledgeActivationEvent(
      evt({
        sequence: 1,
        event_id: "e1",
        payload: {
          request_id: "req-1",
          conversation_id: "c1",
          phase: "complete",
          hit_count: 2,
          node_ids: ["knowledge:document:a", "knowledge:document:b"],
          identifiers_available: true,
        },
      }),
    );
    expect(a?.nodeIds).toEqual(["knowledge:document:a", "knowledge:document:b"]);
  });

  it("does not invent nodes when identifiers are unavailable", () => {
    const state = reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, [
      evt({
        sequence: 2,
        event_id: "e2",
        payload: {
          request_id: "req-2",
          phase: "complete",
          hit_count: 5,
          node_ids: ["should-ignore"],
          identifiers_available: false,
        },
      }),
    ]);
    expect(state.activeNodeIds).toEqual([]);
    expect(state.identifiersAvailable).toBe(false);
    expect(state.detail).toMatch(/Geen node-identificatie beschikbaar/);
  });

  it("dedupes by event id and ignores stale lower sequences for same request", () => {
    const first = reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, [
      evt({
        sequence: 10,
        event_id: "dup",
        payload: {
          request_id: "r",
          phase: "complete",
          node_ids: ["knowledge:document:new"],
          identifiers_available: true,
        },
      }),
    ]);
    const second = reduceKnowledgeActivation(first, [
      evt({
        sequence: 10,
        event_id: "dup",
        payload: {
          request_id: "r",
          phase: "complete",
          node_ids: ["knowledge:document:new"],
          identifiers_available: true,
        },
      }),
      evt({
        sequence: 5,
        event_id: "older",
        payload: {
          request_id: "r",
          phase: "complete",
          node_ids: ["knowledge:document:old"],
          identifiers_available: true,
        },
      }),
    ]);
    expect(second.activeNodeIds).toEqual(["knowledge:document:new"]);
    expect(second.requests).toHaveLength(1);
  });

  it("keeps followed request when a later request arrives", () => {
    const s1 = reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, [
      evt({
        sequence: 1,
        event_id: "a",
        payload: {
          request_id: "req-a",
          node_ids: ["knowledge:document:a"],
          identifiers_available: true,
          phase: "complete",
        },
      }),
    ]);
    const s2 = reduceKnowledgeActivation(
      s1,
      [
        evt({
          sequence: 2,
          event_id: "b",
          payload: {
            request_id: "req-b",
            node_ids: ["knowledge:document:b"],
            identifiers_available: true,
            phase: "complete",
          },
        }),
      ],
      { followedRequestId: "req-a" },
    );
    expect(s2.followedRequestId).toBe("req-a");
    expect(s2.activeNodeIds).toEqual(["knowledge:document:a"]);
  });
});

describe("brain-helix-engine", () => {
  it("keeps stable helix slots when nodes are added", () => {
    const a = assignStableHelixSlots([
      { id: "n1", label: "One", type: "knowledge.document" },
      { id: "n2", label: "Two", type: "concept" },
    ]);
    const b = assignStableHelixSlots([
      { id: "n1", label: "One", type: "knowledge.document" },
      { id: "n2", label: "Two", type: "concept" },
      { id: "n3", label: "Three", type: "evidence" },
    ]);
    expect(a.find((n) => n.id === "n1")?.position).toBe(b.find((n) => n.id === "n1")?.position);
    expect(a.find((n) => n.id === "n2")?.strand).toBe(b.find((n) => n.id === "n2")?.strand);
  });

  it("labels unknown types without inventing insight", () => {
    expect(strandRoleForType("mcp.tool")).toBe("unknown");
    expect(strandRoleForType("knowledge.document")).toBe("source");
    expect(strandRoleForType("research.project")).toBe("insight");
  });

  it("picks nodes and edges without fabricating links", () => {
    const nodes = assignStableHelixSlots([
      { id: "a", label: "A", type: "knowledge.document" },
      { id: "b", label: "B", type: "concept" },
    ]);
    const links = [{ id: "e1", source: "a", target: "b", relation: "SUPPORTS" }];
    const projected = projectNodes(nodes, links, {
      width: 400,
      height: 300,
      angle: 0.5,
      tilt: 0,
      zoom: 1,
      twist: 1.6,
      morph: 0,
      range: [0, 1],
      selectedId: null,
      activeIds: new Set(),
      filter: () => true,
    });
    expect(projected).toHaveLength(2);
    const hit = hitTestNode(projected, projected[0].x, projected[0].y, () => true);
    expect(hit?.node.id).toBe(projected[0].node.id);
    const segments = [
      {
        link: links[0],
        a: { x: 10, y: 10, z: 0, scale: 1 },
        b: { x: 40, y: 10, z: 0, scale: 1 },
        z: 0,
      },
    ];
    expect(hitTestEdge(segments, 25, 10)?.id).toBe("e1");
    expect(hitTestEdge(segments, 25, 40)).toBeNull();
  });

  it("recognizes claim-evidence vocabulary", () => {
    expect(isClaimEvidenceRelation("SUPPORTS")).toBe(true);
    expect(isClaimEvidenceRelation("from_dataset")).toBe(false);
  });
});

describe("brain-knowledge-model", () => {
  const nodes: LiveBrainNode[] = [
    { id: "src", label: "Bron", type: "knowledge.document", meta: { status: "active" } },
    { id: "insight", label: "Conclusie", type: "concept" },
    { id: "insight2", label: "Andere", type: "concept" },
    {
      id: "withdrawn",
      label: "Ingetrokken",
      type: "knowledge.document",
      meta: { status: "withdrawn" },
    },
  ];
  const edges: LiveBrainEdge[] = [
    { id: "e1", source: "src", target: "insight", relation: "SUPPORTS" },
    { id: "e2", source: "withdrawn", target: "insight2", relation: "SUPPORTS" },
    { id: "e3", source: "src", target: "insight2", relation: "related" },
  ];

  it("keeps association edges out of claim-evidence presentation", () => {
    const view = evidenceViewForEdge(edges[2], nodes);
    expect(view?.isClaimEvidence).toBe(false);
    expect(view?.passage).toBeNull();
    expect(view?.note).toMatch(/associatie/i);
  });

  it("marks missing passage as unknown for claim-evidence edges", () => {
    const view = evidenceViewForEdge(edges[0], nodes);
    expect(view?.isClaimEvidence).toBe(true);
    expect(view?.status).toBe("unknown");
    expect(view?.passage).toBeNull();
  });

  it("flags withdrawn sources for review without auto-false", () => {
    const gaps = findKnowledgeGaps(nodes, edges, { truncated: true, maxNodes: 250 });
    expect(gaps.some((g) => g.kind === "withdrawn_source")).toBe(true);
    expect(gaps.some((g) => g.kind === "truncated")).toBe(true);
    const impact = impactedDependents("src", edges);
    expect(impact.dependentIds).toContain("insight");
    expect(impact.note).toMatch(/dependency/i);
  });

  it("compares insights without treating edge counts as truth scores", () => {
    const cmp = compareInsights("insight", "insight2", edges);
    expect(cmp.note).toMatch(/geen waarheidsscore/i);
    expect(cmp.supportingA).toEqual(["src"]);
  });

  it("treats missing verification date as unknown, not age 0", () => {
    const fresh = freshnessForNode(nodes[0], { nowMs: Date.parse("2026-09-30T12:00:00Z") });
    expect(fresh.state).toBe("unknown");
    expect(fresh.days).toBeNull();
  });
});

describe("production fallback guard", () => {
  it("does not import demo mock data modules", async () => {
    // Ensure production brain modules resolve without DNADemoData globals.
    await import("./BrainDnaNetwork");
    await import("./BrainNetworkWorkbench");
    expect((globalThis as { DNADemoData?: unknown }).DNADemoData).toBeUndefined();
  });
});

describe("network rendering regressions", () => {
  it("fits all local-network nodes inside narrow and desktop stages", () => {
    const nodes = assignStableHelixSlots(Array.from({length: 250}, (_, i) => ({id: `doc-${i}`, label: `Document ${i}`, type: 'knowledge.document'})));
    for (const width of [250, 360, 800]) {
      const points = projectNodes(nodes, [], {width, height: 320, angle: 0.6, tilt: -0.095, zoom: 1, twist: 1.6, morph: 1, range: [0,1], selectedId: nodes[0].id, activeIds: new Set(), filter: () => true});
      for (const p of points) {
        expect(p.x).toBeGreaterThanOrEqual(20);
        expect(p.x).toBeLessThanOrEqual(width - 20);
        expect(p.y).toBeGreaterThanOrEqual(70);
        expect(p.y).toBeLessThanOrEqual(280);
      }
    }
  });

  it("picks the frontmost overlapping node regardless of backend ordering", () => {
    const nodes = assignStableHelixSlots([{id:'front',label:'Front',type:'concept'}, {id:'back',label:'Back',type:'concept'}]);
    expect(hitTestNode(nodes.map((node,i) => ({node,x:40,y:40,z:1-i,scale:1,r:5})),40,40,()=>true)?.node.id).toBe('front');
  });

  it("late completion does not steal auto-follow from the newer request, including newest-first event feeds", () => {
    const events = [
      evt({sequence: 1,event_id:'a',payload:{request_id:'old',phase:'retrieving'}}),
      evt({sequence: 2,event_id:'b',payload:{request_id:'new',phase:'complete',node_ids:['memory:new'],identifiers_available:true}}),
      evt({sequence: 3,event_id:'c',payload:{request_id:'old',phase:'complete',node_ids:['memory:old'],identifiers_available:true}}),
    ];
    const result = reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, events.reverse(), {followedRequestId:null});
    expect(result.followedRequestId).toBe('new');
    expect(result.activeNodeIds).toEqual(['memory:new']);
  });

  it("cancelled retrieval clears highlights", () => {
    const result = reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, [evt({sequence:1,event_id:'cancel',payload:{request_id:'r',phase:'cancelled',node_ids:['memory:old'],identifiers_available:true}})]);
    expect(result.activeNodeIds).toEqual([]);
    expect(result.detail).toMatch(/geannuleerd/);
  });
});
