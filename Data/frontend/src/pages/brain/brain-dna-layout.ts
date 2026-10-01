/**
 * Deterministic DNA / double-helix layout for Brain knowledge network.
 * Screen 1 geometry: two luminous sinusoidal strands, paired rungs,
 * focal node at helix center. Same input → same coordinates.
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
  /** Pair index along the helix (0 … nPairs-1). Focal uses -1. */
  pairIndex: number;
  /** Normalized position along helix length [0,1]. */
  t: number;
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

export type DnaHelixPath = {
  strand0: string;
  strand1: string;
};

export type DnaLayoutResult = {
  nodes: DnaLaidOutNode[];
  edges: DnaLaidOutEdge[];
  helix: DnaHelixPath;
  focalId: string | null;
  width: number;
  height: number;
};

export type DnaLayoutOptions = {
  width: number;
  height: number;
  preferredFocalId?: string | null;
  maxPrimary?: number;
  /** Helix turns across the canvas (Screen 1 ≈ 2.0–2.5). */
  turns?: number;
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
  const named = nodes.find(
    (n) =>
      /ai\s*agents?/i.test(n.label) ||
      /leviathan/i.test(n.label) ||
      /leviathan/i.test(n.id),
  );
  if (named) return named;
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
    case "unclassified":
      return 4;
    default:
      return 5;
  }
}

function orderNodes(
  nodes: readonly LiveBrainNode[],
  degrees: Map<string, number>,
  focalId: string,
): LiveBrainNode[] {
  return [...nodes]
    .filter((n) => n.id !== focalId)
    .sort((a, b) => {
      // Prefer named Screen-1 labels over generic "Node N" filler
      const ga = /^Node \d+$/i.test(a.label) ? 1 : 0;
      const gb = /^Node \d+$/i.test(b.label) ? 1 : 0;
      if (ga !== gb) return ga - gb;
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
  if (focal) return 16;
  const t = maxDegree > 0 ? degree / maxDegree : 0;
  return 4.5 + t * 6.5;
}

/** Classic DNA: strand 0 and strand 1 are π out of phase. */
export function helixPoint(
  t: number,
  strand: 0 | 1,
  opts: { startX: number; helixLen: number; cy: number; ampY: number; turns: number },
): { x: number; y: number } {
  const angle = t * Math.PI * 2 * opts.turns + (strand === 0 ? 0 : Math.PI);
  return {
    x: opts.startX + t * opts.helixLen,
    y: opts.cy + Math.sin(angle) * opts.ampY,
  };
}

/**
 * Pair positions along the helix for Screen 1 rungs.
 * Centers each pair in its segment so nodes sit at ladder rungs,
 * not at the tip crossings (t=0 / t=1) where strands meet.
 */
export function pairParam(pairIndex: number, nPairs: number): number {
  if (nPairs <= 1) return 0.5;
  return (pairIndex + 0.5) / nPairs;
}

/**
 * If a sample lands near a zero-crossing of the sine, nudge toward
 * the nearest peak so rung partners stay vertically separated.
 */
export function nudgeOffCrossing(t: number, turns: number): number {
  const angle = t * Math.PI * 2 * turns;
  const s = Math.sin(angle);
  if (Math.abs(s) >= 0.28) return Math.min(1, Math.max(0, t));
  const step = 0.05 / Math.max(1, turns);
  const tPlus = Math.min(1, t + step);
  const tMinus = Math.max(0, t - step);
  const sPlus = Math.abs(Math.sin(tPlus * Math.PI * 2 * turns));
  const sMinus = Math.abs(Math.sin(tMinus * Math.PI * 2 * turns));
  return sPlus >= sMinus ? tPlus : tMinus;
}

/** Smooth SVG path through sampled helix points. */
export function buildHelixPath(
  strand: 0 | 1,
  opts: { startX: number; helixLen: number; cy: number; ampY: number; turns: number },
  samples = 80,
): string {
  const parts: string[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const { x, y } = helixPoint(t, strand, opts);
    parts.push(`${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return parts.join(" ");
}

function findEdge(
  edges: readonly LiveBrainEdge[],
  a: string,
  b: string,
): LiveBrainEdge | undefined {
  return edges.find(
    (e) => (e.source === a && e.target === b) || (e.source === b && e.target === a),
  );
}

/**
 * Project nodes onto a Screen-1 DNA double helix.
 */
export function layoutDnaNetwork(
  nodes: readonly LiveBrainNode[],
  edges: readonly LiveBrainEdge[],
  options: DnaLayoutOptions,
): DnaLayoutResult {
  const width = Math.max(120, options.width || 800);
  const height = Math.max(120, options.height || 360);
  const maxPrimary = options.maxPrimary ?? 36;
  const turns = options.turns ?? 2.15;

  const emptyHelix: DnaHelixPath = { strand0: "", strand1: "" };

  if (!nodes.length) {
    return { nodes: [], edges: [], helix: emptyHelix, focalId: null, width, height };
  }

  const degrees = degreeMap(edges);
  const focal = pickFocal(nodes, degrees, options.preferredFocalId);
  if (!focal) {
    return { nodes: [], edges: [], helix: emptyHelix, focalId: null, width, height };
  }

  const ordered = orderNodes(nodes, degrees, focal.id);
  // Even count so every rung has two strand partners
  let primary = ordered.slice(0, maxPrimary);
  if (primary.length % 2 === 1) primary = primary.slice(0, primary.length - 1);
  const primaryIds = new Set(primary.map((n) => n.id));
  primaryIds.add(focal.id);

  const maxDegree = Math.max(1, ...[...degrees.values()]);
  const cx = width / 2;
  const cy = height / 2;
  const ampY = height * 0.34;
  const helixLen = width * 0.84;
  const startX = (width - helixLen) / 2;
  const helixOpts = { startX, helixLen, cy, ampY, turns };
  const pad = 22;

  const helix: DnaHelixPath = {
    strand0: buildHelixPath(0, helixOpts),
    strand1: buildHelixPath(1, helixOpts),
  };

  const nPairs = Math.max(1, Math.floor(primary.length / 2));
  const laid: DnaLaidOutNode[] = [];

  // Focal sits at helix center (between strands at the mid crossing)
  laid.push({
    id: focal.id,
    label: focal.label,
    type: focal.type,
    category: categoryForNode(focal),
    x: cx,
    y: cy,
    r: radiusForDegree(degrees.get(focal.id) ?? 0, maxDegree, true),
    strand: 0,
    pairIndex: -1,
    t: 0.5,
    degree: degrees.get(focal.id) ?? 0,
    focal: true,
  });

  primary.forEach((node, index) => {
    const strand: 0 | 1 = (index % 2) as 0 | 1;
    const pairIndex = Math.floor(index / 2);
    const t = nudgeOffCrossing(pairParam(pairIndex, nPairs), turns);
    const { x, y } = helixPoint(t, strand, helixOpts);
    // Tiny deterministic jitter keeps overlapping ids readable without breaking helix shape
    const j = (stableHash(node.id) % 1000) / 1000;
    const jx = (j - 0.5) * 2.5;
    const jy = ((stableHash(`${node.id}:y`) % 1000) / 1000 - 0.5) * 2.5;

    laid.push({
      id: node.id,
      label: node.label,
      type: node.type,
      category: categoryForNode(node),
      x: Math.min(width - pad, Math.max(pad, x + jx)),
      y: Math.min(height - pad, Math.max(pad, y + jy)),
      r: radiusForDegree(degrees.get(node.id) ?? 0, maxDegree, false),
      strand,
      pairIndex,
      t,
      degree: degrees.get(node.id) ?? 0,
      focal: false,
    });
  });

  const pos = new Map(laid.map((n) => [n.id, n]));
  const laidEdges: DnaLaidOutEdge[] = [];
  const usedEdgeIds = new Set<string>();

  // 1) Rungs — opposite-strand partners at the same pair index (DNA base pairs)
  for (let pair = 0; pair < nPairs; pair += 1) {
    const a = primary[pair * 2];
    const b = primary[pair * 2 + 1];
    if (!a || !b) continue;
    const real = findEdge(edges, a.id, b.id);
    if (real) {
      usedEdgeIds.add(real.id);
      laidEdges.push({
        id: real.id,
        source: a.id,
        target: b.id,
        relation: real.relation,
        kind: "rung",
        opacity: 0.9,
      });
    } else {
      laidEdges.push({
        id: `dna-rung:${a.id}:${b.id}`,
        source: a.id,
        target: b.id,
        relation: "projection",
        kind: "rung",
        opacity: 0.55,
      });
    }
  }

  // 2) Strand links — consecutive nodes on the same strand
  for (const strand of [0, 1] as const) {
    const strandNodes = laid
      .filter((n) => !n.focal && n.strand === strand)
      .sort((a, b) => a.pairIndex - b.pairIndex);
    for (let i = 0; i < strandNodes.length - 1; i += 1) {
      const a = strandNodes[i];
      const b = strandNodes[i + 1];
      const real = findEdge(edges, a.id, b.id);
      if (real && !usedEdgeIds.has(real.id)) {
        usedEdgeIds.add(real.id);
        laidEdges.push({
          id: real.id,
          source: a.id,
          target: b.id,
          relation: real.relation,
          kind: "strand",
          opacity: 0.7,
        });
      } else if (!real) {
        laidEdges.push({
          id: `dna-strand:${a.id}:${b.id}`,
          source: a.id,
          target: b.id,
          relation: "projection",
          kind: "strand",
          opacity: 0.35,
        });
      }
    }
  }

  // 3) Focal bridges — only to a few nearby helix nodes (not a star)
  const nearFocal = laid
    .filter((n) => !n.focal)
    .sort((a, b) => Math.abs(a.t - 0.5) - Math.abs(b.t - 0.5) || a.id.localeCompare(b.id))
    .slice(0, 6);
  for (const node of nearFocal) {
    const real = findEdge(edges, focal.id, node.id);
    if (real && !usedEdgeIds.has(real.id)) {
      usedEdgeIds.add(real.id);
      laidEdges.push({
        id: real.id,
        source: focal.id,
        target: node.id,
        relation: real.relation,
        kind: "strand",
        opacity: 0.65,
      });
    } else if (!real) {
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

  // 4) Remaining real edges — faint secondary (keep helix silhouette; no star burst)
  for (const edge of edges) {
    if (usedEdgeIds.has(edge.id)) continue;
    if (!primaryIds.has(edge.source) || !primaryIds.has(edge.target)) continue;
    if (!pos.has(edge.source) || !pos.has(edge.target)) continue;
    const a = pos.get(edge.source)!;
    const b = pos.get(edge.target)!;
    // Skip long-distance links that would destroy the helix silhouette
    if (Math.abs(a.t - b.t) > 0.28 && !a.focal && !b.focal) continue;
    if (a.focal || b.focal) continue; // focal already has dedicated bridges
    laidEdges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      relation: edge.relation,
      kind: "secondary",
      opacity: 0.14,
    });
  }

  return {
    nodes: laid,
    edges: laidEdges,
    helix,
    focalId: focal.id,
    width,
    height,
  };
}

export function layoutDnaNetworkStable(
  nodes: readonly LiveBrainNode[],
  edges: readonly LiveBrainEdge[],
  options: DnaLayoutOptions,
): DnaLayoutResult {
  const sortedNodes = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const sortedEdges = [...edges].sort((a, b) => a.id.localeCompare(b.id));
  return layoutDnaNetwork(sortedNodes, sortedEdges, options);
}
