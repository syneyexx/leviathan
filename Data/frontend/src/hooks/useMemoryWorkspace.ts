/**
 * Memory V2 workspace orchestration for `/memory` (Geheugen).
 * Real APIs only — Screen 1 fixture values live exclusively in mocks (Playwright).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useAppToast } from "../state/useAppToast";
import type {
  Conversation,
  MemoryActivityEvent,
  MemoryAnalytics,
  MemoryCreatePayload,
  MemoryKind,
  MemoryOverview,
  MemoryProcessingSettings,
  MemoryRecord,
  MemorySemanticIndexStatus,
  MemoryStatus,
} from "../types/api";

export type MemorySort = "newest" | "oldest" | "priority" | "kind" | "source";
export type AnalyticsRange = "24h" | "7d" | "30d" | "90d";
export type SearchMode = "hybrid" | "lexical" | "semantic";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatBytes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "UNMEASURED";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let i = -1;
  do {
    v /= 1024;
    i += 1;
  } while (v >= 1024 && i < units.length - 1);
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function memoryExcerpt(text: string, max = 72): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1)}…`;
}

export function useMemoryWorkspace() {
  const toast = useAppToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [online, setOnline] = useState(true);
  const [sidebarStatus, setSidebarStatus] = useState<SidebarStatusRow[]>([]);

  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [analytics, setAnalytics] = useState<MemoryAnalytics | null>(null);
  const [analyticsRange, setAnalyticsRange] = useState<AnalyticsRange>("7d");
  const [activity, setActivity] = useState<MemoryActivityEvent[]>([]);
  const [semanticIndex, setSemanticIndex] = useState<MemorySemanticIndexStatus | null>(null);
  const [processing, setProcessing] = useState<MemoryProcessingSettings | null>(null);

  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);

  const [query, setQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [searchHits, setSearchHits] = useState<MemoryRecord[] | null>(null);
  const [searchMeta, setSearchMeta] = useState<{
    mode?: string;
    degraded?: boolean;
    degrade_reason?: string | null;
  } | null>(null);
  const [searching, setSearching] = useState(false);

  const [kindFilter, setKindFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<MemoryStatus | "ACTIVE">("ACTIVE");
  const [sort, setSort] = useState<MemorySort>("newest");
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [dateSort, setDateSort] = useState<"newest" | "oldest">("newest");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MemoryRecord | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [correctOpen, setCorrectOpen] = useState(false);
  const [conversationOpen, setConversationOpen] = useState(false);
  const [processingSettingsOpen, setProcessingSettingsOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [busy, setBusy] = useState(false);

  const loadList = useCallback(
    async (opts?: { cursor?: string | null; append?: boolean }) => {
      setListLoading(true);
      try {
        const res = await api.listMemory({
          status: statusFilter,
          kind: kindFilter || undefined,
          source: sourceFilter || undefined,
          pinned: pinnedOnly || undefined,
          limit: 40,
          cursor: opts?.cursor || undefined,
          sort: dateSort === "oldest" ? "oldest" : sort,
        });
        const rows = res.memory || [];
        setItems((prev) => (opts?.append ? [...prev, ...rows] : rows));
        setNextCursor(res.next_cursor || null);
        if (!opts?.append && rows.length > 0) {
          setSelectedId((prev) =>
            prev && rows.some((m) => m.memory_id === prev) ? prev : rows[0].memory_id,
          );
        }
      } catch (err) {
        if (!opts?.append) setItems([]);
        toast(errMsg(err, "Memory lijst laden mislukt"));
      } finally {
        setListLoading(false);
      }
    },
    [statusFilter, kindFilter, sourceFilter, pinnedOnly, sort, dateSort, toast],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setLoadError(null);
    try {
      const [ov, an, act, sem, proc, health] = await Promise.all([
        api.memoryOverview(),
        api.memoryAnalytics(analyticsRange),
        api.memoryActivity(30),
        api.memorySemanticIndex().catch(() => ({ semantic_index: null })),
        api.memoryProcessing().catch(() => ({ processing: null })),
        api.health().catch(() => null),
      ]);
      setOverview(ov.overview);
      setAnalytics(an.analytics);
      setActivity(act.activity || []);
      setSemanticIndex(sem.semantic_index);
      setProcessing(proc.processing);
      setOnline(Boolean(health));
      const rows: SidebarStatusRow[] = [];
      const services = (health as { services?: Record<string, unknown> } | null)?.services;
      if (services && typeof services === "object") {
        for (const [name, st] of Object.entries(services).slice(0, 8)) {
          const status = String(
            (st as { status?: string })?.status || st || "UNKNOWN",
          ).toUpperCase();
          const tone: SidebarStatusRow["tone"] =
            status.includes("RUN") || status === "OK" || status === "READY" || status === "HEALTHY"
              ? "success"
              : status.includes("UNKNOWN")
                ? "muted"
                : status.includes("FAIL") || status.includes("DOWN")
                  ? "danger"
                  : "warning";
          rows.push({
            id: name,
            label: name,
            value: status,
            tone,
          });
        }
      }
      setSidebarStatus(rows);
      setStale(false);
      setLastUpdated(new Date().toISOString());
      await loadList();
    } catch (err) {
      setLoadError(errMsg(err, "Geheugen laden mislukt"));
      setStale(true);
      setOnline(false);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [analyticsRange, loadList]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    void api
      .memoryAnalytics(analyticsRange)
      .then((r) => setAnalytics(r.analytics))
      .catch(() => undefined);
  }, [analyticsRange]);

  const displayRows = useMemo(() => {
    let rows = searchHits ?? items;
    if (agentFilter) {
      rows = rows.filter((r) => (r.actor || "") === agentFilter);
    }
    return rows;
  }, [searchHits, items, agentFilter]);

  const agentOptions = useMemo(() => {
    const set = new Set<string>();
    for (const m of items) {
      if (m.actor) set.add(m.actor);
    }
    return Array.from(set).sort();
  }, [items]);

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) {
      setSearchHits(null);
      setSearchMeta(null);
      return;
    }
    setSearching(true);
    try {
      const res = await api.searchMemory({
        q,
        limit: 40,
        mode: searchMode,
        kind: kindFilter || undefined,
        source: sourceFilter || undefined,
      });
      setSearchHits(res.memory || []);
      setSearchMeta({
        mode: res.mode,
        degraded: res.degraded,
        degrade_reason: res.degrade_reason,
      });
      if (res.degraded) {
        toast(`Search gedegradeerd naar ${res.mode}: ${res.degrade_reason || "semantic unavailable"}`);
      }
    } catch (err) {
      toast(errMsg(err, "Zoeken mislukt"));
      setSearchHits([]);
    } finally {
      setSearching(false);
    }
  }, [query, searchMode, kindFilter, sourceFilter, toast]);

  const clearSearch = useCallback(() => {
    setQuery("");
    setSearchHits(null);
    setSearchMeta(null);
  }, []);

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetailOpen(true);
    try {
      const res = await api.getMemory(id);
      setDetail(res.memory);
    } catch {
      setDetail(items.find((m) => m.memory_id === id) || null);
    }
  }, [items]);

  const createNote = useCallback(
    async (payload: MemoryCreatePayload) => {
      setBusy(true);
      try {
        await api.createMemory(payload);
        toast("Memory aangemaakt");
        setCreateOpen(false);
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Aanmaken mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const togglePin = useCallback(
    async (id: string, pinned: boolean) => {
      setBusy(true);
      try {
        if (pinned) await api.unpinMemory(id);
        else await api.pinMemory(id);
        toast(pinned ? "Unpinned" : "Pinned");
        await loadList();
        if (detailOpen && selectedId === id) await openDetail(id);
      } catch (err) {
        toast(errMsg(err, "Pin mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [detailOpen, loadList, openDetail, selectedId, toast],
  );

  const archive = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await api.archiveMemory(id);
        toast("Gearchiveerd");
        setDetailOpen(false);
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Archiveren mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const restore = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await api.restoreMemory(id);
        toast("Hersteld");
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Herstellen mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const revoke = useCallback(
    async (id: string) => {
      if (!window.confirm("Revoke is permanent voor retrieval. Doorgaan?")) return;
      setBusy(true);
      try {
        await api.revokeMemory(id);
        toast("Revoked");
        setDetailOpen(false);
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Revoke mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const correct = useCallback(
    async (id: string, content: string, kind?: MemoryKind) => {
      setBusy(true);
      try {
        await api.correctMemory(id, { content, kind });
        toast("Correctie opgeslagen (supersede)");
        setCorrectOpen(false);
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Correctie mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const optimizeIndex = useCallback(async () => {
    setBusy(true);
    try {
      const res = await api.optimizeMemorySemanticIndex();
      if (res.queued) toast("Index optimalisatie gequeued");
      else toast(`Index onderhoud: ${JSON.stringify(res.orphans_removed ?? res)}`);
      await refresh();
    } catch (err) {
      toast(errMsg(err, "Index optimaliseren mislukt"));
    } finally {
      setBusy(false);
    }
  }, [refresh, toast]);

  const patchProcessing = useCallback(
    async (patch: Partial<MemoryProcessingSettings>) => {
      setBusy(true);
      try {
        const res = await api.patchMemoryProcessing(patch);
        setProcessing(res.processing);
        toast("Verwerkingsinstellingen opgeslagen");
      } catch (err) {
        toast(errMsg(err, "Settings opslaan mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const loadConversations = useCallback(async () => {
    try {
      const res = await api.listConversations({ limit: 30 });
      setConversations(res.conversations || []);
    } catch {
      setConversations([]);
    }
  }, []);

  const saveFromConversation = useCallback(
    async (payload: {
      conversation_id: string;
      content: string;
      kind?: string;
      from_assistant?: boolean;
    }) => {
      setBusy(true);
      try {
        await api.memoryFromConversation(payload);
        toast("Opgeslagen uit gesprek");
        setConversationOpen(false);
        await refresh();
      } catch (err) {
        toast(errMsg(err, "Opslaan uit gesprek mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const kpi = useMemo(() => {
    const ov = overview;
    const storageLabel =
      ov?.storage?.provenance === "MEASURED"
        ? formatBytes(ov.storage.total_bytes)
        : "UNMEASURED";
    const emb = ov?.semantic_index?.indexed_count ?? semanticIndex?.indexed_count ?? null;
    return {
      total: ov?.total ?? null,
      active: ov?.active ?? null,
      embeddings: emb,
      storage: storageLabel,
      storageProvenance: ov?.storage?.provenance ?? "UNMEASURED",
      sources: ov?.unique_sources ?? null,
      searches: ov?.search_count_7d ?? null,
      searchesLabel: "7d",
    };
  }, [overview, semanticIndex]);

  const recentAdded = useMemo(() => items.slice(0, 8), [items]);

  return {
    loading,
    refreshing,
    stale,
    lastUpdated,
    loadError,
    online,
    sidebarStatus,
    overview,
    analytics,
    analyticsRange,
    setAnalyticsRange,
    activity,
    semanticIndex,
    processing,
    items: displayRows,
    nextCursor,
    listLoading,
    loadMore: () => void loadList({ cursor: nextCursor, append: true }),
    query,
    setQuery,
    searchMode,
    setSearchMode,
    searchMeta,
    searching,
    runSearch,
    clearSearch,
    isSearchActive: searchHits != null,
    kindFilter,
    setKindFilter,
    sourceFilter,
    setSourceFilter,
    agentFilter,
    setAgentFilter,
    agentOptions,
    statusFilter,
    setStatusFilter,
    sort,
    setSort,
    dateSort,
    setDateSort,
    pinnedOnly,
    setPinnedOnly,
    advancedOpen,
    setAdvancedOpen,
    selectedId,
    setSelectedId,
    detail,
    detailOpen,
    setDetailOpen,
    openDetail,
    createOpen,
    setCreateOpen,
    correctOpen,
    setCorrectOpen,
    conversationOpen,
    setConversationOpen,
    processingSettingsOpen,
    setProcessingSettingsOpen,
    conversations,
    loadConversations,
    busy,
    refresh,
    createNote,
    togglePin,
    archive,
    restore,
    revoke,
    correct,
    optimizeIndex,
    patchProcessing,
    saveFromConversation,
    kpi,
    recentAdded,
    formatBytes,
  };
}

export type MemoryWorkspace = ReturnType<typeof useMemoryWorkspace>;
