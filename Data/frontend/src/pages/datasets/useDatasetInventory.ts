/**
 * Inventory load + filter params + deep-link selection for `/datasets`.
 * Selection is independent of the filtered inventory page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import type { DatasetJob, DatasetOverview, DatasetRecord } from "../../types/api";
import {
  DS_PAGE_SIZE,
  DS_SEARCH_DEBOUNCE_MS,
  DS_TYPE_OPTIONS,
  DS_UPDATED_OPTIONS,
  type DhColumnId,
  type DhFilterId,
  type DhRow,
  DS_COLUMNS,
} from "./constants";
import { buildListDatasetsParams } from "./datasetFilterParams";
import { countDatasetsByFilter, reconcileSelection } from "./datasetsInventory";
import { formatBytes, recordToRow } from "./datasetsMapping";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function defaultVisibleColumns(): Set<DhColumnId> {
  return new Set(DS_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.id));
}

export type WorkspaceMode = "inventory" | "manage" | "learning";

export function useDatasetInventory(opts: {
  jobs: DatasetJob[];
  onInventoryChanged?: () => void;
}) {
  const { jobs } = opts;
  const [searchParams, setSearchParams] = useSearchParams();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [filter, setFilter] = useState<DhFilterId>("all");
  const [view, setView] = useState<"list" | "grid">("list");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<(typeof DS_TYPE_OPTIONS)[number]>(DS_TYPE_OPTIONS[0]);
  const [updatedFilter, setUpdatedFilter] =
    useState<(typeof DS_UPDATED_OPTIONS)[number]>(DS_UPDATED_OPTIONS[0]);
  const [visibleColumns, setVisibleColumns] = useState<Set<DhColumnId>>(defaultVisibleColumns);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  /** Independent of inventory page — may be outside filteredRows. */
  const [selectedRecord, setSelectedRecord] = useState<DatasetRecord | null>(null);
  const [selectionOutsidePage, setSelectionOutsidePage] = useState(false);

  const modeParam = searchParams.get("mode");
  const workspaceMode: WorkspaceMode =
    modeParam === "learning" || modeParam === "learned"
      ? "learning"
      : modeParam === "manage"
        ? "manage"
        : "inventory";

  const inventoryGenRef = useRef(0);
  const overviewGenRef = useRef(0);
  const deepLinkHandledRef = useRef<string | null>(null);
  const loadDatasetsRef = useRef<(opts?: { quiet?: boolean; offset?: number }) => Promise<void>>(
    async () => undefined,
  );

  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(queryInput.trim()), DS_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [queryInput]);

  // Deep link ?dataset=id — set selection independently of inventory.
  useEffect(() => {
    const deep = searchParams.get("dataset");
    if (!deep) {
      deepLinkHandledRef.current = null;
      return;
    }
    if (deepLinkHandledRef.current === deep) return;
    deepLinkHandledRef.current = deep;
    setActiveId(deep);
  }, [searchParams]);

  const liveRows = useMemo(() => datasets.map((ds) => recordToRow(ds, jobs)), [datasets, jobs]);

  // Server already applied filters — do NOT re-filter type/updated client-side.
  const filteredRows = liveRows;

  const filterCounts = useMemo(() => {
    const pageCounts = countDatasetsByFilter(liveRows);
    if (!overview) return pageCounts;
    return {
      all: overview.totalDatasets ?? pageCounts.all,
      local: overview.localDatasets ?? pageCounts.local,
      external: overview.externalDatasets ?? pageCounts.external,
      indexed: overview.indexedDatasets ?? pageCounts.indexed,
      not_indexed: overview.notIndexedDatasets ?? pageCounts.not_indexed,
    };
  }, [liveRows, overview]);

  // Reconcile multi-select against current page only — never clear intentional activeId.
  useEffect(() => {
    setSelectedIds((prev) => reconcileSelection(prev, filteredRows.map((r) => r.id)));
  }, [filteredRows]);

  // Track whether active selection is outside the current inventory page.
  useEffect(() => {
    if (!activeId) {
      setSelectionOutsidePage(false);
      return;
    }
    const onPage = filteredRows.some((r) => r.id === activeId);
    setSelectionOutsidePage(!onPage);
  }, [activeId, filteredRows]);

  const activeRow: DhRow | null = useMemo(() => {
    if (!activeId) return null;
    return (
      filteredRows.find((r) => r.id === activeId) ??
      (selectedRecord ? recordToRow(selectedRecord, jobs) : null)
    );
  }, [filteredRows, activeId, selectedRecord, jobs]);

  const activeRecord = useMemo(() => {
    if (!activeId) return null;
    return datasets.find((d) => d.datasetId === activeId) ?? selectedRecord;
  }, [datasets, activeId, selectedRecord]);

  const listParams = useCallback(
    (pageOffset: number) =>
      buildListDatasetsParams({
        filter,
        query,
        typeFilter,
        updatedFilter,
        offset: pageOffset,
      }),
    [filter, query, typeFilter, updatedFilter],
  );

  const loadDatasets = useCallback(
    async (opts?: { quiet?: boolean; offset?: number }) => {
      const pageOffset = opts?.offset ?? offset;
      const gen = ++inventoryGenRef.current;
      if (!opts?.quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await api.listDatasets(DS_PAGE_SIZE, listParams(pageOffset));
        if (gen !== inventoryGenRef.current) return;
        setDatasets(res.datasets);
        setCatalogTotal(res.total ?? res.datasets.length);
        setOffset(res.offset ?? pageOffset);
        setHasMore(Boolean(res.hasMore));
        setNextCursor(res.nextCursor ?? null);
        setStale(false);
        setLastUpdated(new Date().toISOString());
        setError(null);
        // Do NOT replace activeId with row 1 when deep-linked/selected is outside page.
      } catch (err) {
        if (gen !== inventoryGenRef.current) return;
        const msg = errMsg(err, "Datasets laden mislukt");
        setError(msg);
        if (opts?.quiet && datasets.length > 0) {
          setStale(true);
        } else if (!opts?.quiet) {
          setDatasets([]);
          setStale(false);
        }
      } finally {
        if (gen === inventoryGenRef.current && !opts?.quiet) setLoading(false);
      }
    },
    [datasets.length, listParams, offset],
  );

  const loadOverview = useCallback(async (opts?: { quiet?: boolean }) => {
    const gen = ++overviewGenRef.current;
    if (!opts?.quiet) setOverviewLoading(true);
    try {
      const res = await api.getDatasetsOverview();
      if (gen !== overviewGenRef.current) return;
      setOverview(res.overview);
      setOverviewError(null);
    } catch (err) {
      if (gen !== overviewGenRef.current) return;
      setOverviewError(errMsg(err, "Overzicht laden mislukt"));
      if (!opts?.quiet) setOverview(null);
    } finally {
      if (gen === overviewGenRef.current && !opts?.quiet) setOverviewLoading(false);
    }
  }, []);

  loadDatasetsRef.current = loadDatasets;

  useEffect(() => {
    void loadOverview();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial

  useEffect(() => {
    setOffset(0);
    void loadDatasets({ offset: 0 });
  }, [filter, query, typeFilter, updatedFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // When learning mode: keep filter affinity but do not force inventory rewrite here.
  useEffect(() => {
    if (workspaceMode === "learning" && filter === "all") {
      // Soft preference — operator can still change pills.
    }
  }, [workspaceMode, filter]);

  function setActiveIdAndUrl(id: string | null) {
    setActiveId(id);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("dataset", id);
        else next.delete("dataset");
        return next;
      },
      { replace: true },
    );
  }

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (filteredRows.every((r) => selectedIds.has(r.id)) && filteredRows.length > 0) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(filteredRows.map((r) => r.id)));
  }

  function toggleColumn(id: DhColumnId) {
    setVisibleColumns((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (id === "name") return prev;
        next.delete(id);
      } else next.add(id);
      return next;
    });
  }

  function goPage(nextOffset: number) {
    void loadDatasets({ offset: Math.max(0, nextOffset) });
  }

  const metrics = useMemo(() => {
    const total = overview?.totalDatasets ?? catalogTotal ?? liveRows.length;
    const local =
      overview?.localDatasets != null
        ? overview.localDatasets
        : overview?.bySourceType
          ? Object.entries(overview.bySourceType).reduce((sum, [k, v]) => {
              const kind = k.toLowerCase();
              if (kind.includes("local") || kind.includes("upload") || kind === "file" || kind === "path") {
                return sum + v;
              }
              return sum;
            }, 0)
          : liveRows.filter((r) => r.sourceKind === "local").length;
    const external =
      overview?.externalDatasets != null ? overview.externalDatasets : Math.max(0, total - local);
    const sizeBytes = overview?.attributableBytes ?? liveRows.reduce((s, r) => s + (r.byteSize ?? 0), 0);
    const indexed =
      overview?.indexedDatasets != null
        ? overview.indexedDatasets
        : liveRows.filter((r) => r.embeddings.kind === "indexed").length;
    const indexedPct = total > 0 ? Math.round((indexed / total) * 100) : null;
    return {
      total,
      local,
      external,
      localPct: total > 0 ? Math.round((local / total) * 100) : null,
      externalPct: total > 0 ? Math.round((external / total) * 100) : null,
      sizeLabel: formatBytes(sizeBytes),
      sizeUnmeasured: overview ? overview.bytesUnmeasuredDatasets > 0 : liveRows.some((r) => r.byteSize == null),
      indexed,
      indexedPct,
      capacityLabel: overview?.capacityBytes != null ? formatBytes(overview.capacityBytes) : null,
      usedBytes: overview?.usedBytes ?? null,
      capacityBytes: overview?.capacityBytes ?? null,
      inventoryPageSize: liveRows.length,
      catalogTotal: catalogTotal ?? overview?.totalDatasets ?? liveRows.length,
      hasMore,
    };
  }, [overview, liveRows, catalogTotal, hasMore]);

  return {
    loading,
    error,
    stale,
    lastUpdated,
    datasets,
    setDatasets,
    catalogTotal,
    offset,
    hasMore,
    nextCursor,
    pageSize: DS_PAGE_SIZE,
    overview,
    overviewLoading,
    overviewError,
    loadDatasets,
    loadOverview,
    loadDatasetsRef,
    filter,
    setFilter,
    view,
    setView,
    filtersOpen,
    setFiltersOpen,
    columnsOpen,
    setColumnsOpen,
    queryInput,
    setQueryInput,
    query,
    typeFilter,
    setTypeFilter,
    updatedFilter,
    setUpdatedFilter,
    visibleColumns,
    toggleColumn,
    selectedIds,
    setSelectedIds,
    toggleSelected,
    toggleSelectAll,
    activeId,
    setActiveId: setActiveIdAndUrl,
    setActiveIdRaw: setActiveId,
    activeRow,
    activeRecord,
    selectedRecord,
    setSelectedRecord,
    selectionOutsidePage,
    liveRows,
    filteredRows,
    filterCounts,
    metrics,
    goPage,
    workspaceMode,
    searchParams,
    setSearchParams,
  };
}

export type DatasetInventory = ReturnType<typeof useDatasetInventory>;
