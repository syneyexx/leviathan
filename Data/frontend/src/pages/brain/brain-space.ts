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

/** Hard visual bounds: data volume must not make the universe grow without limit. */
export const BRAIN_SPACE_MAX_NODE_ORBIT = 248;
/** Slow ambient drift — noticeable across seconds, never frantic. */
export const BRAIN_SPACE_MAX_NODE_SPEED = 0.000012;
export const BRAIN_SPACE_MAX_SYSTEM_SPEED = 0.000002;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

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
  return BRAIN_SPACE_DOMAINS.find((domain) => domain.toLowerCase() === raw) ?? null;
}

/** View classification only. Canonical backend ownership is never mutated. */
export function brainSpaceDomainForNode(node: LiveBrainNode): BrainSpaceDomain {
  const explicit = explicitDomain(node);
  if (explicit) return explicit;

  const type = node.type.toLowerCase();
  const label = node.label.toLowerCase();
  const combined = `${type} ${label}`;

  if (type.includes("dataset") || type.includes("data.") || type.includes("corpus")) return "Datasets";
  if (type.includes("research") || type === "project" || type === "run") return "Research";
  if (type === "agent" || type.includes("agent")) return "Agents";
  if (type === "model" || type.includes("model") || type.includes("llm")) return "Models";
  if (
    type.includes("capability") ||
    type.includes("mcp.") ||
    type === "tool" ||
    type === "workflow" ||
    type === "code" ||
    type === "module"
  ) return "Capabilities";
  if (type === "memory" || type === "conversation") return "Memory";
  if (type.includes("knowledge") || type === "concept" || type === "evidence" || type === "atlas") {
    if (
      type === "concept" &&
      ["trading", "strategy", "market", "backtest", "portfolio", "riskguard", "risk guard"].some((token) =>
        combined.includes(token),
      )
    ) return "Trading";
    return "Knowledge";
  }

  if (["trading", "market", "strategy", "backtest", "portfolio", "riskguard", "risk guard", "paper ledger"].some((token) => combined.includes(token))) return "Trading";
  if (["hypothesis", "experiment"].some((token) => combined.includes(token))) return "Research";
  if (["dataset", "corpus", "ohlcv", "tick archive"].some((token) => combined.includes(token))) return "Datasets";
  if (["orchestrator", "researcher", "verifier", "synthesizer"].some((token) => combined.includes(token))) return "Agents";
  if (["embedding model", "reranker"].some((token) => combined.includes(token))) return "Models";
  if (["browser", "provider"].some((token) => combined.includes(token))) return "Capabilities";
  if (["memory", "recall", "session"].some((token) => combined.includes(token))) return "Memory";
  if (["ontology", "entity graph"].some((token) => combined.includes(token))) return "Knowledge";
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
  if (node.meta?.archived === true || node.meta?.deprecated === true || node.meta?.retired === true) return true;
  return ["archived", "deprecated", "retired"].some(
    (token) => status === token || lifecycle === token || state === token,
  );
}

function statusForNode(node: LiveBrainNode): BrainSpaceNode["status"] {
  if (node.meta?.available === false) return "unavailable";
  const raw = normalizeText(node.meta?.status);
  if (!raw) return "unknown";
  if (["ready", "active", "healthy", "running", "available", "completed", "verified"].includes(raw)) return "ready";
  if (["degraded", "warning", "partial", "stale"].includes(raw)) return "degraded";
  if (["unavailable", "offline", "failed", "blocked", "disabled"].includes(raw)) return "unavailable";
  return "unknown";
}

function importanceForNode(node: LiveBrainNode, degree: number): number {
  const explicit = Number(node.meta?.importance ?? node.meta?.relevance);
  if (Number.isFinite(explicit)) return Math.max(0, Math.min(100, explicit));
  return Math.max(18, Math.min(100, 35 + Math.log2(degree + 1) * 14));
}

/**
 * Density-aware bounded packing. The old linear nodeIndex * 11 radius made a
 * 200-node domain exceed 2,000 world units. sqrt packing keeps every domain
 * reachable while retaining deterministic visual separation.
 */
function packedOrbit(nodeIndex: number, nodeId: string): number {
  if (nodeIndex <= 0) return 42 + seeded01(nodeId, "orbit-radius") * 5;
  const ring = Math.floor(Math.sqrt(nodeIndex));
  const jitter = seeded01(nodeId, "orbit-radius") * 5;
  return Math.min(BRAIN_SPACE_MAX_NODE_ORBIT, 48 + ring * 13 + jitter);
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
  for (const node of nodes) grouped.get(brainSpaceDomainForNode(node))?.push(node);

  const systems: BrainSpaceSystem[] = [];
  const byId = new Map<string, BrainSpaceNode>();
  const nonEmptyDomains = BRAIN_SPACE_DOMAINS.filter((domain) => (grouped.get(domain)?.length ?? 0) > 0);
  let archivedCount = 0;

  nonEmptyDomains.forEach((domain, systemIndex) => {
    const sourceNodes = grouped.get(domain) ?? [];
    const palette = BRAIN_SPACE_PALETTE[domain];
    const direction = systemIndex % 2 ? -1 : 1;
    const system: BrainSpaceSystem = {
      domain,
      palette,
      galRadius: 218 + (systemIndex % 3) * 34 + seeded01(domain, "gal-r") * 14,
      angle: (systemIndex / Math.max(1, nonEmptyDomains.length)) * Math.PI * 2 - 0.3,
      orbitSpeed: direction * (0.0000008 + seeded01(domain, "orbit") * 0.0000012),
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
        const speedDirection = seeded01(node.id, "direction") > 0.25 ? 1 : -1;

        const spaceNode: BrainSpaceNode = {
          source: node,
          domain,
          color: palette.planet,
          accent: styleSeed > 0.68 ? palette.sun : styleSeed > 0.38 ? "#FFFFFF" : palette.planet,
          radius: 3.8 + seeded01(node.id, "radius") * 4.2,
          orbit: packedOrbit(nodeIndex, node.id),
          phase: (nodeIndex * GOLDEN_ANGLE + seeded01(node.id, "phase") * 0.24) % (Math.PI * 2),
          speed: speedDirection * (0.000004 + seeded01(node.id, "speed") * 0.000008),
          tilt: (seeded01(node.id, "tilt") - 0.5) * 0.48,
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

export function nodeVisibleAtKnowledgeAge(node: BrainSpaceNode, knowledgeAge: number): boolean {
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
    return Boolean(
      source &&
        target &&
        nodeVisibleAtKnowledgeAge(source, knowledgeAge) &&
        nodeVisibleAtKnowledgeAge(target, knowledgeAge),
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
  onFrame: (simTime: number, deltaMs: number, wallNow: number) => void;
  /** Time multiplier. Default 1 = real millisecond simulation time. */
  orbitScale?: number;
  paused?: boolean;
  requestAnimationFrame?: typeof globalThis.requestAnimationFrame;
  cancelAnimationFrame?: typeof globalThis.cancelAnimationFrame;
};

/**
 * One bounded RAF chain.
 * - Frame deltas are hard-capped so tab-hidden gaps never simulate lost wall time.
 * - Resume resets the frame baseline so Pause→Resume never bursts sim time.
 */
export function createBrainSpaceAnimationLoop(
  options: BrainSpaceAnimationLoopOptions,
): BrainSpaceAnimationLoop {
  const raf = options.requestAnimationFrame ?? globalThis.requestAnimationFrame.bind(globalThis);
  const caf = options.cancelAnimationFrame ?? globalThis.cancelAnimationFrame.bind(globalThis);
  const orbitScale = Math.max(0, options.orbitScale ?? 1);
  let handle: number | null = null;
  let running = false;
  let paused = options.paused ?? false;
  let simTime = 0;
  let lastFrame = 0;

  const tick = (wallNow: number) => {
    if (!running) return;
    // Cap at one calm frame. Background tabs must not catch up on lost seconds.
    const delta = Math.min(32, Math.max(0, lastFrame ? wallNow - lastFrame : 0));
    lastFrame = wallNow;
    if (!paused) simTime += delta * orbitScale;
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
      if (handle !== null) caf(handle);
      handle = null;
      lastFrame = 0;
    },
    isRunning: () => running,
    getSimTime: () => simTime,
    setPaused(next) {
      paused = next;
      // Always drop the stale baseline (including same-state calls after tab focus).
      lastFrame = 0;
    },
    getPaused: () => paused,
  };
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
