"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import {
  hadesApi,
  type BrainLayout,
  type BrainLink,
  type BrainNode,
  type BrainResponse,
} from "@/lib/hades-api";

const BRAIN_KEY = "hades:brain";
const LAYOUT_KEY = "hades:brain-layout";

export function useHadesBrain(viewId = "default") {
  const brainQuery = useHadesQuery(
    `${BRAIN_KEY}:${viewId}`,
    async () => hadesApi.brain(viewId),
    { staleTime: 5_000, refetchInterval: 15_000 },
  );

  const layoutQuery = useHadesQuery(
    `${LAYOUT_KEY}:${viewId}`,
    async () => hadesApi.brainLayout(viewId),
    { staleTime: 10_000 },
  );

  const payload = brainQuery.data as BrainResponse | undefined;
  const layoutExtra = layoutQuery.data as BrainLayout | undefined;
  const layout = payload?.layout || layoutExtra;
  const nodes: BrainNode[] = payload?.nodes ?? [];
  const links: BrainLink[] = payload?.links ?? [];
  const counts = payload?.counts ?? { nodes: nodes.length, links: links.length };

  const refresh = useCallback(async () => {
    invalidateHadesQuery(`${BRAIN_KEY}:${viewId}`);
    invalidateHadesQuery(`${LAYOUT_KEY}:${viewId}`);
    await Promise.all([brainQuery.refetch(), layoutQuery.refetch()]);
  }, [brainQuery, layoutQuery, viewId]);

  const stats = useMemo(() => {
    const byKind: Record<string, number> = {};
    for (const node of nodes) {
      const kind = String(node.kind || "other").toLowerCase();
      byKind[kind] = (byKind[kind] || 0) + 1;
    }
    return {
      nodeCount: counts.nodes ?? nodes.length,
      linkCount: counts.links ?? links.length,
      memoryCount: byKind.memory || 0,
      knowledgeCount: (byKind.knowledge || 0) + (byKind.document || 0) + (byKind.note || 0),
      evidenceCount: byKind.evidence || 0,
      truncated: Boolean(counts.truncated),
      byKind,
    };
  }, [nodes, links, counts]);

  return {
    nodes,
    links,
    layout,
    counts,
    stats,
    relationKinds: payload?.relation_kinds ?? [],
    loading: brainQuery.status === "loading" && !brainQuery.data,
    error: brainQuery.error || layoutQuery.error,
    refresh,
    raw: payload,
  };
}
