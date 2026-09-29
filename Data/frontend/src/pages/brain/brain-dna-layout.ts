import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

export type DnaRenderNode = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  r: number;
  color: string;
  strand: 0 | 1;
  degree: number;
  showLabel: boolean;
};

export type DnaSemanticEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

export type DnaScaffoldSegment = {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  kind: "backbone" | "rung";
};

export type DnaLayout = {
  width: number;
  height: number;
  nodes: DnaRenderNode[];
  semanticEdges: DnaSemanticEdge[];
  scaffold: DnaScaffoldSegment[];
  centerNodeId: string | null;
};

const DEFAULT_MAX_LABELS = 12;
const PADDING = 48;
const HELIX_TURNS = 2.5;
const BASE_RADIUS = 6;
const MAX_RADIUS = 14;

function stableSortNodes(nodes: LiveBrainNode[]): LiveBrainNode[] {
  return nodes.slice().sort((a, b) => a.id.localeCompare(b.id));
}

function computeDegrees(nodes: LiveBrainNode[], edges: LiveBrainEdge[]): Map<string, number> {
  const degrees = new Map<string, number>();
  for (const node of nodes) degrees.set(node.id, 0);
  for (const edge of edges) {
    if (degrees.has(edge.source)) degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    if (degrees.has(edge.target)) degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }
  return degrees;
}

function pickCenterId(
  nodes: LiveBrainNode[],
  degrees: Map<string, number>,
  selectedId?: string | null,
): string | null {
  if (!nodes.length) return null;
  if (selectedId && nodes.some((node) => node.id === selectedId)) return selectedId;
  let bestId = nodes[0].id;
  let bestDegree = degrees.get(bestId) ?? 0;
  for (const node of nodes) {
    const degree = degrees.get(node.id) ?? 0;
    if (degree > bestDegree || (degree === bestDegree && node.id.localeCompare(bestId) < 0)) {
      bestId = node.id;
      bestDegree = degree;
    }
  }
  return bestId;
}

function nodeRadius(degree: number, maxDegree: number, isCenter: boolean): number {
  const t = maxDegree > 0 ? degree / maxDegree : 0;
  const r = BASE_RADIUS + t * (MAX_RADIUS - BASE_RADIUS);
  return isCenter ? Math.min(MAX_RADIUS + 2, r + 2) : r;
}

/**
 * Deterministic DNA / double-helix layout for LiveBrainNode[] + LiveBrainEdge[].
 * Scaffold segments are decorative only; semanticEdges mirror real graph edges.
 */
export function buildDnaLayout(opts: {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  width: number;
  height: number;
  selectedId?: string | null;
  colorForType: (type: string) => string;
  maxLabels?: number;
}): DnaLayout {
  const { width, height, selectedId = null, colorForType } = opts;
  const maxLabels = opts.maxLabels ?? DEFAULT_MAX_LABELS;

  if (!opts.nodes.length) {
    return {
      width,
      height,
      nodes: [],
      semanticEdges: [],
      scaffold: [],
      centerNodeId: null,
    };
  }

  const sorted = stableSortNodes(opts.nodes);
  const degrees = computeDegrees(sorted, opts.edges);
  const centerNodeId = pickCenterId(sorted, degrees, selectedId);
  const maxDegree = Math.max(0, ...degrees.values());
  const n = sorted.length;
  const midY = height / 2;
  const amp = Math.max(28, Math.min(height * 0.32, height / 2 - PADDING));
  const span = Math.max(1, width - 2 * PADDING);

  const placed: DnaRenderNode[] = sorted.map((node, i) => {
    const t = n === 1 ? 0.5 : i / (n - 1);
    const strand: 0 | 1 = (i % 2 === 0 ? 0 : 1);
    const phase = strand === 0 ? 0 : Math.PI;
    const x = PADDING + t * span;
    const y = midY + amp * Math.sin(2 * Math.PI * HELIX_TURNS * t + phase);
    const degree = degrees.get(node.id) ?? 0;
    const isCenter = node.id === centerNodeId;
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      x,
      y,
      r: nodeRadius(degree, maxDegree, isCenter),
      color: colorForType(node.type),
      strand,
      degree,
      showLabel: false,
    };
  });

  const labelIds = new Set<string>();
  if (selectedId && placed.some((node) => node.id === selectedId)) labelIds.add(selectedId);
  if (centerNodeId) labelIds.add(centerNodeId);
  const byDegree = placed
    .slice()
    .sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id));
  for (const node of byDegree) {
    if (labelIds.size >= maxLabels) break;
    labelIds.add(node.id);
  }
  for (const node of placed) {
    node.showLabel = labelIds.has(node.id);
  }

  const scaffold: DnaScaffoldSegment[] = [];
  const strand0 = placed.filter((node) => node.strand === 0);
  const strand1 = placed.filter((node) => node.strand === 1);

  for (let i = 0; i < strand0.length - 1; i += 1) {
    const a = strand0[i];
    const b = strand0[i + 1];
    scaffold.push({
      id: `scaffold:backbone:0:${a.id}:${b.id}`,
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      kind: "backbone",
    });
  }
  for (let i = 0; i < strand1.length - 1; i += 1) {
    const a = strand1[i];
    const b = strand1[i + 1];
    scaffold.push({
      id: `scaffold:backbone:1:${a.id}:${b.id}`,
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      kind: "backbone",
    });
  }

  const rungCount = Math.min(strand0.length, strand1.length);
  const rungStep = Math.max(1, Math.floor(rungCount / Math.max(1, Math.min(rungCount, 12))));
  for (let i = 0; i < rungCount; i += rungStep) {
    const a = strand0[i];
    const b = strand1[i];
    if (!a || !b) continue;
    scaffold.push({
      id: `scaffold:rung:${a.id}:${b.id}`,
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      kind: "rung",
    });
  }

  const semanticEdges: DnaSemanticEdge[] = opts.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    relation: edge.relation,
  }));

  return {
    width,
    height,
    nodes: placed,
    semanticEdges,
    scaffold,
    centerNodeId,
  };
}
