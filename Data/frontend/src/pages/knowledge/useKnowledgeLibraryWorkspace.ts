/**
 * Knowledge Library V2 workspace orchestration.
 *
 * Authorities:
 * - Library list/overview: GET /api/knowledge/library(+ /overview)
 * - Ingestion: SourceIngestion via /api/knowledge/library/ingestion/*
 * - Vector search: GET /api/knowledge/search (canonical HybridRetriever)
 * - Detail tabs: preview / embeddings / content-chunks / relations / related
 *
 * No production fixture fallback. Partial failure keeps healthy panels.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAppToast } from "../../state/useAppToast";
import type {
  KnowledgeEmbeddingStatus,
  KnowledgeIngestionRecentItem,
  KnowledgeLibraryItem,
  KnowledgeLibraryOverview,
  KnowledgeSearchHit,
} from "../../types/api";
import {
  KL_INGEST_POLL_MS,
  KL_LIBRARY_POLL_MS,
  KL_NAV,
  KL_PAGE_SIZE,
  KL_SEARCH_DEBOUNCE_MS,
  type KlDetailTab,
  type KlViewId,
  type KlViewMode,
} from "./constants";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(2)} TB`;
}

function relativeAge(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const sec = Math.max(0, Math.round((nowMs - t) / 1000));
  if (sec < 60) return `${sec}s geleden`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min geleden`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} u geleden`;
  return `${Math.floor(sec / 86400)} d geleden`;
}

export function useKnowledgeLibraryWorkspace() {
  const toast = useAppToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const selectGen = useRef(0);
  const refreshGen = useRef(0);

  const [view, setView] = useState<KlViewId>((params.get("view") as KlViewId) || "bibliotheek");
  const [viewMode, setViewMode] = useState<KlViewMode>("list");
  const [detailTab, setDetailTab] = useState<KlDetailTab>("preview");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  const [overview, setOverview] = useState<KnowledgeLibraryOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [items, setItems] = useState<KnowledgeLibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  const [q, setQ] = useState(params.get("q") || "");
  const [debouncedQ, setDebouncedQ] = useState(q);
  const [typeFilter, setTypeFilter] = useState(params.get("type") || "");
  const [tagFilter, setTagFilter] = useState(params.get("tag") || "");
  const [datePreset, setDatePreset] = useState(params.get("date") || "");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState(q ? "relevance" : "updated_desc");
  const [tagsExpanded, setTagsExpanded] = useState(false);

  const dateBounds = (() => {
    if (!datePreset) return { date_from: undefined as string | undefined, date_to: undefined as string | undefined };
    const end = new Date();
    const start = new Date(end);
    if (datePreset === "7d") start.setDate(start.getDate() - 7);
    else if (datePreset === "30d") start.setDate(start.getDate() - 30);
    else if (datePreset === "90d") start.setDate(start.getDate() - 90);
    else return { date_from: undefined, date_to: undefined };
    return { date_from: start.toISOString(), date_to: end.toISOString() };
  })();

  const [selectedId, setSelectedId] = useState<string | null>(params.get("source"));
  const [selected, setSelected] = useState<KnowledgeLibraryItem | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [embeddings, setEmbeddings] = useState<KnowledgeEmbeddingStatus | null>(null);
  const [chunks, setChunks] = useState<Array<Record<string, unknown>>>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [relations, setRelations] = useState<Array<Record<string, unknown>>>([]);
  const [related, setRelated] = useState<KnowledgeLibraryItem[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const [recentIngestions, setRecentIngestions] = useState<KnowledgeIngestionRecentItem[]>([]);
  const [ingestionError, setIngestionError] = useState<string | null>(null);
  const [activeIngestionId, setActiveIngestionId] = useState<string | null>(null);
  const [activeProgress, setActiveProgress] = useState<Record<string, unknown> | null>(null);

  const [vectorQ, setVectorQ] = useState("");
  const [vectorHits, setVectorHits] = useState<KnowledgeSearchHit[]>([]);
  const [vectorError, setVectorError] = useState<string | null>(null);

  // Debounce library search
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), KL_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [q]);

  // Sync deep-linkable state
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (selectedId) next.set("source", selectedId);
    else next.delete("source");
    if (view && view !== "bibliotheek") next.set("view", view);
    else next.delete("view");
    if (debouncedQ) next.set("q", debouncedQ);
    else next.delete("q");
    if (typeFilter) next.set("type", typeFilter);
    else next.delete("type");
    if (tagFilter) next.set("tag", tagFilter);
    else next.delete("tag");
    const cur = params.toString();
    const nxt = next.toString();
    if (cur !== nxt) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional deep-link sync
  }, [selectedId, view, debouncedQ, typeFilter, tagFilter]);

  // Ctrl+K / Escape for library search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
      if (e.key === "Escape" && document.activeElement === searchInputRef.current) {
        setQ("");
        searchInputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadOverview = useCallback(async () => {
    try {
      const res = await api.getKnowledgeLibraryOverview();
      setOverview(res.overview);
      setOverviewError(null);
      setOnline(true);
    } catch (err) {
      setOverviewError(errMsg(err, "Overview unavailable"));
      setOnline(false);
      setOverview((prev) => {
        if (prev) setStale(true);
        return prev;
      });
    }
  }, []);

  const loadLibrary = useCallback(
    async (opts: { offset?: number; quiet?: boolean } = {}) => {
      const off = opts.offset ?? 0;
      if (!opts.quiet) setLoading(off === 0);
      try {
        const sortKey = debouncedQ ? (sort === "relevance" ? "relevance" : sort) : sort === "relevance" ? "updated_desc" : sort;
        const res = await api.listKnowledgeLibrary({
          q: debouncedQ || undefined,
          type: typeFilter || undefined,
          tag: tagFilter || undefined,
          status: statusFilter || undefined,
          date_from: dateBounds.date_from,
          date_to: dateBounds.date_to,
          sort: sortKey,
          limit: KL_PAGE_SIZE,
          offset: off,
        });
        setItems(res.items);
        setTotal(res.total);
        setHasMore(res.has_more);
        setOffset(res.offset);
        setError(null);
        setStale(false);
        setLastUpdated(new Date().toISOString());
        setOnline(true);
        if (res.items.length && !selectedId) {
          setSelectedId(res.items[0].id);
        } else if (selectedId && !res.items.some((i) => i.id === selectedId) && off === 0) {
          // Keep selection if deep-linked even when not on this page.
        }
      } catch (err) {
        setError(errMsg(err, "Failed to load knowledge library"));
        setOnline(false);
        if (items.length) setStale(true);
        else setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [debouncedQ, typeFilter, tagFilter, statusFilter, sort, selectedId, items.length, dateBounds.date_from, dateBounds.date_to],
  );

  const loadIngestion = useCallback(async () => {
    try {
      const res = await api.listKnowledgeLibraryRecentIngestions(12, 0);
      setRecentIngestions(res.items);
      setIngestionError(null);
      const active = res.items.find((i) =>
        ["queued", "uploading", "stored", "inspecting", "expanding", "classifying", "parsing", "normalizing", "brain_pending", "brain_syncing", "ocr_pending", "ocr_running"].includes(
          String(i.phase || i.status || "").toLowerCase(),
        ),
      );
      if (active) {
        setActiveIngestionId(active.source_id);
        try {
          const st = await api.getKnowledgeLibraryIngestionStatus(active.source_id);
          setActiveProgress(st.progress as Record<string, unknown>);
        } catch {
          setActiveProgress({
            filename: active.filename,
            phase: active.phase,
            status: active.status,
            progress_pct: active.progress_pct,
            measured: active.measured,
          });
        }
      } else {
        setActiveIngestionId(null);
        setActiveProgress(null);
      }
    } catch (err) {
      setIngestionError(errMsg(err, "Ingestion status unavailable"));
    }
  }, [activeIngestionId]);

  const refresh = useCallback(
    async (opts: { quiet?: boolean } = {}) => {
      const gen = ++refreshGen.current;
      if (!opts.quiet) setRefreshing(true);
      await Promise.all([loadOverview(), loadLibrary({ quiet: opts.quiet }), loadIngestion()]);
      if (gen === refreshGen.current) setRefreshing(false);
    },
    [loadOverview, loadLibrary, loadIngestion],
  );

  // Initial + filter-driven library reload
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, typeFilter, tagFilter, statusFilter, sort, datePreset]);

  // Polling: active ingestion faster; library slower
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void loadIngestion();
    }, KL_INGEST_POLL_MS);
    return () => window.clearInterval(id);
  }, [loadIngestion]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void loadLibrary({ quiet: true });
      void loadOverview();
    }, KL_LIBRARY_POLL_MS);
    return () => window.clearInterval(id);
  }, [loadLibrary, loadOverview]);

  // Selection → lazy detail (race-safe)
  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setPreview(null);
      setEmbeddings(null);
      setChunks([]);
      setRelations([]);
      setRelated([]);
      setDetailError(null);
      return;
    }
    const gen = ++selectGen.current;
    setDetailLoading(true);
    setDetailError(null);
    (async () => {
      try {
        const [sum, prev, emb, ch, rel, relSrc] = await Promise.all([
          api.getKnowledgeLibraryDocument(selectedId),
          api.getKnowledgeLibraryPreview(selectedId).catch(() => null),
          api.getKnowledgeLibraryEmbeddings(selectedId).catch(() => null),
          api.getKnowledgeLibraryContentChunks(selectedId, { limit: 20 }).catch(() => null),
          api.getKnowledgeLibraryRelations(selectedId).catch(() => null),
          api.getKnowledgeLibraryRelated(selectedId).catch(() => null),
        ]);
        if (gen !== selectGen.current) return;
        setSelected(sum.document);
        setPreview(prev?.preview ?? null);
        setEmbeddings(emb?.embeddings ?? null);
        setChunks((ch?.chunks as Array<Record<string, unknown>>) ?? []);
        setChunkTotal(ch?.total ?? 0);
        setRelations(rel?.relations ?? []);
        setRelated(relSrc?.related ?? []);
      } catch (err) {
        if (gen !== selectGen.current) return;
        setDetailError(errMsg(err, "Failed to load source detail"));
        setSelected(null);
      } finally {
        if (gen === selectGen.current) setDetailLoading(false);
      }
    })();
  }, [selectedId]);

  const onNav = useCallback(
    (id: KlViewId) => {
      const item = KL_NAV.find((n) => n.id === id);
      if (item?.kind === "route" && item.to) {
        navigate(item.to);
        return;
      }
      setView(id);
    },
    [navigate],
  );

  const onUploadFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) return;
      setBusy(true);
      let ok = 0;
      try {
        for (const file of Array.from(files)) {
          const res = await api.uploadKnowledgeLibraryFile(file);
          ok += 1;
          if (res.source_id) setActiveIngestionId(String(res.source_id));
          if (res.idempotent) toast(`${file.name}: already known`);
        }
        toast(`${ok} bestand(en) geüpload naar SourceIngestion`);
        await loadIngestion();
        await loadLibrary({ quiet: true });
        setView("ingestie");
      } catch (err) {
        toast(errMsg(err, "Upload failed"));
      } finally {
        setBusy(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [loadIngestion, loadLibrary, toast],
  );

  const onCancelIngestion = useCallback(async () => {
    if (!activeIngestionId) return;
    setBusy(true);
    try {
      await api.cancelKnowledgeLibraryIngestion(activeIngestionId);
      toast("Cancel requested");
      await loadIngestion();
    } catch (err) {
      toast(errMsg(err, "Cancel failed"));
    } finally {
      setBusy(false);
    }
  }, [activeIngestionId, loadIngestion, toast]);

  const onRetryIngestion = useCallback(async () => {
    if (!activeIngestionId) return;
    setBusy(true);
    try {
      await api.retryKnowledgeLibraryIngestion(activeIngestionId, true);
      toast("Retry enqueued");
      await loadIngestion();
    } catch (err) {
      toast(errMsg(err, "Retry failed"));
    } finally {
      setBusy(false);
    }
  }, [activeIngestionId, loadIngestion, toast]);

  const onDeleteSelected = useCallback(async () => {
    if (!selectedId) return;
    if (!window.confirm("Delete this knowledge document? Related chunks/embeddings will be removed. Shared raw artifacts are not automatically destroyed.")) {
      return;
    }
    setBusy(true);
    try {
      await api.deleteKnowledgeDocument(selectedId);
      setSelectedId(null);
      toast("Document deleted");
      await loadLibrary({ quiet: true });
      await loadOverview();
    } catch (err) {
      toast(errMsg(err, "Delete failed"));
    } finally {
      setBusy(false);
    }
  }, [selectedId, loadLibrary, loadOverview, toast]);

  const onBulkDelete = useCallback(async () => {
    if (!checked.size) return;
    if (!window.confirm(`Delete ${checked.size} selected document(s)? This cannot be undone.`)) return;
    setBusy(true);
    try {
      const ids = [...checked].slice(0, 50);
      for (const id of ids) {
        await api.deleteKnowledgeDocument(id);
      }
      setChecked(new Set());
      toast(`${ids.length} deleted`);
      await refresh({ quiet: true });
    } catch (err) {
      toast(errMsg(err, "Bulk delete failed"));
    } finally {
      setBusy(false);
    }
  }, [checked, refresh, toast]);

  const onBulkTag = useCallback(async () => {
    if (!checked.size) return;
    const raw = window.prompt("Tags toevoegen (comma-separated):");
    if (!raw) return;
    const tags = raw.split(/[,;\s]+/).map((t) => t.trim()).filter(Boolean);
    if (!tags.length) return;
    setBusy(true);
    try {
      for (const id of [...checked].slice(0, 50)) {
        await api.setKnowledgeLibraryTags(id, tags, "add");
      }
      toast("Tags toegevoegd");
      await loadLibrary({ quiet: true });
    } catch (err) {
      toast(errMsg(err, "Tag update failed"));
    } finally {
      setBusy(false);
    }
  }, [checked, loadLibrary, toast]);

  const onVectorSearch = useCallback(async () => {
    const query = vectorQ.trim();
    if (!query) {
      toast("Enter a vector search query");
      return;
    }
    setBusy(true);
    setVectorError(null);
    try {
      const res = await api.searchKnowledge({ q: query, limit: 20 });
      setVectorHits(res.hits);
      if (!res.hits.length) toast("No semantic matches");
    } catch (err) {
      setVectorHits([]);
      setVectorError(errMsg(err, "Vector search failed"));
    } finally {
      setBusy(false);
    }
  }, [vectorQ, toast]);

  const onShare = useCallback(async () => {
    if (!selectedId) return;
    const url = `${window.location.origin}/knowledge?source=${encodeURIComponent(selectedId)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Deep link copied");
    } catch {
      toast(url);
    }
  }, [selectedId, toast]);

  const toggleCheck = useCallback((id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const sidebarStatus = [
    {
      id: "knowledge-db",
      label: "Knowledge DB",
      value: overviewError && !overview ? "ERROR" : overview ? "Healthy" : "…",
      tone: (overviewError && !overview ? "danger" : "success") as "danger" | "success" | "muted",
    },
    {
      id: "vector-index",
      label: "Vector Index",
      value: overview?.embedding?.status ?? "—",
      tone: (overview?.embedding?.status === "OK" ? "success" : "muted") as "success" | "muted",
    },
    {
      id: "ingestion",
      label: "Ingestion",
      value: ingestionError ? "Degraded" : activeProgress ? "Active" : "Idle",
      tone: (ingestionError ? "danger" : activeProgress ? "success" : "muted") as "danger" | "success" | "muted",
    },
  ];

  return {
    formatBytes,
    relativeAge,
    searchInputRef,
    fileInputRef,
    view,
    onNav,
    viewMode,
    setViewMode,
    detailTab,
    setDetailTab,
    loading,
    refreshing,
    error,
    stale,
    lastUpdated,
    online,
    overview,
    overviewError,
    items,
    total,
    hasMore,
    offset,
    q,
    setQ,
    typeFilter,
    setTypeFilter,
    tagFilter,
    setTagFilter,
    datePreset,
    setDatePreset,
    statusFilter,
    setStatusFilter,
    sort,
    setSort,
    tagsExpanded,
    setTagsExpanded,
    selectedId,
    setSelectedId,
    selected,
    preview,
    embeddings,
    chunks,
    chunkTotal,
    relations,
    related,
    detailError,
    detailLoading,
    checked,
    toggleCheck,
    setChecked,
    busy,
    recentIngestions,
    ingestionError,
    activeIngestionId,
    activeProgress,
    vectorQ,
    setVectorQ,
    vectorHits,
    vectorError,
    onVectorSearch,
    refresh,
    loadLibrary,
    onUploadFiles,
    onCancelIngestion,
    onRetryIngestion,
    onDeleteSelected,
    onBulkDelete,
    onBulkTag,
    onShare,
    sidebarStatus,
  };
}

export type KnowledgeLibraryWorkspace = ReturnType<typeof useKnowledgeLibraryWorkspace>;
