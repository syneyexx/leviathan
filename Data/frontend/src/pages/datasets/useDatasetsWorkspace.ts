/**
 * Onderzoek & Kennis → Datasets workspace orchestration.
 *
 * Canonical authorities:
 * - Inventory: GET /api/datasets via api.listDatasets (bounded pagination)
 * - Overview KPIs/storage/services: GET /api/datasets/overview
 * - Jobs/activity: useDatasetActivity → listDatasetJobs (adaptive polling)
 * - Mutations: create/upload/import/delete/index/bulk/cancel via DatasetService routes
 *
 * No page-local queue, scheduler, or fixture production fallback.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAppToast } from "../../state/useAppToast";
import type {
  DatasetOverview,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetVersion,
} from "../../types/api";
import {
  DS_BULK_MAX,
  DS_COLUMNS,
  DS_PAGE_SIZE,
  DS_SEARCH_DEBOUNCE_MS,
  DS_TYPE_OPTIONS,
  DS_UPDATED_OPTIONS,
  type DhColumnId,
  type DhFilterId,
  type DhRow,
} from "./constants";
import {
  countDatasetsByFilter,
  filterDatasetRows,
  reconcileSelection,
} from "./datasetsInventory";
import {
  formatBytes,
  jobProgressDetail,
  measuredProgressPct,
  phaseLabel,
  recordToRow,
  relativeTime,
} from "./datasetsMapping";
import { useDatasetActivity } from "./useDatasetActivity";

export type ViewMode = "list" | "grid";
export type ModalKind = "create" | "import" | "hf" | "activity" | "health" | null;
export type DetailTab = "overview" | "analyse" | "preview" | "metadata" | "versions" | "activity";
export type ImportMenuKind = "upload" | "path" | null;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function defaultVisibleColumns(): Set<DhColumnId> {
  return new Set(DS_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.id));
}

export function useDatasetsWorkspace() {
  const toast = useAppToast();
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);
  const importMenuRef = useRef<HTMLDivElement>(null);
  const externalMenuRef = useRef<HTMLDivElement>(null);
  const columnsMenuRef = useRef<HTMLDivElement>(null);
  const downloadMenuRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const loadDatasetsRef = useRef<(opts?: { quiet?: boolean; offset?: number }) => Promise<void>>(
    async () => undefined,
  );
  const loadOverviewRef = useRef<(opts?: { quiet?: boolean }) => Promise<void>>(async () => undefined);

  const {
    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    loadJobs,
    clearActivityView,
    live,
  } = useDatasetActivity({
    onLifecycleChange: () => {
      void loadDatasetsRef.current({ quiet: true });
      void loadOverviewRef.current({ quiet: true });
    },
  });

  const [filter, setFilter] = useState<DhFilterId>("all");
  const [view, setView] = useState<ViewMode>("list");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const [externalMenuOpen, setExternalMenuOpen] = useState(false);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<(typeof DS_TYPE_OPTIONS)[number]>(DS_TYPE_OPTIONS[0]);
  const [updatedFilter, setUpdatedFilter] =
    useState<(typeof DS_UPDATED_OPTIONS)[number]>(DS_UPDATED_OPTIONS[0]);
  const [visibleColumns, setVisibleColumns] = useState<Set<DhColumnId>>(defaultVisibleColumns);
  const [activityPeriod, setActivityPeriod] = useState("Laatste 24 uur");

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");

  const [detailVersions, setDetailVersions] = useState<DatasetVersion[]>([]);
  const [detailPreview, setDetailPreview] = useState<DatasetPreviewRow[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [tagDraft, setTagDraft] = useState("");

  const [modal, setModal] = useState<ModalKind>(null);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [hfRepo, setHfRepo] = useState("");
  const [hfRevision, setHfRevision] = useState("main");
  const [hfToken, setHfToken] = useState("");

  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(queryInput.trim()), DS_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [queryInput]);

  const liveRows = useMemo(
    () => datasets.map((ds) => recordToRow(ds, jobs)),
    [datasets, jobs],
  );

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

  const filteredRows = useMemo(
    () =>
      filterDatasetRows(liveRows, {
        filter: "all", // server already applied primary filter; keep type/updated/query client-side extras
        query: "",
        typeFilter,
        updatedFilter,
      }),
    [liveRows, typeFilter, updatedFilter],
  );

  // Reconcile selection + active row against filtered inventory.
  useEffect(() => {
    setSelectedIds((prev) => reconcileSelection(prev, filteredRows.map((r) => r.id)));
    if (activeId && !filteredRows.some((r) => r.id === activeId) && !liveRows.some((r) => r.id === activeId)) {
      setActiveId(filteredRows[0]?.id ?? null);
    }
  }, [filteredRows, liveRows, activeId]);

  const activeRow: DhRow | null = useMemo(
    () => filteredRows.find((r) => r.id === activeId) ?? liveRows.find((r) => r.id === activeId) ?? null,
    [filteredRows, liveRows, activeId],
  );

  const activeRecord = useMemo(
    () => datasets.find((d) => d.datasetId === activeId) ?? null,
    [datasets, activeId],
  );

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

  const storage = useMemo(() => {
    if (overview?.storageBreakdown?.length) {
      const usedBytes = overview.attributableBytes ?? overview.usedBytes ?? 0;
      const capacity = overview.capacityBytes ?? null;
      return {
        usedLabel: formatBytes(usedBytes),
        capacityLabel: capacity != null ? formatBytes(capacity) : null,
        pct:
          capacity != null && capacity > 0 && overview.usedBytes != null
            ? Math.min(100, Math.round((overview.usedBytes / capacity) * 100))
            : null,
        segments: overview.storageBreakdown.map((row, i) => ({
          id: row.id,
          label: row.label,
          bytesLabel: formatBytes(row.bytes),
          pct: row.pct,
          color: ["#2ec4b6", "#4f8cff", "#9b5cff", "#6b7280", "#f59e0b"][i % 5],
        })),
        estimated: false,
        measurementNote:
          overview.measurementStatus && overview.measurementStatus !== "measured"
            ? overview.measurementStatus
            : null,
      };
    }

    const totalBytes = liveRows.reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const localBytes = liveRows
      .filter((r) => r.sourceKind === "local")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const processingBytes = liveRows
      .filter((r) => r.status === "processing" || r.status === "validating")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const other = Math.max(0, totalBytes - localBytes - processingBytes);
    return {
      usedLabel: formatBytes(totalBytes),
      capacityLabel: null as string | null,
      pct: null as number | null,
      segments: [
        { id: "local", label: "Lokale datasets", bytesLabel: formatBytes(localBytes), pct: 0, color: "#2ec4b6" },
        {
          id: "processing",
          label: "Verwerking",
          bytesLabel: formatBytes(processingBytes),
          pct: 0,
          color: "#9b5cff",
        },
        { id: "other", label: "Overig", bytesLabel: formatBytes(other), pct: 0, color: "#6b7280" },
      ],
      estimated: true,
      measurementNote: "Geschat uit inventory byteSize — capaciteit UNMEASURED",
    };
  }, [overview, liveRows]);

  const pipelineItems = useMemo(() => {
    const active = jobs
      .filter((j) => {
        const s = j.status.toLowerCase();
        return s === "running" || s === "queued" || s === "pending";
      })
      .slice(0, 3);
    if (active.length === 0) {
      return [
        {
          id: "idle",
          title: "Wachtrij idle",
          detail: "Geen actieve dataset jobs",
          pct: null as number | null,
          eta: "—",
          tone: "cyan" as const,
          jobId: null as string | null,
        },
      ];
    }
    return active.map((j) => {
      const pct = measuredProgressPct(j);
      const dsName =
        datasets.find((d) => d.datasetId === j.datasetId)?.displayName ||
        datasets.find((d) => d.datasetId === j.datasetId)?.name ||
        j.datasetId ||
        "dataset";
      const detail = jobProgressDetail(j) || dsName;
      return {
        id: j.jobId,
        title: j.jobType.replace(/_/g, " "),
        detail,
        pct,
        eta: j.phase ? phaseLabel(j.phase) : relativeTime(j.updatedAt),
        tone: (j.jobType.toLowerCase().includes("index") ? "cyan" : "purple") as "cyan" | "purple",
        jobId: j.jobId as string | null,
      };
    });
  }, [jobs, datasets]);

  const activeJobCount = useMemo(
    () =>
      jobs.filter((j) => {
        const s = j.status.toLowerCase();
        return s === "running" || s === "queued" || s === "pending";
      }).length,
    [jobs],
  );

  const healthItems = useMemo(() => {
    const total = liveRows.length || 1;
    const ready = liveRows.filter((r) => r.status === "ready").length;
    const indexed = liveRows.filter((r) => r.embeddings.kind === "indexed").length;
    const offline = liveRows.filter((r) => r.status === "offline").length;
    const validating = liveRows.filter((r) => r.status === "validating").length;
    const unknown = liveRows.filter((r) => r.status === "unknown").length;
    return [
      {
        id: "ready",
        label: "Ready Coverage",
        pct: liveRows.length ? Math.round((ready / total) * 100) : null,
        hint: `${ready}/${liveRows.length} ready (status counts, not integrity proof)`,
        tone: "green" as const,
      },
      {
        id: "schema",
        label: "Schema Validation",
        pct: null as number | null,
        hint: validating
          ? `${validating} validating`
          : liveRows.length
            ? "UNMEASURED (no global schema probe score)"
            : "UNMEASURED",
        tone: "teal" as const,
      },
      {
        id: "embedding",
        label: "Embedding Coverage",
        pct: liveRows.length ? Math.round((indexed / total) * 100) : null,
        hint: `${Math.max(0, liveRows.length - indexed)} datasets not indexed`,
        tone: "blue" as const,
      },
      {
        id: "offline",
        label: "Offline Availability",
        pct: liveRows.length ? Math.round((offline / total) * 100) : null,
        hint:
          unknown > 0
            ? `${offline} offline · ${unknown} UNKNOWN`
            : `${offline} datasets marked offline`,
        tone: "orange" as const,
      },
    ];
  }, [liveRows]);

  const filteredActivity = useMemo(() => {
    const now = Date.now();
    const windowMs =
      activityPeriod === "Laatste 24 uur"
        ? 24 * 60 * 60 * 1000
        : activityPeriod === "Laatste 7 dagen"
          ? 7 * 24 * 60 * 60 * 1000
          : activityPeriod === "Laatste 30 dagen"
            ? 30 * 24 * 60 * 60 * 1000
            : null;
    if (windowMs == null) return activityEntries;
    const cutoff = now - windowMs;
    return activityEntries.filter((e) => {
      if (!e.timestamp) return false;
      const t = Date.parse(e.timestamp);
      return Number.isFinite(t) && t >= cutoff;
    });
  }, [activityEntries, activityPeriod]);

  const listParams = useCallback(() => {
    const params: {
      offset?: number;
      q?: string;
      sourceScope?: "local" | "external";
      indexed?: boolean;
      sort?: string;
    } = {
      sort: "updated_at_desc",
    };
    if (query) params.q = query;
    if (filter === "local") params.sourceScope = "local";
    if (filter === "external") params.sourceScope = "external";
    if (filter === "indexed") params.indexed = true;
    if (filter === "not_indexed") params.indexed = false;
    return params;
  }, [query, filter]);

  const loadDatasets = useCallback(
    async (opts?: { quiet?: boolean; offset?: number }) => {
      const pageOffset = opts?.offset ?? offset;
      if (!opts?.quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await api.listDatasets(DS_PAGE_SIZE, {
          ...listParams(),
          offset: pageOffset,
        });
        setDatasets(res.datasets);
        setCatalogTotal(res.total ?? res.datasets.length);
        setOffset(res.offset ?? pageOffset);
        setHasMore(Boolean(res.hasMore));
        setStale(false);
        setLastUpdated(new Date().toISOString());
        setError(null);
        setActiveId((prev) => {
          if (prev && res.datasets.some((d) => d.datasetId === prev)) return prev;
          return res.datasets[0]?.datasetId ?? null;
        });
      } catch (err) {
        const msg = errMsg(err, "Datasets laden mislukt");
        setError(msg);
        if (opts?.quiet && datasets.length > 0) {
          setStale(true);
        } else if (!opts?.quiet) {
          setDatasets([]);
          setStale(false);
        }
      } finally {
        if (!opts?.quiet) setLoading(false);
      }
    },
    [datasets.length, listParams, offset],
  );

  const loadOverview = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setOverviewLoading(true);
    try {
      const res = await api.getDatasetsOverview();
      setOverview(res.overview);
      setOverviewError(null);
    } catch (err) {
      setOverviewError(errMsg(err, "Overzicht laden mislukt"));
      if (!opts?.quiet) setOverview(null);
    } finally {
      if (!opts?.quiet) setOverviewLoading(false);
    }
  }, []);

  loadDatasetsRef.current = loadDatasets;
  loadOverviewRef.current = loadOverview;

  useEffect(() => {
    void loadOverview();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    setOffset(0);
    void loadDatasets({ offset: 0 });
  }, [filter, query]); // eslint-disable-line react-hooks/exhaustive-deps -- refetch on server filters

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(t)) setMenuFor(null);
      if (importMenuRef.current && !importMenuRef.current.contains(t)) setImportMenuOpen(false);
      if (externalMenuRef.current && !externalMenuRef.current.contains(t)) setExternalMenuOpen(false);
      if (columnsMenuRef.current && !columnsMenuRef.current.contains(t)) setColumnsOpen(false);
      if (downloadMenuRef.current && !downloadMenuRef.current.contains(t)) setDownloadMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  // Detail projection for selected dataset.
  useEffect(() => {
    if (!activeId) {
      setDetailVersions([]);
      setDetailPreview([]);
      setDetailError(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setPreviewError(null);
    setDetailTab("overview");
    void (async () => {
      try {
        const detail = await api.getDataset(activeId);
        if (cancelled) return;
        setDetailVersions(detail.versions);
        const version =
          detail.versions.find((v) => v.status === "ready") ?? detail.versions[0] ?? null;
        if (version) {
          try {
            const prev = await api.previewDatasetVersion(version.versionId, 20);
            if (!cancelled) setDetailPreview(prev.rows ?? []);
          } catch (err) {
            if (!cancelled) {
              setDetailPreview([]);
              setPreviewError(errMsg(err, "Voorbeeld niet beschikbaar"));
            }
          }
        } else {
          setDetailPreview([]);
        }
      } catch (err) {
        if (!cancelled) {
          setDetailVersions([]);
          setDetailPreview([]);
          setDetailError(errMsg(err, "Dataset detail niet beschikbaar"));
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  async function withBusy(fn: () => Promise<void>, okMsg?: string) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      if (okMsg) toast(okMsg);
    } catch (err) {
      toast(errMsg(err, "Actie mislukt"));
    } finally {
      setBusy(false);
    }
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

  async function onCreate() {
    if (!createName.trim()) {
      toast("Naam is verplicht");
      return;
    }
    await withBusy(async () => {
      await api.createDataset({ name: createName.trim(), description: createDesc });
      setCreateName("");
      setCreateDesc("");
      setModal(null);
      await loadDatasets({ offset: 0 });
      await loadOverview({ quiet: true });
    }, "Dataset aangemaakt");
  }

  async function onUpload() {
    if (!uploadFile) {
      toast("Kies eerst een bestand");
      return;
    }
    await withBusy(async () => {
      const form = new FormData();
      form.append("file", uploadFile);
      if (createName.trim()) form.append("name", createName.trim());
      if (createDesc) form.append("description", createDesc);
      form.append("materialize", "true");
      const res = await api.uploadDataset(form);
      setPreferredJobId(res.job.jobId);
      setUploadFile(null);
      setModal(null);
      await loadDatasets({ quiet: true, offset: 0 });
      await loadJobs();
      await loadOverview({ quiet: true });
    }, "Upload in wachtrij");
  }

  async function onImportLocal() {
    if (!localPath.trim()) {
      toast("Lokaal pad is verplicht");
      return;
    }
    await withBusy(async () => {
      const res = await api.importDatasetLocal({
        path: localPath.trim(),
        name: localName.trim() || undefined,
        materialize: true,
      });
      setPreferredJobId(res.job.jobId);
      setModal(null);
      setLocalPath("");
      setLocalName("");
      await loadJobs();
      await loadDatasets({ quiet: true, offset: 0 });
      await loadOverview({ quiet: true });
    }, "Lokale import in wachtrij");
  }

  async function onImportHf() {
    if (!hfRepo.trim()) {
      toast("Repository id is verplicht");
      return;
    }
    await withBusy(async () => {
      const token = hfToken.trim() || null;
      const res = await api.importDatasetHuggingFace({
        repositoryId: hfRepo.trim(),
        revision: hfRevision.trim() || "main",
        token,
        materialize: true,
      });
      setPreferredJobId(res.job.jobId);
      setModal(null);
      setHfRepo("");
      setHfToken("");
      await loadJobs();
      await loadDatasets({ quiet: true, offset: 0 });
      await loadOverview({ quiet: true });
    }, "Hugging Face import in wachtrij");
  }

  async function onCancelDatasetJob(jobId: string) {
    await withBusy(async () => {
      await api.cancelDatasetJob(jobId);
      await loadJobs();
    }, "Annulering aangevraagd");
  }

  async function onDelete(id: string) {
    if (!window.confirm("Deze dataset verwijderen?")) return;
    await withBusy(async () => {
      await api.deleteDataset(id);
      setMenuFor(null);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (activeId === id) setActiveId(null);
      await loadDatasets({ offset: 0 });
      await loadOverview({ quiet: true });
    }, "Dataset verwijderd");
  }

  async function onIndex(id: string) {
    await withBusy(async () => {
      const detail = await api.getDataset(id);
      const version =
        detail.versions.find((v) => v.status === "ready") ?? detail.versions[0] ?? null;
      if (!version) {
        toast("Geen versie beschikbaar om te indexeren");
        return;
      }
      await api.indexDatasetVersion(id, version.versionId);
      setMenuFor(null);
      await loadJobs();
    }, "Index in wachtrij");
  }

  async function onProcessQueue() {
    await withBusy(async () => {
      const res = await api.processDatasetJobs();
      toast(`${res.processed.length} job(s) verwerkt`);
      await loadJobs();
    });
  }

  async function onBulkProcess() {
    const ids = [...selectedIds].slice(0, DS_BULK_MAX);
    if (ids.length === 0) {
      await onProcessQueue();
      return;
    }
    await withBusy(async () => {
      const res = await api.bulkMaterializeDatasets({ datasetIds: ids });
      toast(`Verwerken: ${res.succeeded} ok, ${res.failed} mislukt`);
      if (res.results.find((r) => r.ok && r.jobId)) {
        setPreferredJobId(res.results.find((r) => r.ok && r.jobId)!.jobId!);
      }
      await loadJobs();
      await loadDatasets({ quiet: true });
    });
  }

  async function onBulkIndex() {
    const ids = selectedIds.size > 0 ? [...selectedIds].slice(0, DS_BULK_MAX) : activeId ? [activeId] : [];
    if (ids.length === 0) {
      toast("Selecteer datasets of een actieve rij om te indexeren");
      return;
    }
    await withBusy(async () => {
      const res = await api.bulkIndexDatasets({ datasetIds: ids });
      toast(`Indexeren: ${res.succeeded} ok, ${res.failed} mislukt`);
      if (res.results.find((r) => r.ok && r.jobId)) {
        setPreferredJobId(res.results.find((r) => r.ok && r.jobId)!.jobId!);
      }
      await loadJobs();
    });
  }

  async function onExportDownload(id: string) {
    await withBusy(async () => {
      const detail = await api.getDataset(id);
      const ready =
        detail.versions.find((v) => v.status === "ready" && (v.kind === "export" || v.kind === "materialized")) ??
        detail.versions.find((v) => v.status === "ready") ??
        detail.versions[0] ??
        null;
      if (!ready) {
        toast("Geen exporteerbare versie");
        return;
      }
      if (ready.kind !== "export") {
        const job = await api.exportDatasetVersion(id, ready.versionId);
        setPreferredJobId(job.job.jobId);
        toast("Export job gestart — download wanneer klaar");
        await loadJobs();
        return;
      }
      const blob = await api.downloadDatasetExport(id, ready.versionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${activeRow?.name || id}.export`;
      a.click();
      URL.revokeObjectURL(url);
      setDownloadMenuOpen(false);
    }, "Download gestart");
  }

  async function onShareLink(id: string) {
    const link = `${window.location.origin}/datasets?dataset=${encodeURIComponent(id)}`;
    try {
      await navigator.clipboard.writeText(link);
      toast("Interne link gekopieerd");
    } catch {
      toast("Kopiëren mislukt — link niet gedeeld");
    }
  }

  async function onSaveTags() {
    if (!activeId) return;
    const tags = tagDraft
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    await withBusy(async () => {
      await api.patchDatasetSemantic(activeId, { tags });
      await loadDatasets({ quiet: true });
      setTagDraft("");
    }, "Tags opgeslagen");
  }

  async function onSemanticAnalyze(id: string) {
    await withBusy(async () => {
      const res = await api.analyzeDatasetSemantic(id, { enqueue: true });
      if (res.job?.jobId) setPreferredJobId(res.job.jobId);
      await loadJobs();
      await loadDatasets({ quiet: true });
    }, "Semantic analyse in wachtrij");
  }

  function openInAnalyse(id: string) {
    navigate(`/research?dataset=${encodeURIComponent(id)}`);
  }

  function openManageStorage() {
    navigate("/settings?section=opslag");
  }

  function goPage(nextOffset: number) {
    void loadDatasets({ offset: Math.max(0, nextOffset) });
  }

  async function refresh(opts?: { quiet?: boolean }) {
    await Promise.all([loadDatasets({ ...opts, offset }), loadOverview(opts), loadJobs()]);
  }

  const sidebarStatus = useMemo(() => {
    const indexing = jobs.filter((j) => {
      const t = j.jobType.toLowerCase();
      const s = j.status.toLowerCase();
      return t.includes("index") && (s === "running" || s === "queued" || s === "pending");
    }).length;
    const used = overview?.usedBytes;
    const cap = overview?.capacityBytes;
    const storageValue =
      used != null && cap != null
        ? `${formatBytes(used)} / ${formatBytes(cap)}`
        : used != null
          ? `${formatBytes(used)} / UNMEASURED`
          : "UNMEASURED";
    return [
      {
        id: "dataset-api",
        label: "Dataset API",
        value: error && !stale ? "Error" : stale ? "Stale" : loading ? "Loading" : "Ready",
        tone: (error && !stale ? "danger" : stale ? "warning" : "success") as
          | "success"
          | "warning"
          | "danger"
          | "muted",
      },
      {
        id: "dataset-jobs",
        label: "Jobs",
        value: jobsError ? "Error" : live ? "Active" : "Idle",
        tone: (jobsError ? "danger" : live ? "success" : "muted") as
          | "success"
          | "warning"
          | "danger"
          | "muted",
      },
      {
        id: "dataset-storage",
        label: "Storage",
        value: storageValue,
        tone: "muted" as const,
      },
      {
        id: "dataset-indexing",
        label: "Active Indexing",
        value: `${indexing} actief`,
        tone: (indexing > 0 ? "success" : "muted") as "success" | "warning" | "danger" | "muted",
      },
    ];
  }, [error, stale, loading, jobsError, live, jobs, overview]);

  return {
    loading,
    error,
    stale,
    lastUpdated,
    busy,
    sidebarStatus,
    online: !error || stale,
    refreshing: loading || overviewLoading || busy,
    refresh,

    datasets,
    liveRows,
    filteredRows,
    filterCounts,
    filter,
    setFilter,
    view,
    setView,
    filtersOpen,
    setFiltersOpen,
    columnsOpen,
    setColumnsOpen,
    visibleColumns,
    toggleColumn,
    queryInput,
    setQueryInput,
    query,
    setQuery,
    typeFilter,
    setTypeFilter,
    updatedFilter,
    setUpdatedFilter,
    selectedIds,
    toggleSelected,
    toggleSelectAll,
    activeId,
    setActiveId,
    activeRow,
    activeRecord,
    menuFor,
    setMenuFor,
    menuRef,
    importMenuOpen,
    setImportMenuOpen,
    importMenuRef,
    externalMenuOpen,
    setExternalMenuOpen,
    externalMenuRef,
    columnsMenuRef,
    downloadMenuOpen,
    setDownloadMenuOpen,
    downloadMenuRef,

    detailTab,
    setDetailTab,
    detailVersions,
    detailPreview,
    detailError,
    previewError,
    detailLoading,
    tagDraft,
    setTagDraft,
    onSaveTags,

    overview,
    overviewLoading,
    overviewError,
    metrics,
    storage,
    pipelineItems,
    activeJobCount,
    healthItems,
    filteredActivity,
    activityPeriod,
    setActivityPeriod,

    offset,
    hasMore,
    catalogTotal,
    pageSize: DS_PAGE_SIZE,
    goPage,

    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    clearActivityView,
    live,
    onCancelDatasetJob,

    modal,
    setModal,
    createName,
    setCreateName,
    createDesc,
    setCreateDesc,
    localPath,
    setLocalPath,
    localName,
    setLocalName,
    uploadFile,
    setUploadFile,
    hfRepo,
    setHfRepo,
    hfRevision,
    setHfRevision,
    hfToken,
    setHfToken,
    onCreate,
    onUpload,
    onImportLocal,
    onImportHf,
    onDelete,
    onIndex,
    onProcessQueue,
    onBulkProcess,
    onBulkIndex,
    onExportDownload,
    onShareLink,
    onSemanticAnalyze,
    openInAnalyse,
    openManageStorage,
    loadDatasets,
  };
}

export type DatasetsWorkspace = ReturnType<typeof useDatasetsWorkspace>;
