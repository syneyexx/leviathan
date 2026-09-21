"use client";

import { useCallback, useMemo, useState } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type MemoryItem } from "@/lib/hades-api";

const KEY = "hades:memories";

export function useHadesMemory(initialQuery = "") {
  const [query, setQuery] = useState(initialQuery);
  const [collection, setCollection] = useState("");
  const [scope, setScope] = useState("");

  const memQuery = useHadesQuery(
    `${KEY}:${query}:${collection}:${scope}`,
    async () => hadesApi.memories(query, collection, scope),
    { staleTime: 4_000 },
  );

  const items = memQuery.data?.items ?? [];
  const stats = memQuery.data?.stats;
  const collections = memQuery.data?.collections ?? [];

  const refresh = useCallback(async () => {
    invalidateHadesQuery(`${KEY}:${query}:${collection}:${scope}`);
    return memQuery.refetch();
  }, [memQuery, query, collection, scope]);

  const create = useCallback(
    async (values: Omit<MemoryItem, "id" | "created_at" | "updated_at">) => {
      const item = await hadesApi.createMemory(values);
      await refresh();
      return item;
    },
    [refresh],
  );

  const update = useCallback(
    async (id: string, values: Omit<MemoryItem, "id" | "created_at" | "updated_at">) => {
      const item = await hadesApi.updateMemory(id, values);
      await refresh();
      return item;
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await hadesApi.deleteMemory(id);
      await refresh();
    },
    [refresh],
  );

  const retrieve = useCallback(async (q: string) => {
    const res = await hadesApi.retrieveMemory(q);
    return res.matches || [];
  }, []);

  const cards = useMemo(
    () =>
      items.map((item) => ({
        id: item.id,
        title: item.title || "(zonder titel)",
        summary: item.summary || item.content.slice(0, 160),
        content: item.content,
        collection: item.collection,
        tags: item.tags || [],
        source: item.source,
        scope: item.scope,
        created_at: item.created_at,
        updated_at: item.updated_at,
        raw: item,
      })),
    [items],
  );

  return {
    items,
    cards,
    stats,
    collections,
    query,
    setQuery,
    collection,
    setCollection,
    scope,
    setScope,
    loading: memQuery.status === "loading" && !memQuery.data,
    error: memQuery.error,
    refresh,
    create,
    update,
    remove,
    retrieve,
  };
}
