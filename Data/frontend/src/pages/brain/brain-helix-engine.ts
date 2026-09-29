/**
 * Pure spatial helix / local-network projection for Brain Kennis Netwerk.
 * Extracted from the Research Memory demo renderer — no globals, injectable config.
 * Geometry is visual ordering; only real edges are content relations.
 */

const TAU = Math.PI * 2;

export type HelixStrandRole = "source" | "insight" | "unknown";

export type HelixNode = {
  id: string;
  label: string;
  type: string;
  /** Stable slot along helix [0, 1]. */
  position: number;
  strand: 0 | 1;
  strandRole: HelixStrandRole;
  meta?: Record<string, unknown>;
};

export type HelixLink = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

export type HelixPoint = {
  x: number;
  y: number;
  z: number;
  scale: number;
};

export type HelixEngineConfig = {
  width: number;
  height: number;
  angle: number;
  tilt: number;
  zoom: number;
  twist: number;
  morph: number;
  range: readonly [number, number];
  selectedId: string | null;
  activeIds: ReadonlySet<string>;
  filter: (node: HelixNode) => boolean;
};

export type ProjectedNode = HelixPoint & {
  node: HelixNode;
  r: number;
};

export type ProjectedEdge = {
  link: HelixLink;
  a: HelixPoint;
  b: HelixPoint;
  z: number;
};

function stableHash(input: string): number {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** Map backend type → strand meaning. Unknown types stay labeled unknown. */
export function strandRoleForType(type: string): HelixStrandRole {
  const t = type.toLowerCase();
  if (
    t.includes("hypothesis") ||
    t.includes("finding") ||
    t.includes("insight") ||
    t.includes("claim") ||
    t === "concept" ||
    t.startsWith("concept.") ||
    t === "research.project" ||
    t.includes("conclusion")
  ) {
    return "insight";
  }
  if (
    t === "knowledge.document" ||
    t === "evidence" ||
    t.startsWith("evidence.") ||
    t.includes("document") ||
    t.includes("source") ||
    t === "dataset" ||
    t === "memory" ||
    t.startsWith("memory.") ||
    t === "atlas" ||
    t.includes("observation")
  ) {
    return "source";
  }
  return "unknown";
}

export function strandIndexForRole(role: HelixStrandRole, id: string): 0 | 1 {
  if (role === "source") return 0;
  if (role === "insight") return 1;
  return (stableHash(id) % 2) as 0 | 1;
}

/**
 * Assign stable helix slots. Filtering must not reshuffle surviving ids —
 * positions are derived from id hash + type, not filter order.
 */
export function assignStableHelixSlots(
  nodes: readonly { id: string; label: string; type: string; meta?: Record<string, unknown> }[],
): HelixNode[] {
  return nodes.map((n) => {
    const role = strandRoleForType(n.type);
    const strand = strandIndexForRole(role, n.id);
    const position = (stableHash(`helix:${n.id}`) % 10_000) / 10_000;
    return {
      id: n.id,
      label: n.label,
      type: n.type,
      position,
      strand,
      strandRole: role,
      meta: n.meta,
    };
  });
}

export function projectHelix(
  t: number,
  strand: 0 | 1,
  cfg: Pick<HelixEngineConfig, "width" | "height" | "angle" | "tilt" | "zoom" | "twist" | "range">,
): HelixPoint {
  const { width: w, height: h, angle, tilt, zoom, twist, range } = cfg;
  const theta = t * TAU * twist + angle + strand * Math.PI;
  const r = Math.min(h * 0.225, w * 0.18);
  const z = Math.sin(theta) * r;
  const depth = 780 / (780 - z);
  const mid = (range[0] + range[1]) / 2;
  const span = Math.max(1e-6, range[1] - range[0]);
  const x = ((t - mid) / span) * w * 0.83;
  const y = Math.cos(theta) * r;
  return {
    x: w * 0.5 + (x * Math.cos(tilt) - y * Math.sin(tilt)) * depth * zoom,
    y: h * 0.53 + (x * Math.sin(tilt) + y * Math.cos(tilt)) * depth * zoom,
    z: z / r,
    scale: depth * zoom,
  };
}

export function projectLocalNetwork(
  node: HelixNode,
  allNodes: readonly HelixNode[],
  links: readonly HelixLink[],
  cfg: HelixEngineConfig,
): HelixPoint {
  const focusId = cfg.selectedId ?? [...cfg.activeIds][0] ?? allNodes.find((n) => cfg.filter(n))?.id ?? null;
  const neighbors = new Set<string>();
  if (focusId) {
    for (const e of links) {
      if (e.source === focusId) neighbors.add(e.target);
      if (e.target === focusId) neighbors.add(e.source);
    }
  }
  const w = cfg.width;
  const h = cfg.height;
  if (focusId && node.id === focusId) {
    return { x: w * 0.5, y: h * 0.53, z: 0.6, scale: 1.3 };
  }
  const related = neighbors.has(node.id);
  const group = related
    ? allNodes.filter((n) => neighbors.has(n.id)).sort((a, b) => a.id.localeCompare(b.id))
    : allNodes
        .filter((n) => n.id !== focusId && !neighbors.has(n.id))
        .sort((a, b) => a.id.localeCompare(b.id));
  const index = Math.max(0, group.findIndex((n) => n.id === node.id));
  const phase = (index / Math.max(group.length, 1)) * TAU - Math.PI / 2;
  const radius = related ? Math.min(w * 0.29, h * 0.29) : Math.min(w * 0.42, h * 0.39);
  return {
    x: w * 0.5 + Math.cos(phase) * radius * 1.45,
    y: h * 0.53 + Math.sin(phase) * radius,
    z: 0.2,
    scale: related ? 1.1 : 0.7,
  };
}

export function lerpPoint(a: HelixPoint, b: HelixPoint, t: number): HelixPoint {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    z: a.z + (b.z - a.z) * t,
    scale: a.scale + (b.scale - a.scale) * t,
  };
}

export function projectNodes(
  nodes: readonly HelixNode[],
  links: readonly HelixLink[],
  cfg: HelixEngineConfig,
): ProjectedNode[] {
  return nodes.map((node) => {
    const helix = projectHelix(node.position, node.strand, cfg);
    const net = projectLocalNetwork(node, nodes, links, cfg);
    const p = lerpPoint(helix, net, cfg.morph);
    return { ...p, node, r: 5.3 };
  });
}

export function hitTestNode(
  points: readonly ProjectedNode[],
  x: number,
  y: number,
  filter: (node: HelixNode) => boolean,
): ProjectedNode | null {
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const p = points[i];
    if (!filter(p.node)) continue;
    if (Math.hypot(p.x - x, p.y - y) < Math.max(12, p.r + 5)) return p;
  }
  return null;
}

export function hitTestEdge(
  segments: readonly ProjectedEdge[],
  x: number,
  y: number,
  threshold = 6,
): HelixLink | null {
  for (const seg of segments) {
    const { a, b } = seg;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = dx * dx + dy * dy;
    if (!d) continue;
    const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / d));
    if (Math.hypot(x - a.x - t * dx, y - a.y - t * dy) < threshold) return seg.link;
  }
  return null;
}

export function focusAngleForNode(node: HelixNode, twist: number): number {
  return Math.PI / 2 - node.position * TAU * twist - node.strand * Math.PI;
}

export function shortestAngleDelta(from: number, to: number): number {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

/** Claim-evidence vocabulary — keep intact; do not collapse to true/false. */
export const CLAIM_EVIDENCE_RELATIONS = new Set([
  "SUPPORTS",
  "CONTRADICTS",
  "QUALIFIES",
  "BACKGROUND",
  "INSUFFICIENT",
  "supports",
  "contradicts",
  "qualifies",
  "background",
  "insufficient",
  "evidenced_by",
]);

export function isClaimEvidenceRelation(relation: string): boolean {
  return CLAIM_EVIDENCE_RELATIONS.has(relation) || CLAIM_EVIDENCE_RELATIONS.has(relation.toUpperCase());
}
