/**
 * Deterministic DNA / double-helix layout for Brain knowledge network.
 * Same node/edge set → same coordinates. No Math.random, no physics.
 */

import {
  categoryForNode,
  type BrainSemanticCategory,
} from "./brain-categories";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

export type DnaLaidOutNode = {
  id: string;
  label: string;
  type: string;
  category: BrainSemanticCategory;
  x: number;
  y: number;
  r: number;
  strand: 0 | 1;
  degree: number;
  focal: boolean;
};

export type DnaLaidOutEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  kind: "rung" | "strand" | "secondary";
  opacity: number;
};

export type DnaLayoutResult = {
  nodes: DnaLaidOutNode[];
  edges: DnaLaidOutEdge[];
  focalId: string | null;
  width: number;
  height: number;
};

export type DnaLayoutOptions = {
  width: number;
  height: number;
  /** Prefer this node as focal when present. */
  preferredFocalId?: string | null;
  /** Max primary nodes placed on the helix (bounded projection). */
  maxPrimary?: number;
};

function stableHash(input: string): number {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function degreeMap(edges: readonly LiveBrainEdge[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const edge of edges) {
    map.set(edge.source, (map.get(edge.source) ?? 0) + 1);
    map.set(edge.target, (map.get(edge.target) ?? 0) + 1);
  }
  return map;
}

function pickFocal(
  nodes: readonly LiveBrainNode[],
  degrees: Map<string, number>,
  preferredFocalId?: string | null,
): LiveBrainNode | null {
  if (!nodes.length) return null;
  if (preferredFocalId) {
    const preferred = nodes.find((n) => n.id === preferredFocalId);
    if (preferred) return preferred;
  }
  const leviathan = nodes.find((n) => /leviathan/i.test(n.label) || /leviathan/i.test(n.id));
  if (leviathan) return leviathan;
  let best = nodes[0];
  let bestDegree = degrees.get(best.id) ?? 0;
  for (const node of nodes) {
    const d = degrees.get(node.id) ?? 0;
    if (d > bestDegree || (d === bestDegree && node.id.localeCompare(best.id) < 0)) {
      best = node;
      bestDegree = d;
    }
  }
  return best;
}

function categoryRank(category: BrainSemanticCategory): number {
  switch (category) {
    case "agent":
      return 0;
    case "concept":
      return 1;
    case "entity":
      return 2;
    case "document":
      return 3;
    default:
      return 4;
  }
}

/**
 * Order remaining nodes by category + degree + stable id.
 */
function orderNodes(
  nodes: readonly LiveBrainNode[],
  degrees: Map<string, number>,
  focalId: string,
): LiveBrainNode[] {
  return [...nodes]
    .filter((n) => n.id !== focalId)
    .sort((a, b) => {
      const ca = categoryRank(categoryForNode(a));
      const cb = categoryRank(categoryForNode(b));
      if (ca !== cb) return ca - cb;
      const da = degrees.get(a.id) ?? 0;
      const db = degrees.get(b.id) ?? 0;
      if (db !== da) return db - da;
      return a.id.localeCompare(b.id);
    });
}

function radiusForDegree(degree: number, maxDegree: number, focal: boolean): number {
  if (focal) return 18;
  const t = maxDegree > 0 ? degree / maxDegree : 0;
  return 5 + t * 7;
}

/**
 * Project nodes onto a double helix with a bright central focal node.
 */
export function layoutDnaNetwork(
  nodes: readonly LiveBrainNode[],
  edges: readonly LiveBrainEdge[],
  options: DnaLayoutOptions,
): DnaLayoutResult {
  const width = Math.max(120, options.width || 800);
  const height = Math.max(120, options.height || 360);
  const maxPrimary = options.maxPrimary ?? 48;

  if (!nodes.length) {
    return { nodes: [], edges: [], focalId: null, width, height };
  }

  const degrees = degreeMap(edges);
  const focal = pickFocal(nodes, degrees, options.preferredFocalId);
  if (!focal) {
    return { nodes: [], edges: [], focalId: null, width, height };
  }

  const ordered = orderNodes(nodes, degrees, focal.id);
  const primary = ordered.slice(0, maxPrimary);
  const primaryIds = new Set(primary.map((n) => n.id));
  primaryIds.add(focal.id);

  const maxDegree = Math.max(1, ...[...degrees.values()]);
  const cx = width / 2;
  const cy = height / 2;
  const ampY = height * 0.36;
  const helixLen = width * 0.82;
  const startX = cx - helixLen / 2;

  const laid: DnaLaidOutNode[] = [
    {
      id: focal.id,
      label: focal.label,
      type: focal.type,
      category: categoryForNode(focal),
      x: cx,
      y: cy,
      r: radiusForDegree(degrees.get(focal.id) ?? 0, maxDegree, true),
      strand: 0,
      degree: degrees.get(focal.id) ?? 0,
      focal: true,
    },
  ];

  const n = Math.max(1, primary.length);
  const turns = 2.4;
  primary.forEach((node, index) => {
    const t = n === 1 ? 0.5 : index / (n - 1);
    const strand: 0 | 1 = (index % 2) as 0 | 1;
    const angle = t * Math.PI * 2 * turns + (strand === 0 ? 0 : Math.PI);
    const x = startX + t * helixLen;
    const y = cy + Math.sin(angle) * ampY;
    const pad = 28;
    // Deterministic micro-offset so equal-t nodes don't stack
    const jitter = (stableHash(node.id) % 1000) / 1000;
    const jx = (jitter - 0.5) * 8;
    const jy = ((stableHash(`${node.id}:y`) % 1000) / 1000 - 0.5) * 6;

    laid.push({
      id: node.id,
      label: node.label,
      type: node.type,
      category: categoryForNode(node),
      x: Math.min(width - pad, Math.max(pad, x + jx)),
      y: Math.min(height - pad, Math.max(pad, y + jy)),
      r: radiusForDegree(degrees.get(node.id) ?? 0, maxDegree, false),
      strand,
      degree: degrees.get(node.id) ?? 0,
      focal: false,
    });
  });

  const pos = new Map(laid.map((n) => [n.id, n]));
  const laidEdges: DnaLaidOutEdge[] = [];

  // Rungs: connect opposite-strand neighbors that share a real edge when possible
  for (let i = 0; i + 1 < primary.length; i += 2) {
    const a = primary[i];
    const b = primary[i + 1];
    if (!a || !b) continue;
    const real = edges.find(
      (e) =>
        (e.source === a.id && e.target === b.id) ||
        (e.source === b.id && e.target === a.id),
    );
    if (real) {
      laidEdges.push({
        id: real.id,
        source: a.id,
        target: b.id,
        relation: real.relation,
        kind: "rung",
        opacity: 0.85,
      });
    } else {
      // Visual rung only when both are primary — still keyed deterministically,
      // but marked secondary so we never invent backend relations as truth.
      laidEdges.push({
        id: `dna-rung:${a.id}:${b.id}`,
        source: a.id,
        target: b.id,
        relation: "projection",
        kind: "rung",
        opacity: 0.35,
      });
    }
  }

  // Strand-adjacent links + real secondary edges among primary nodes
  for (const edge of edges) {
    if (!primaryIds.has(edge.source) || !primaryIds.has(edge.target)) continue;
    if (!pos.has(edge.source) || !pos.has(edge.target)) continue;
    if (laidEdges.some((e) => e.id === edge.id)) continue;
    const a = pos.get(edge.source)!;
    const b = pos.get(edge.target)!;
    const sameStrand = a.strand === b.strand && !a.focal && !b.focal;
    const touchesFocal = a.focal || b.focal;
    laidEdges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      relation: edge.relation,
      kind: touchesFocal ? "strand" : sameStrand ? "strand" : "secondary",
      opacity: touchesFocal ? 0.7 : sameStrand ? 0.55 : 0.28,
    });
  }

  // Soft links from focal to a few high-degree primaries if no edges exist
  if (!edges.some((e) => e.source === focal.id || e.target === focal.id)) {
    const top = primary.slice(0, Math.min(6, primary.length));
    for (const node of top) {
      laidEdges.push({
        id: `dna-focal:${focal.id}:${node.id}`,
        source: focal.id,
        target: node.id,
        relation: "projection",
        kind: "strand",
        opacity: 0.4,
      });
    }
  }

  return {
    nodes: laid,
    edges: laidEdges,
    focalId: focal.id,
    width,
    height,
  };
}

/** Pure helper for tests — layout must be order-invariant given same set. */
export function layoutDnaNetworkStable(
  nodes: readonly LiveBrainNode[],
  edges: readonly LiveBrainEdge[],
  options: DnaLayoutOptions,
): DnaLayoutResult {
  const sortedNodes = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const sortedEdges = [...edges].sort((a, b) => a.id.localeCompare(b.id));
  return layoutDnaNetwork(sortedNodes, sortedEdges, options);
}
