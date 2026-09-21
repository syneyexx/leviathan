"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type KnowledgeSource } from "@/lib/hades-api";

const KEY = "hades:knowledge";

function metaOf(source: KnowledgeSource): Record<string, unknown> {
  return (source.metadata && typeof source.metadata === "object" ? source.metadata : {}) as Record<string, unknown>;
}

export function useHadesKnowledge() {
  const query = useHadesQuery(
    KEY,
    async () => hadesApi.knowledge(),
    { staleTime: 5_000, refetchInterval: 12_000 },
  );

  const sources = query.data?.sources ?? [];
  const stats = query.data?.stats;

  const refresh = useCallback(async () => {
    invalidateHadesQuery(KEY);
    return query.refetch();
  }, [query]);

  const docs = useMemo(
    () =>
      sources.map((source: KnowledgeSource) => {
        const meta = metaOf(source);
        const statusRaw = String(source.status || "").toLowerCase();
        const status =
          statusRaw.includes("ready") || statusRaw.includes("index")
            ? ("indexed" as const)
            : statusRaw.includes("fail") || statusRaw.includes("error")
              ? ("failed" as const)
              : ("processing" as const);
        const uri = String(source.uri || source.local_path || meta.path || "");
        const type = uri.startsWith("http")
          ? "WEB"
          : uri.toLowerCase().endsWith(".md")
            ? "MD"
            : String(source.source_type || "FILE").toUpperCase().includes("MD")
              ? "MD"
              : "FILE";
        const chunkCount =
          typeof meta.chunk_count === "number"
            ? meta.chunk_count
            : typeof meta.chunks === "number"
              ? meta.chunks
              : null;
        return {
          id: source.id,
          name: source.title || String(meta.filename || "") || source.id,
          meta: uri || String(meta.collection || "—"),
          type,
          typeTone: type === "WEB" ? "cyan" : type === "MD" ? "gold" : "blue",
          collection: String(meta.collection || "Algemeen"),
          collectionTone: "blue",
          status,
          statusLabel: status === "indexed" ? "Geïndexeerd" : status === "failed" ? "Mislukt" : "Bezig",
          chunks: chunkCount,
          updated: source.updated_at || source.created_at || "—",
          raw: source,
        };
      }),
    [sources],
  );

  return {
    sources,
    docs,
    stats,
    loading: query.status === "loading" && !query.data,
    error: query.error,
    refresh,
    deleteSource: async (id: string) => {
      const api = hadesApi as typeof hadesApi & { deleteKnowledgeSource?: (id: string) => Promise<unknown> };
      if (typeof api.deleteKnowledgeSource !== "function") {
        throw new Error("Knowledge delete API niet beschikbaar.");
      }
      await api.deleteKnowledgeSource(id);
      await refresh();
    },
  };
}
