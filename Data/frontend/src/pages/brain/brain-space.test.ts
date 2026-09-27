import { describe, expect, it } from "vitest";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import {
  brainSpaceDomainForNode,
  buildBrainSpaceProjection,
  createBrainSpaceAnimationLoop,
  nodeVisibleAtKnowledgeAge,
  parseBrainTimestamp,
  projectionFingerprint,
  visibleBrainSpaceEdges,
} from "./brain-space";

function node(
  partial: Partial<LiveBrainNode> & Pick<LiveBrainNode, "id" | "type" | "label">,
): LiveBrainNode {
  return {
    created_at: null,
    meta: {},
    ...partial,
  };
}

describe("brainSpaceDomainForNode", () => {
  it("lets canonical dataset type win over trading-like labels", () => {
    expect(
      brainSpaceDomainForNode(
        node({ id: "dataset:ohlcv", type: "dataset", label: "Market OHLCV" }),
      ),
    ).toBe("Datasets");
  });

  it("honors explicit valid meta.domain", () => {
    expect(
      brainSpaceDomainForNode(
        node({
          id: "concept:1",
          type: "concept",
          label: "Generic Idea",
          meta: { domain: "Trading" },
        }),
      ),
    ).toBe("Trading");
  });

  it("honors explicit valid meta.scope", () => {
    expect(
      brainSpaceDomainForNode(
        node({
          id: "x:1",
          type: "other",
          label: "Scoped",
          meta: { scope: "Research" },
        }),
      ),
    ).toBe("Research");
  });

  it("ignores unknown domain metadata and falls back honestly", () => {
    expect(
      brainSpaceDomainForNode(
        node({
          id: "x:2",
          type: "widget",
          label: "Mystery",
          meta: { domain: "NotARealDomain" },
        }),
      ),
    ).toBe("Other");
  });

  it("projects trading-labelled concepts into Trading without overriding datasets", () => {
    expect(
      brainSpaceDomainForNode(
        node({
          id: "concept:alpha",
          type: "concept",
          label: "Trading Strategy Alpha",
        }),
      ),
    ).toBe("Trading");
  });

  it("maps memory / agent / model / capability types canonically", () => {
    expect(brainSpaceDomainForNode(node({ id: "m", type: "memory", label: "Mem" }))).toBe("Memory");
    expect(brainSpaceDomainForNode(node({ id: "a", type: "agent", label: "Agent" }))).toBe("Agents");
    expect(brainSpaceDomainForNode(node({ id: "mo", type: "model", label: "LLM" }))).toBe("Models");
    expect(
      brainSpaceDomainForNode(node({ id: "c", type: "capability", label: "Tool" })),
    ).toBe("Capabilities");
  });
});

describe("parseBrainTimestamp / Knowledge Age", () => {
  it("returns null for missing and invalid timestamps (UNMEASURED)", () => {
    expect(parseBrainTimestamp(null)).toBeNull();
    expect(parseBrainTimestamp(undefined)).toBeNull();
    expect(parseBrainTimestamp("")).toBeNull();
    expect(parseBrainTimestamp("not-a-date")).toBeNull();
    expect(parseBrainTimestamp("2026-01-15T12:00:00Z")).toBe(
      Date.parse("2026-01-15T12:00:00Z"),
    );
  });

  it("keeps UNMEASURED nodes visible at any knowledge age", () => {
    const projection = buildBrainSpaceProjection(
      [
        node({
          id: "unknown-date",
          type: "knowledge.document",
          label: "Legacy Note",
          created_at: null,
        }),
        node({
          id: "early",
          type: "memory",
          label: "Early",
          created_at: "2026-01-01T00:00:00Z",
        }),
        node({
          id: "late",
          type: "concept",
          label: "Late",
          created_at: "2026-09-01T00:00:00Z",
        }),
      ],
      [],
    );
    const unknown = projection.byId.get("unknown-date");
    expect(unknown?.ageFraction).toBeNull();
    expect(nodeVisibleAtKnowledgeAge(unknown!, 0)).toBe(true);
    expect(nodeVisibleAtKnowledgeAge(unknown!, 1)).toBe(true);

    const late = projection.byId.get("late")!;
    expect(nodeVisibleAtKnowledgeAge(late, 0.01)).toBe(false);
    expect(nodeVisibleAtKnowledgeAge(late, 1)).toBe(true);
  });

  it("does not treat invalid created_at as age zero", () => {
    const projection = buildBrainSpaceProjection(
      [
        node({
          id: "bad",
          type: "memory",
          label: "Bad stamp",
          created_at: "yesterday-ish",
        }),
        node({
          id: "good",
          type: "memory",
          label: "Good stamp",
          created_at: "2026-06-01T00:00:00Z",
        }),
      ],
      [],
    );
    expect(projection.byId.get("bad")?.ageFraction).toBeNull();
    expect(projection.byId.get("bad")?.timestamp).toBeNull();
    expect(nodeVisibleAtKnowledgeAge(projection.byId.get("bad")!, 0)).toBe(true);
  });
});

describe("buildBrainSpaceProjection", () => {
  const nodes: LiveBrainNode[] = [
    node({
      id: "memory:1",
      type: "memory",
      label: "Working Memory",
      created_at: "2026-01-01T00:00:00Z",
      meta: { status: "active" },
    }),
    node({
      id: "dataset:1",
      type: "dataset",
      label: "Market OHLCV",
      created_at: "2026-06-01T00:00:00Z",
    }),
    node({
      id: "strategy:1",
      type: "concept",
      label: "Trading Strategy Alpha",
      created_at: "2026-09-01T00:00:00Z",
      meta: { domain: "Trading" },
    }),
    node({
      id: "unknown-date",
      type: "knowledge.document",
      label: "Legacy Note",
      created_at: null,
    }),
    node({
      id: "arch:1",
      type: "memory",
      label: "Old Recall",
      created_at: "2025-01-01T00:00:00Z",
      meta: { status: "archived" },
    }),
    node({
      id: "deg:1",
      type: "agent",
      label: "Degraded Agent",
      created_at: "2026-03-01T00:00:00Z",
      meta: { status: "degraded" },
    }),
    node({
      id: "down:1",
      type: "model",
      label: "Offline Model",
      created_at: "2026-04-01T00:00:00Z",
      meta: { available: false },
    }),
  ];

  const edges: LiveBrainEdge[] = [
    { id: "e1", source: "memory:1", target: "dataset:1", relation: "uses" },
    { id: "e2", source: "dataset:1", target: "strategy:1", relation: "supports" },
  ];

  it("projects every live node 1:1 with deterministic layout", () => {
    const a = buildBrainSpaceProjection(nodes, edges);
    const b = buildBrainSpaceProjection(nodes, edges);
    expect(a.byId.size).toBe(nodes.length);
    expect(projectionFingerprint(a)).toBe(projectionFingerprint(b));
    expect(a.byId.get("dataset:1")?.domain).toBe("Datasets");
    expect(a.byId.get("strategy:1")?.domain).toBe("Trading");
    expect(a.archivedCount).toBe(1);
    expect(a.byId.get("deg:1")?.status).toBe("degraded");
    expect(a.byId.get("down:1")?.status).toBe("unavailable");
    expect(a.byId.get("unknown-date")?.status).toBe("unknown");
  });

  it("only emits visible edges when both endpoints pass knowledge age", () => {
    const projection = buildBrainSpaceProjection(nodes, edges);
    const early = visibleBrainSpaceEdges(projection, edges, 0.05);
    expect(early.every((edge) => edge.source !== "strategy:1" && edge.target !== "strategy:1")).toBe(
      true,
    );
    const full = visibleBrainSpaceEdges(projection, edges, 1);
    expect(full).toHaveLength(2);
  });

  it("never invents nodes or relations", () => {
    const projection = buildBrainSpaceProjection(nodes, edges);
    for (const id of projection.byId.keys()) {
      expect(nodes.some((n) => n.id === id)).toBe(true);
    }
    for (const system of projection.systems) {
      for (const spaceNode of system.nodes) {
        expect(spaceNode.source.id).toBeTruthy();
        expect(nodes.find((n) => n.id === spaceNode.source.id)).toBeTruthy();
      }
    }
  });
});

describe("createBrainSpaceAnimationLoop", () => {
  it("starts exactly one RAF chain and cancels on stop", () => {
    const handles: number[] = [];
    let nextHandle = 1;
    let active = 0;
    const callbacks = new Map<number, FrameRequestCallback>();

    const raf = (cb: FrameRequestCallback) => {
      const id = nextHandle++;
      callbacks.set(id, cb);
      handles.push(id);
      active += 1;
      return id;
    };
    const caf = (id: number) => {
      if (callbacks.delete(id)) active -= 1;
    };

    let frames = 0;
    const loop = createBrainSpaceAnimationLoop({
      requestAnimationFrame: raf,
      cancelAnimationFrame: caf,
      onFrame: () => {
        frames += 1;
      },
    });

    expect(loop.isRunning()).toBe(false);
    loop.start();
    expect(loop.isRunning()).toBe(true);
    expect(active).toBe(1);

    // Drive a few frames manually.
    for (let i = 0; i < 3; i += 1) {
      const [[id, cb]] = [...callbacks.entries()];
      callbacks.delete(id);
      active -= 1;
      cb(1000 + (i + 1) * 16);
    }
    expect(frames).toBe(3);
    expect(active).toBe(1);

    loop.stop();
    expect(loop.isRunning()).toBe(false);
    expect(active).toBe(0);

    // Starting again replaces with a fresh chain (no duplicate).
    loop.start();
    expect(active).toBe(1);
    loop.start();
    expect(active).toBe(1);
    loop.stop();
    expect(active).toBe(0);
  });

  it("freezes simulation time while paused and resumes afterward", () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let nextHandle = 1;
    let wall = 0;

    const loop = createBrainSpaceAnimationLoop({
      paused: false,
      orbitScale: 1,
      requestAnimationFrame: (cb) => {
        const id = nextHandle++;
        callbacks.set(id, cb);
        return id;
      },
      cancelAnimationFrame: (id) => {
        callbacks.delete(id);
      },
      onFrame: () => undefined,
    });

    loop.start();
    const step = (ms: number) => {
      wall += ms;
      const [[id, cb]] = [...callbacks.entries()];
      callbacks.delete(id);
      cb(wall);
    };

    step(16);
    step(16);
    const beforePause = loop.getSimTime();
    expect(beforePause).toBeGreaterThan(0);

    loop.setPaused(true);
    step(16);
    step(16);
    expect(loop.getSimTime()).toBe(beforePause);

    loop.setPaused(false);
    step(16);
    expect(loop.getSimTime()).toBeGreaterThan(beforePause);
    loop.stop();
  });

  it("respects initial paused state (reduced motion)", () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let nextHandle = 1;
    let wall = 0;
    const loop = createBrainSpaceAnimationLoop({
      paused: true,
      orbitScale: 1,
      requestAnimationFrame: (cb) => {
        const id = nextHandle++;
        callbacks.set(id, cb);
        return id;
      },
      cancelAnimationFrame: (id) => {
        callbacks.delete(id);
      },
      onFrame: () => undefined,
    });
    loop.start();
    wall = 20;
    const [[id, cb]] = [...callbacks.entries()];
    callbacks.delete(id);
    cb(wall);
    expect(loop.getSimTime()).toBe(0);
    loop.stop();
  });
});

describe("250-node bounded projection fixture", () => {
  it("builds a usable deterministic projection without inventing data", () => {
    const nodes: LiveBrainNode[] = Array.from({ length: 250 }, (_, index) => {
      const types = [
        "dataset",
        "memory",
        "agent",
        "model",
        "capability",
        "concept",
        "research.project",
        "knowledge.document",
      ] as const;
      const type = types[index % types.length];
      return node({
        id: `n:${index}`,
        type,
        label: type === "dataset" ? `Market OHLCV ${index}` : `Node ${index}`,
        created_at:
          index % 7 === 0
            ? null
            : new Date(Date.UTC(2025, 0, 1 + (index % 300))).toISOString(),
        meta:
          index % 41 === 0
            ? { status: "degraded" }
            : index % 53 === 0
              ? { available: false }
              : index % 61 === 0
                ? { status: "archived" }
                : {},
      });
    });
    const edges: LiveBrainEdge[] = Array.from({ length: 400 }, (_, index) => ({
      id: `e:${index}`,
      source: `n:${index % 250}`,
      target: `n:${(index * 7 + 3) % 250}`,
      relation: index % 2 ? "supports" : "uses",
    }));

    const projection = buildBrainSpaceProjection(nodes, edges);
    expect(projection.byId.size).toBe(250);
    expect(projection.systems.length).toBeGreaterThan(0);
    expect(projectionFingerprint(projection)).toBe(
      projectionFingerprint(buildBrainSpaceProjection(nodes, edges)),
    );

    // Dataset labels with "Market" must remain Datasets.
    for (const spaceNode of projection.byId.values()) {
      if (spaceNode.source.type === "dataset") {
        expect(spaceNode.domain).toBe("Datasets");
      }
    }

    const visible = [...projection.byId.values()].filter((n) =>
      nodeVisibleAtKnowledgeAge(n, 0.25),
    );
    expect(visible.length).toBeGreaterThan(0);
    expect(visible.every((n) => n.ageFraction === null || n.ageFraction <= 0.25)).toBe(true);

    const filteredEdges = visibleBrainSpaceEdges(projection, edges, 0.25);
    for (const edge of filteredEdges) {
      expect(projection.byId.has(edge.source)).toBe(true);
      expect(projection.byId.has(edge.target)).toBe(true);
    }
  });
});

describe("filter integration contract", () => {
  it("projection only contains nodes passed in (BrainPage visibleNodes truth)", () => {
    const all = [
      node({ id: "keep", type: "dataset", label: "Keep", created_at: "2026-01-01T00:00:00Z" }),
      node({ id: "drop", type: "memory", label: "Drop", created_at: "2026-01-02T00:00:00Z" }),
    ];
    const visible = all.filter((n) => n.type === "dataset");
    const projection = buildBrainSpaceProjection(visible, [
      { id: "e", source: "keep", target: "drop", relation: "uses" },
    ]);
    expect(projection.byId.has("keep")).toBe(true);
    expect(projection.byId.has("drop")).toBe(false);
    expect(visibleBrainSpaceEdges(projection, [{ id: "e", source: "keep", target: "drop", relation: "uses" }], 1)).toHaveLength(0);
  });
});
