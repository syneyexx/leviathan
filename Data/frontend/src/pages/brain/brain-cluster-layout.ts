import type { ClusterRow } from "./brain-live";

export type ClusterPoint = { x: number; y: number };

export const CLUSTER_MAP_WIDTH = 900;
export const CLUSTER_MAP_HEIGHT = 410;
export const CLUSTER_MAP_TOP_N = 10;

/**
 * Canonical top-N bodies for the map. Selection never mutates this set —
 * that keeps layout positions stable when the operator clicks a cluster.
 */
export function canonicalMapClusters(
  clusters: readonly ClusterRow[],
  topN: number = CLUSTER_MAP_TOP_N,
): ClusterRow[] {
  return clusters.slice(0, Math.max(0, topN));
}

/**
 * Bodies actually drawn: canonical top-N plus the selected cluster when it
 * would otherwise be hidden by the visual bound.
 */
export function visibleMapClusters(
  canonical: readonly ClusterRow[],
  selected: ClusterRow | null,
): ClusterRow[] {
  if (!selected) return [...canonical];
  if (canonical.some((cluster) => cluster.id === selected.id)) return [...canonical];
  return [...canonical, selected];
}

/** Deterministic layout keyed only by stable canonical IDs (not selection). */
export function layoutClusterPositions(
  canonical: readonly Pick<ClusterRow, "id">[],
): Map<string, ClusterPoint> {
  const map = new Map<string, ClusterPoint>();
  if (!canonical.length) return map;
  const anchor = canonical[0];
  map.set(anchor.id, { x: CLUSTER_MAP_WIDTH / 2, y: CLUSTER_MAP_HEIGHT / 2 });
  const others = canonical.slice(1);
  others.forEach((cluster, index) => {
    const angle = (index / Math.max(1, others.length)) * Math.PI * 2 - Math.PI / 2;
    const ring = others.length > 7 && index >= 5 ? 1 : 0;
    const xRadius = ring ? 230 : 315;
    const yRadius = ring ? 112 : 150;
    const phase = ring ? Math.PI / Math.max(1, others.length) : 0;
    map.set(cluster.id, {
      x: CLUSTER_MAP_WIDTH / 2 + Math.cos(angle + phase) * xRadius,
      y: CLUSTER_MAP_HEIGHT / 2 + Math.sin(angle + phase) * yRadius,
    });
  });
  return map;
}

/** Parking slot for a selected cluster that sits outside the top-N visual bound. */
export function overflowClusterPosition(selectedId: string): ClusterPoint {
  let hash = 2166136261;
  for (let i = 0; i < selectedId.length; i += 1) {
    hash ^= selectedId.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const t = (hash >>> 0) % 1000;
  const angle = (t / 1000) * Math.PI * 2;
  return {
    x: CLUSTER_MAP_WIDTH / 2 + Math.cos(angle) * 360,
    y: CLUSTER_MAP_HEIGHT / 2 + Math.sin(angle) * 175,
  };
}

export function resolveClusterPosition(
  id: string,
  dragged: ReadonlyMap<string, ClusterPoint>,
  layout: ReadonlyMap<string, ClusterPoint>,
): ClusterPoint | null {
  if (dragged.has(id)) return dragged.get(id)!;
  if (layout.has(id)) return layout.get(id)!;
  return overflowClusterPosition(id);
}

/** Drop dragged offsets for clusters that no longer exist in the projection. */
export function pruneDraggedPositions(
  dragged: ReadonlyMap<string, ClusterPoint>,
  validIds: ReadonlySet<string>,
): Map<string, ClusterPoint> {
  let changed = false;
  const next = new Map<string, ClusterPoint>();
  for (const [id, point] of dragged) {
    if (validIds.has(id)) next.set(id, point);
    else changed = true;
  }
  return changed ? next : new Map(dragged);
}

export function clusterIds(clusters: readonly Pick<ClusterRow, "id">[]): Set<string> {
  return new Set(clusters.map((cluster) => cluster.id));
}
