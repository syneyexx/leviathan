import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

export type BrainSpaceMode = "galaxy" | "systems" | "orbits";

export type BrainSpaceDomain =
  | "Knowledge"
  | "Memory"
  | "Agents"
  | "Datasets"
  | "Capabilities"
  | "Models"
  | "Research"
  | "Trading"
  | "Other";

export type BrainSpacePalette = {
  sun: string;
  planet: string;
};

export type BrainSpaceNode = {
  source: LiveBrainNode;
  domain: BrainSpaceDomain;
  color: string;
  accent: string;
  radius: number;
  orbit: number;
  phase: number;
  speed: number;
  tilt: number;
  style: "solid" | "banded" | "ring";
  timestamp: number | null;
  ageFraction: number | null;
  recent: boolean;
  archived: boolean;
  status: "ready" | "degraded" | "unavailable" | "unknown";
  importance: number;
};

export type BrainSpaceSystem = {
  domain: BrainSpaceDomain;
  palette: BrainSpacePalette;
  galRadius: number;
  angle: number;
  orbitSpeed: number;
  nodes: BrainSpaceNode[];
};

export type BrainSpaceProjection = {
  systems: BrainSpaceSystem[];
  byId: Map<string, BrainSpaceNode>;
  minTimestamp: number | null;
  maxTimestamp: number | null;
  archivedCount: number;
};

export const BRAIN_SPACE_DOMAINS: readonly BrainSpaceDomain[] = [
  "Knowledge",
  "Memory",
  "Agents",
  "Datasets",
  "Capabilities",
  "Models",
  "Research",
  "Trading",
  "Other",
] as const;

export const BRAIN_SPACE_PALETTE: Record<BrainSpaceDomain, BrainSpacePalette> = {
  Knowledge: { sun: "#7BE8FF", planet: "#4CA6FF" },
  Memory: { sun: "#C091FF", planet: "#8F63EA" },
  Agents: { sun: "#FF7FDB", planet: "#DE56B2" },
  Datasets: { sun: "#82FFD2", planet: "#40C89F" },
  Capabilities: { sun: "#FFD978", planet: "#DEA247" },
  Models: { sun: "#FF9A73", planet: "#DF704C" },
  Research: { sun: "#93ADFF", planet: "#6580E1" },
  Trading: { sun: "#97FF84", planet: "#59CA5B" },
  Other: { sun: "#C8D1DD", planet: "#8E9AA8" },
};

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seeded01(value: string, salt: string): number {
  return (hashString(`${salt}:${value}`) % 10_000) / 10_000;
}

function normalizeText(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function explicitDomain(node: LiveBrainNode): BrainSpaceDomain | null {
  const raw = normalizeText(node.meta?.domain ?? node.meta?.scope);
  if (!raw) return null;
  const match = BRAIN_SPACE_DOMAINS.find((domain) => domain.toLowerCase() === raw);
  return match ?? null;
}

/**
 * VIEW classification only.
 * Never mutates node.type, backend metadata, or canonical ownership.
 *
 * Priority:
 * 1. explicit trusted meta.domain / meta.scope when valid
 * 2. canonical node.type
 * 3. deterministic label fallback
 */
export function brainSpaceDomainForNode(node: LiveBrainNode): BrainSpaceDomain {
  const explicit = explicitDomain(node);
  if (explicit) return explicit;

  const type = node.type.toLowerCase();
  const label = node.label.toLowerCase();
  const combined = `${type} ${label}`;

  // Strong canonical type ownership wins over display-label heuristics.
  // Example: a dataset named "Market OHLCV" remains a Dataset, not Trading.
  if (
    type.includes("dataset") ||
    type.includes("data.") ||
    type.includes("corpus")
  ) return "Datasets";

  if (
    type.includes("research") ||
    type === "project" ||
    type === "run"
  ) return "Research";

  if (
    type === "agent" ||
    type.includes("agent")
  ) return "Agents";

  if (
    type === "model" ||
    type.includes("model") ||
    type.includes("llm")
  ) return "Models";

  if (
    type.includes("capability") ||
    type.includes("mcp.") ||
    type === "tool" ||
    type === "workflow" ||
    type === "code" ||
    type === "module"
  ) return "Capabilities";

  if (
    type === "memory" ||
    type === "conversation"
  ) return "Memory";

  if (
    type.includes("knowledge") ||
    type === "concept" ||
    type === "evidence" ||
    type === "atlas"
  ) {
    if (
      type === "concept" &&
      (
        combined.includes("trading") ||
        combined.includes("strategy") ||
        combined.includes("market") ||
        combined.includes("backtest") ||
        combined.includes("portfolio") ||
        combined.includes("riskguard") ||
        combined.includes("risk guard")
      )
    ) return "Trading";
    return "Knowledge";
  }

  // Label heuristics are a final display fallback only.
  if (
    combined.includes("trading") ||
    combined.includes("market") ||
    combined.includes("strategy") ||
    combined.includes("backtest") ||
    combined.includes("portfolio") ||
    combined.includes("riskguard") ||
    combined.includes("risk guard") ||
    combined.includes("paper ledger")
  ) return "Trading";

  if (
    combined.includes("hypothesis") ||
    combined.includes("experiment")
  ) return "Research";

  if (
    combined.includes("dataset") ||
    combined.includes("corpus") ||
    combined.includes("ohlcv") ||
    combined.includes("tick archive")
  ) return "Datasets";

  if (
    combined.includes("orchestrator") ||
    combined.includes("researcher") ||
    combined.includes("verifier") ||
    combined.includes("synthesizer")
  ) return "Agents";

  if (
    combined.includes("embedding model") ||
    combined.includes("reranker")
  ) return "Models";

  if (
    combined.includes("browser") ||
    combined.includes("provider")
  ) return "Capabilities";

  if (
    combined.includes("memory") ||
    combined.includes("recall") ||
    combined.includes("session")
  ) return "Memory";

  if (
    combined.includes("ontology") ||
    combined.includes("entity graph")
  ) return "Knowledge";

  return "Other";
}

export function parseBrainTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isArchivedBrainNode(node: LiveBrainNode): boolean {
  const status = normalizeText(node.meta?.status);
  const lifecycle = normalizeText(node.meta?.lifecycle);
  const state = normalizeText(node.meta?.state);
  if (node.meta?.archived === true) return true;
  if (node.meta?.deprecated === true) return true;
  if (node.meta?.retired === true) return true;
  return ["archived", "deprecated", "retired"].some(
    (token) => status === token || lifecycle === token || state === token,
  );
}

function statusForNode(node: LiveBrainNode): BrainSpaceNode["status"] {
  if (node.meta?.available === false) return "unavailable";
  const raw = normalizeText(node.meta?.status);
  if (!raw) return "unknown";
  if (["ready", "active", "healthy", "running", "available", "completed", "verified"].includes(raw)) {
    return "ready";
  }
  if (["degraded", "warning", "partial", "stale"].includes(raw)) return "degraded";
  if (["unavailable", "offline", "failed", "blocked", "disabled"].includes(raw)) {
    return "unavailable";
  }
  // Archived/retired are lifecycle states, not health — keep presentation neutral.
  if (["archived", "deprecated", "retired"].includes(raw)) return "unknown";
  return "unknown";
}

function importanceForNode(node: LiveBrainNode, degree: number): number {
  const explicit = Number(node.meta?.importance ?? node.meta?.relevance);
  if (Number.isFinite(explicit)) {
    return Math.max(0, Math.min(100, explicit));
  }
  return Math.max(18, Math.min(100, 35 + Math.log2(degree + 1) * 14));
}

export function buildBrainSpaceProjection(
  nodes: LiveBrainNode[],
  edges: LiveBrainEdge[],
): BrainSpaceProjection {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const timestamps = nodes
    .map((node) => parseBrainTimestamp(node.created_at))
    .filter((value): value is number => value !== null);

  const minTimestamp = timestamps.length ? Math.min(...timestamps) : null;
  const maxTimestamp = timestamps.length ? Math.max(...timestamps) : null;
  const timeSpan =
    minTimestamp !== null && maxTimestamp !== null && maxTimestamp > minTimestamp
      ? maxTimestamp - minTimestamp
      : null;

  const grouped = new Map<BrainSpaceDomain, LiveBrainNode[]>();
  for (const domain of BRAIN_SPACE_DOMAINS) grouped.set(domain, []);
  for (const node of nodes) {
    grouped.get(brainSpaceDomainForNode(node))?.push(node);
  }

  const systems: BrainSpaceSystem[] = [];
  const byId = new Map<string, BrainSpaceNode>();
  const nonEmptyDomains = BRAIN_SPACE_DOMAINS.filter((domain) => (grouped.get(domain)?.length ?? 0) > 0);
  let archivedCount = 0;

  nonEmptyDomains.forEach((domain, systemIndex) => {
    const sourceNodes = grouped.get(domain) ?? [];
    const palette = BRAIN_SPACE_PALETTE[domain];
    // Calm but clearly visible orbital motion (ms-based sim clock).
    const system: BrainSpaceSystem = {
      domain,
      palette,
      galRadius: 260 + (systemIndex % 3) * 48 + seeded01(domain, "gal-r") * 18,
      angle: (systemIndex / Math.max(1, nonEmptyDomains.length)) * Math.PI * 2 - 0.3,
      orbitSpeed:
        (systemIndex % 2 ? -0.00011 : 0.00013) *
        (0.85 + seeded01(domain, "orbit") * 0.4),
      nodes: [],
    };

    sourceNodes
      .slice()
      .sort((a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id))
      .forEach((node, nodeIndex) => {
        const styleSeed = seeded01(node.id, "style");
        const timestamp = parseBrainTimestamp(node.created_at);
        const ageFraction =
          timestamp === null || minTimestamp === null || timeSpan === null
            ? null
            : Math.max(0, Math.min(1, (timestamp - minTimestamp) / timeSpan));
        const archived = isArchivedBrainNode(node);
        if (archived) archivedCount += 1;

        const spaceNode: BrainSpaceNode = {
          source: node,
          domain,
          color: palette.planet,
          accent: styleSeed > 0.68 ? palette.sun : styleSeed > 0.38 ? "#FFFFFF" : palette.planet,
          radius: 3.8 + seeded01(node.id, "radius") * 4.2,
          orbit: 42 + nodeIndex * 11 + seeded01(node.id, "orbit-radius") * 8,
          phase: seeded01(node.id, "phase") * Math.PI * 2,
          speed:
            (0.00055 + seeded01(node.id, "speed") * 0.00085) *
            (seeded01(node.id, "direction") > 0.25 ? 1 : -1),
          tilt: (seeded01(node.id, "tilt") - 0.5) * 0.55,
          style: styleSeed > 0.77 ? "ring" : styleSeed > 0.45 ? "banded" : "solid",
          timestamp,
          ageFraction,
          recent:
            timestamp !== null && maxTimestamp !== null
              ? maxTimestamp - timestamp <= 1000 * 60 * 60 * 24 * 7
              : false,
          archived,
          status: statusForNode(node),
          importance: importanceForNode(node, degree.get(node.id) ?? 0),
        };
        system.nodes.push(spaceNode);
        byId.set(node.id, spaceNode);
      });

    systems.push(system);
  });

  return { systems, byId, minTimestamp, maxTimestamp, archivedCount };
}

export function nodeVisibleAtKnowledgeAge(
  node: BrainSpaceNode,
  knowledgeAge: number,
): boolean {
  // Missing created_at is UNMEASURED, not zero and not fabricated.
  if (node.ageFraction === null) return true;
  return node.ageFraction <= knowledgeAge;
}

export function visibleBrainSpaceEdges(
  projection: BrainSpaceProjection,
  edges: LiveBrainEdge[],
  knowledgeAge: number,
): LiveBrainEdge[] {
  return edges.filter((edge) => {
    const source = projection.byId.get(edge.source);
    const target = projection.byId.get(edge.target);
    return (
      source !== undefined &&
      target !== undefined &&
      nodeVisibleAtKnowledgeAge(source, knowledgeAge) &&
      nodeVisibleAtKnowledgeAge(target, knowledgeAge)
    );
  });
}

/** Deterministic layout fingerprint for regression tests. */
export function projectionFingerprint(projection: BrainSpaceProjection): string {
  return projection.systems
    .map((system) => {
      const nodes = system.nodes
        .map((node) =>
          [
            node.source.id,
            node.domain,
            node.orbit.toFixed(4),
            node.phase.toFixed(4),
            node.speed.toFixed(8),
            node.ageFraction === null ? "UNMEASURED" : node.ageFraction.toFixed(6),
            node.status,
          ].join(":"),
        )
        .join("|");
      return `${system.domain}@${system.galRadius.toFixed(4)}/${system.angle.toFixed(4)}/${system.orbitSpeed.toFixed(8)}=>{${nodes}}`;
    })
    .join(";;");
}

export type BrainSpaceAnimationLoop = {
  start: () => void;
  stop: () => void;
  isRunning: () => boolean;
  getSimTime: () => number;
  setPaused: (paused: boolean) => void;
  getPaused: () => boolean;
};

export type BrainSpaceAnimationLoopOptions = {
  /** Called once per frame with (simTime, deltaMs, wallNow). */
  onFrame: (simTime: number, deltaMs: number, wallNow: number) => void;
  /** Orbit scale multiplier applied to delta_ms. */
  orbitScale?: number;
  /** Initial paused state (e.g. prefers-reduced-motion). */
  paused?: boolean;
  requestAnimationFrame?: typeof globalThis.requestAnimationFrame;
  cancelAnimationFrame?: typeof globalThis.cancelAnimationFrame;
};

/**
 * Production-safe RAF loop.
 * Exactly one chain while running; stop() cancels the handle.
 * Simulation time advances only when not paused.
 */
export function createBrainSpaceAnimationLoop(
  options: BrainSpaceAnimationLoopOptions,
): BrainSpaceAnimationLoop {
  const raf = options.requestAnimationFrame ?? globalThis.requestAnimationFrame.bind(globalThis);
  const caf = options.cancelAnimationFrame ?? globalThis.cancelAnimationFrame.bind(globalThis);
  const orbitScale = options.orbitScale ?? 3.2;

  let handle: number | null = null;
  let running = false;
  let paused = options.paused ?? false;
  let simTime = 0;
  let lastFrame = 0;

  const tick = (wallNow: number) => {
    if (!running) return;
    const delta = Math.min(40, Math.max(0, lastFrame ? wallNow - lastFrame : 0));
    lastFrame = wallNow;
    if (!paused) {
      simTime += delta * orbitScale;
    }
    options.onFrame(simTime, delta, wallNow);
    handle = raf(tick);
  };

  return {
    start() {
      if (running) return;
      running = true;
      lastFrame = 0;
      handle = raf(tick);
    },
    stop() {
      running = false;
      if (handle !== null) {
        caf(handle);
        handle = null;
      }
      lastFrame = 0;
    },
    isRunning() {
      return running;
    },
    getSimTime() {
      return simTime;
    },
    setPaused(next) {
      paused = next;
    },
    getPaused() {
      return paused;
    },
  };
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
