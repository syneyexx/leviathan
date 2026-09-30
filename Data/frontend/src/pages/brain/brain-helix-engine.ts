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
  const r = Math.max(1, Math.min(h * 0.21, w * 0.18));
  const z = Math.sin(theta) * r;
  const depth = 780 / (780 - z);
  const mid = (range[0] + range[1]) / 2;
  const span = Math.max(1e-6, range[1] - range[0]);
  // Preserve the reference's proportions instead of stretching across ultrawide panels.
  const displayWidth = Math.min(w, h * (1100 / 485));
  const x = ((t - mid) / span) * Math.max(1, displayWidth - 80) * 0.82;
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
  return localNetworkPoints(allNodes, links, cfg).get(node.id)!;
}

function localNetworkPoints(nodes: readonly HelixNode[], links: readonly HelixLink[], cfg: HelixEngineConfig): Map<string, HelixPoint> {
  const visible = nodes.filter(cfg.filter);
  const ids = new Set(visible.map((n) => n.id));
  const focusId = cfg.selectedId && ids.has(cfg.selectedId) ? cfg.selectedId :
    [...cfg.activeIds].find((id) => ids.has(id)) ?? visible[0]?.id;
  const neighbors = new Set<string>();
  for (const e of links) {
    if (e.source === focusId) neighbors.add(e.target);
    if (e.target === focusId) neighbors.add(e.source);
  }
  const points = new Map<string, HelixPoint>();
  const w = cfg.width, h = cfg.height;
  if (focusId) points.set(focusId, { x: w / 2, y: h * 0.53, z: 0.6, scale: 1.3 });
  for (const related of [true, false]) {
    const group = visible.filter((n) => n.id !== focusId && neighbors.has(n.id) === related)
      .sort((a, b) => a.id.localeCompare(b.id));
    const rx = Math.max(1, w / 2 - 30) * (related ? 0.68 : 1);
    const ry = Math.max(1, h / 2 - 80) * (related ? 0.68 : 1);
    group.forEach((node, index) => {
      const phase = index / group.length * TAU - Math.PI / 2;
      points.set(node.id, { x: w / 2 + Math.cos(phase) * rx, y: h * 0.53 + Math.sin(phase) * ry, z: 0.2, scale: related ? 1.1 : 0.7 });
    });
  }
  return points;
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
  const network = cfg.morph > 0 ? localNetworkPoints(nodes, links, cfg) : null;
  return nodes.map((node) => {
    const helix = projectHelix(node.position, node.strand, cfg);
    const net = network?.get(node.id) ?? helix;
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
  const frontToBack = [...points].sort((a, b) => b.z - a.z);
  for (const p of frontToBack) {
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
