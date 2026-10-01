/**
 * useConversationCatalog — server-side search + cursor pagination + race safety.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";
import type { Conversation } from "../../../types/api";

export type ConversationCatalogState = {
  conversations: Conversation[];
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  hasMore: boolean;
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  selectedId: string | null;
  selectConversation: (id: string | null) => void;
  refresh: () => Promise<Conversation[]>;
  loadMore: () => Promise<Conversation[]>;
  upsertConversation: (c: Conversation) => void;
  removeConversation: (id: string) => void;
};

export function useConversationCatalog(opts?: {
  debounceMs?: number;
  pageSize?: number;
}): ConversationCatalogState {
  const debounceMs = opts?.debounceMs ?? 250;
  const pageSize = opts?.pageSize ?? 50;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const genRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchQuery), debounceMs);
    return () => window.clearTimeout(t);
  }, [searchQuery, debounceMs]);

  const fetchPage = useCallback(
    async (mode: "reset" | "more"): Promise<Conversation[]> => {
      const gen = ++genRef.current;
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;
      if (mode === "reset") setLoading(true);
      else setLoadingMore(true);
      try {
        const result = await api.listConversations({
          q: debouncedQ || undefined,
          limit: pageSize,
          cursor: mode === "more" ? cursor ?? undefined : undefined,
          signal: abort.signal,
        });
        if (gen !== genRef.current) return [];
        const items = result.conversations ?? result.items ?? [];
        setConversations((prev) => (mode === "more" ? [...prev, ...items] : items));
        setHasMore(Boolean(result.has_more));
        setCursor(result.next_cursor ?? null);
        if (mode === "reset") setTotal(result.total ?? null);
        return items;
      } catch (err) {
        if ((err as { name?: string })?.name === "AbortError") return [];
        if (gen !== genRef.current) return [];
        if (mode === "reset") {
          setConversations([]);
          setHasMore(false);
          setCursor(null);
        }
        return [];
      } finally {
        if (gen === genRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [cursor, debouncedQ, pageSize],
  );

  useEffect(() => {
    void fetchPage("reset");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when query changes
  }, [debouncedQ]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return {
    conversations,
    searchQuery,
    setSearchQuery,
    hasMore,
    total,
    loading,
    loadingMore,
    selectedId,
    selectConversation: setSelectedId,
    refresh: () => fetchPage("reset"),
    loadMore: () => fetchPage("more"),
    upsertConversation: (c) => {
      setConversations((prev) => {
        const without = prev.filter((x) => x.id !== c.id);
        return [c, ...without];
      });
    },
    removeConversation: (id) => {
      setConversations((prev) => prev.filter((x) => x.id !== id));
      setSelectedId((cur) => (cur === id ? null : cur));
    },
  };
}
