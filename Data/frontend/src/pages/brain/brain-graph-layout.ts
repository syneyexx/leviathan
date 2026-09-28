import { colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";

export type GraphPoint = { x: number; y: number };
export type PositionedGraphNode = LiveBrainNode & GraphPoint & {
  r: number;
  color: string;
  cluster: string;
  core: boolean;
};

export const GRAPH_BASE_WIDTH = 1000;
export const GRAPH_BASE_HEIGHT = 610;

/** Extra room per node so ~250 nodes stay readable without heavy overlap. */
export function graphCanvasSize(count: number): { width: number; height: number } {
  const expansion = Math.max(0, Math.sqrt(count) - 6);
  return {
    width: GRAPH_BASE_WIDTH + expansion * 210,
    height: GRAPH_BASE_HEIGHT + expansion * 145,
  };
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function clusterKeyForNode(node: LiveBrainNode): string {
  if (node.type === "capability" && typeof node.meta?.provider_kind === "string" && node.meta.provider_kind.trim()) {
    return `capability.${node.meta.provider_kind.trim().toLowerCase()}`;
  }
  return node.type;
}

function clusterColor(key: string, sample: LiveBrainNode): string {
  const base = colorForType(sample.type);
  if (!key.startsWith("capability.")) return base;
  const palette = ["#E6A13A", "#F0C875", "#E8794A", "#38C9D6", "#8D6EF4", "#42C58A"];
  return palette[hashString(key) % palette.length];
}

/**
 * Spatial-hash collision resolution. Neighbor checks only — O(n · k) instead of O(n²).
 * Tuned for graphs up to a few hundred nodes.
 */
export function resolveCollisionsSpatial(
  nodes: PositionedGraphNode[],
  options: { iterations?: number; cellSize?: number } = {},
): void {
  if (nodes.length < 2) return;
  const iterations = options.iterations ?? 24;
  let maxRadius = 8;
  for (const node of nodes) maxRadius = Math.max(maxRadius, node.r);
  const cellSize = Math.max(48, options.cellSize ?? maxRadius * 2 + 36);

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const grid = new Map<string, number[]>();
    for (let index = 0; index < nodes.length; index += 1) {
      const node = nodes[index];
      const cx = Math.floor(node.x / cellSize);
      const cy = Math.floor(node.y / cellSize);
      const key = `${cx}:${cy}`;
      const bucket = grid.get(key);
      if (bucket) bucket.push(index);
      else grid.set(key, [index]);
    }

    for (let aIndex = 0; aIndex < nodes.length; aIndex += 1) {
      const a = nodes[aIndex];
      const cx = Math.floor(a.x / cellSize);
      const cy = Math.floor(a.y / cellSize);
      for (let ox = -1; ox <= 1; ox += 1) {
        for (let oy = -1; oy <= 1; oy += 1) {
          const bucket = grid.get(`${cx + ox}:${cy + oy}`);
          if (!bucket) continue;
          for (const bIndex of bucket) {
            if (bIndex <= aIndex) continue;
            const b = nodes[bIndex];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distance = Math.hypot(dx, dy);
            const minimum = a.r + b.r + (a.core || b.core ? 58 : 36);
            if (distance >= minimum) continue;
            const angle =
              distance < 0.001
                ? ((hashString(a.id + b.id) % 360) * Math.PI) / 180
                : Math.atan2(dy, dx);
            const displacement = (minimum - distance) * 0.42;
            if (!a.core) {
              a.x -= Math.cos(angle) * displacement;
              a.y -= Math.sin(angle) * displacement;
            }
            if (!b.core) {
              b.x += Math.cos(angle) * displacement;
              b.y += Math.sin(angle) * displacement;
            }
          }
        }
      }
    }
  }
}

/** Deterministic force + spatial collision layout for the Technical Brain graph. */
export function buildBrainGraphLayout(
  nodes: LiveBrainNode[],
  edges: LiveBrainEdge[],
  physics: boolean,
  width: number,
  height: number,
): PositionedGraphNode[] {
  if (!nodes.length) return [];
  const center = { x: width / 2, y: height / 2 };
  const groups = new Map<string, LiveBrainNode[]>();
  for (const node of nodes) {
    const key = clusterKeyForNode(node);
    const group = groups.get(key) ?? [];
    group.push(node);
    groups.set(key, group);
  }
  const groupEntries = [...groups.entries()].sort(
    (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]),
  );
  const actualHub =
    nodes.find((node) => /leviathan/i.test(node.label)) ??
    nodes.find((node) => node.type === "atlas") ??
    null;
  const positioned: PositionedGraphNode[] = [];

  groupEntries.forEach(([key, group], groupIndex) => {
    const color = clusterColor(key, group[0]);
    const includesHub = actualHub ? group.some((node) => node.id === actualHub.id) : false;
    const nonHubIndex = includesHub ? Math.max(0, groupIndex - 1) : groupIndex;
    const nonHubCount = Math.max(1, groupEntries.length - (actualHub ? 1 : 0));
    const angle = (nonHubIndex / nonHubCount) * Math.PI * 2 - Math.PI / 2;
    // Wider inter-cluster orbit so clusters do not pile into the core.
    const orbit = Math.min(width, height) * (groupEntries.length < 3 ? 0.34 : 0.42);
    const groupCenter = includesHub
      ? center
      : {
          x: center.x + Math.cos(angle) * orbit,
          y: center.y + Math.sin(angle) * orbit * 0.82,
        };

    group.forEach((node, index) => {
      if (actualHub && node.id === actualHub.id) {
        positioned.push({ ...node, ...center, r: 34, color: "#E6BD58", cluster: key, core: true });
        return;
      }
      const seed = hashString(node.id);
      const localAngle = index * 2.399963229728653 + (seed % 29) * 0.014;
      // Increased intra-cluster spacing for readable ~250-node projections.
      const localRadius = index === 0 ? 0 : 58 + Math.sqrt(index) * 34;
      positioned.push({
        ...node,
        x: groupCenter.x + Math.cos(localAngle) * localRadius,
        y: groupCenter.y + Math.sin(localAngle) * localRadius,
        r: index === 0 ? Math.min(26, 14 + Math.sqrt(group.length) * 2.4) : 7 + Math.min(3, Math.log2(index + 2) * 0.65),
        color,
        cluster: key,
        core: false,
      });
    });
  });

  if (!physics || positioned.length > 500) return positioned;

  const byId = new Map(positioned.map((node) => [node.id, node]));
  for (let iteration = 0; iteration < 24; iteration += 1) {
    for (const edge of edges) {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b || a.core || b.core) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = a.cluster === b.cluster ? 148 : 340;
      const force = (distance - desired) * 0.008;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      a.x += fx;
      a.y += fy;
      b.x -= fx;
      b.y -= fy;
    }
    resolveCollisionsSpatial(positioned, { iterations: 1 });
  }
  return positioned;
}

/** Merge a fresh layout with operator-dragged positions that still exist. */
export function mergeDraggedGraphPositions(
  layout: PositionedGraphNode[],
  previous: Map<string, GraphPoint>,
  draggedIds: ReadonlySet<string>,
): Map<string, GraphPoint> {
  const next = new Map<string, GraphPoint>();
  for (const node of layout) {
    if (draggedIds.has(node.id) && previous.has(node.id)) {
      next.set(node.id, previous.get(node.id)!);
    } else {
      next.set(node.id, { x: node.x, y: node.y });
    }
  }
  return next;
}

export function layoutSpreadStats(nodes: PositionedGraphNode[]): {
  minPairDistance: number;
  clusterCenters: Map<string, GraphPoint>;
  minClusterDistance: number;
} {
  let minPairDistance = Number.POSITIVE_INFINITY;
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const distance = Math.hypot(nodes[j].x - nodes[i].x, nodes[j].y - nodes[i].y);
      if (distance < minPairDistance) minPairDistance = distance;
    }
  }
  if (!Number.isFinite(minPairDistance)) minPairDistance = 0;

  const sums = new Map<string, { x: number; y: number; count: number }>();
  for (const node of nodes) {
    if (node.core) continue;
    const row = sums.get(node.cluster) ?? { x: 0, y: 0, count: 0 };
    row.x += node.x;
    row.y += node.y;
    row.count += 1;
    sums.set(node.cluster, row);
  }
  const clusterCenters = new Map<string, GraphPoint>();
  for (const [key, row] of sums) {
    clusterCenters.set(key, { x: row.x / row.count, y: row.y / row.count });
  }

  let minClusterDistance = Number.POSITIVE_INFINITY;
  const centers = [...clusterCenters.values()];
  for (let i = 0; i < centers.length; i += 1) {
    for (let j = i + 1; j < centers.length; j += 1) {
      const distance = Math.hypot(centers[j].x - centers[i].x, centers[j].y - centers[i].y);
      if (distance < minClusterDistance) minClusterDistance = distance;
    }
  }
  if (!Number.isFinite(minClusterDistance)) minClusterDistance = 0;

  return { minPairDistance, clusterCenters, minClusterDistance };
}
