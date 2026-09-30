/**
 * Onderzoek & Kennis → Datasets workspace orchestration.
 *
 * Canonical authorities:
 * - Inventory: GET /api/datasets via api.listDatasets
 * - Overview KPIs/storage/services: GET /api/datasets/overview
 * - Jobs/activity: useDatasetActivity → listDatasetJobs (adaptive polling)
 * - Mutations: create/upload/import/delete/index/cancel via DatasetService routes
 *
 * No page-local queue, scheduler, or fixture production fallback.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import {
  DH_TYPE_OPTIONS,
  DH_UPDATED_OPTIONS,
  type DhFilterId,
  type DhRow,
} from "../../mocks/datasets-dashboard";
import { useAppToast } from "../../state/useAppToast";
import type {
  DatasetOverview,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetVersion,
} from "../../types/api";
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
export type ModalKind = "create" | "import" | "hf" | null;
export type DetailTab = "overview" | "preview" | "versions" | "metadata" | "activity";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function useDatasetsWorkspace() {
  const toast = useAppToast();
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);

  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const loadDatasetsRef = useRef<(opts?: { quiet?: boolean }) => Promise<void>>(async () => undefined);
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
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<(typeof DH_TYPE_OPTIONS)[number]>(DH_TYPE_OPTIONS[0]);
  const [updatedFilter, setUpdatedFilter] =
    useState<(typeof DH_UPDATED_OPTIONS)[number]>(DH_UPDATED_OPTIONS[0]);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");

  const [detailVersions, setDetailVersions] = useState<DatasetVersion[]>([]);
  const [detailPreview, setDetailPreview] = useState<DatasetPreviewRow[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [modal, setModal] = useState<ModalKind>(null);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [hfRepo, setHfRepo] = useState("");
  const [hfRevision, setHfRevision] = useState("main");
  const [hfToken, setHfToken] = useState("");

  const liveRows = useMemo(
    () => datasets.map((ds) => recordToRow(ds, jobs)),
    [datasets, jobs],
  );

  const filterCounts = useMemo(() => countDatasetsByFilter(liveRows), [liveRows]);

  const filteredRows = useMemo(
    () =>
      filterDatasetRows(liveRows, {
        filter,
        query,
        typeFilter,
        updatedFilter,
      }),
    [liveRows, filter, query, typeFilter, updatedFilter],
  );

  // Reconcile selection + active row against filtered inventory.
  useEffect(() => {
    setSelectedIds((prev) => reconcileSelection(prev, filteredRows.map((r) => r.id)));
    if (activeId && !filteredRows.some((r) => r.id === activeId)) {
      setActiveId(filteredRows[0]?.id ?? null);
    }
  }, [filteredRows, activeId]);

  const activeRow: DhRow | null = useMemo(
    () => filteredRows.find((r) => r.id === activeId) ?? liveRows.find((r) => r.id === activeId) ?? null,
    [filteredRows, liveRows, activeId],
  );

  const activeRecord = useMemo(
    () => datasets.find((d) => d.datasetId === activeId) ?? null,
    [datasets, activeId],
  );

  const metrics = useMemo(() => {
    const total = overview?.totalDatasets ?? liveRows.length;
    const local =
      overview?.bySourceType
        ? Object.entries(overview.bySourceType).reduce((sum, [k, v]) => {
            const kind = k.toLowerCase();
            if (kind.includes("local") || kind.includes("upload") || kind === "file" || kind === "path") {
              return sum + v;
            }
            return sum;
          }, 0)
        : liveRows.filter((r) => r.sourceKind === "local").length;
    const external = Math.max(0, total - local);
    const sizeBytes = overview?.attributableBytes ?? liveRows.reduce((s, r) => s + (r.byteSize ?? 0), 0);
    const indexed = liveRows.filter((r) => r.embeddings.kind === "indexed").length;
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
      capacityLabel:
        overview?.capacityBytes != null ? formatBytes(overview.capacityBytes) : null,
      usedBytes: overview?.usedBytes ?? null,
      capacityBytes: overview?.capacityBytes ?? null,
    };
  }, [overview, liveRows]);

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

    // Fallback projection from inventory byteSize only — cache is estimated.
    const totalBytes = liveRows.reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const localBytes = liveRows
      .filter((r) => r.sourceKind === "local")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const processingBytes = liveRows
      .filter((r) => r.status === "processing" || r.status === "validating")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const other = Math.max(0, totalBytes - localBytes - processingBytes);
    const cacheEstimate = Math.min(totalBytes * 0.18, totalBytes);
    return {
      usedLabel: formatBytes(totalBytes),
      capacityLabel: null as string | null,
      pct: null as number | null,
      segments: [
        { id: "local", label: "Local Datasets", bytesLabel: formatBytes(localBytes), pct: 0, color: "#2ec4b6" },
        {
          id: "cache",
          label: "Cache & Indexes (est.)",
          bytesLabel: formatBytes(cacheEstimate),
          pct: 0,
          color: "#4f8cff",
        },
        {
          id: "processing",
          label: "Processing",
          bytesLabel: formatBytes(processingBytes),
          pct: 0,
          color: "#9b5cff",
        },
        { id: "other", label: "Other", bytesLabel: formatBytes(other), pct: 0, color: "#6b7280" },
      ],
      estimated: true,
      measurementNote: "Estimated from inventory byteSize — cache not measured",
    };
  }, [overview, liveRows]);

  const pipelineItems = useMemo(() => {
    const active = jobs
      .filter((j) => {
        const s = j.status.toLowerCase();
        return s === "running" || s === "queued" || s === "pending";
      })
      .slice(0, 4);
    if (active.length === 0) {
      return [
        {
          id: "idle",
          title: "Queue idle",
          detail: "No active dataset jobs",
          pct: null as number | null,
          eta: "—",
          tone: "cyan" as const,
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
      };
    });
  }, [jobs, datasets]);

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

  const loadDatasets = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) {
      setLoading(true);
      setError(null);
    }
    try {
      const res = await api.listDatasets(200);
      setDatasets(res.datasets);
      setStale(false);
      setLastUpdated(new Date().toISOString());
      setError(null);
      setActiveId((prev) => {
        if (prev && res.datasets.some((d) => d.datasetId === prev)) return prev;
        return res.datasets[0]?.datasetId ?? null;
      });
    } catch (err) {
      const msg = errMsg(err, "Failed to load datasets");
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
  }, [datasets.length]);

  const loadOverview = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setOverviewLoading(true);
    try {
      const res = await api.getDatasetsOverview();
      setOverview(res.overview);
      setOverviewError(null);
    } catch (err) {
      setOverviewError(errMsg(err, "Failed to load dataset overview"));
      if (!opts?.quiet) setOverview(null);
    } finally {
      if (!opts?.quiet) setOverviewLoading(false);
    }
  }, []);

  loadDatasetsRef.current = loadDatasets;
  loadOverviewRef.current = loadOverview;

  useEffect(() => {
    void loadDatasets();
    void loadOverview();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setMenuFor(null);
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
              setPreviewError(errMsg(err, "Preview unavailable"));
            }
          }
        } else {
          setDetailPreview([]);
        }
      } catch (err) {
        if (!cancelled) {
          setDetailVersions([]);
          setDetailPreview([]);
          setDetailError(errMsg(err, "Dataset detail unavailable"));
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
      toast(errMsg(err, "Action failed"));
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

  async function onCreate() {
    if (!createName.trim()) {
      toast("Name is required");
      return;
    }
    await withBusy(async () => {
      await api.createDataset({ name: createName.trim(), description: createDesc });
      setCreateName("");
      setCreateDesc("");
      setModal(null);
      await loadDatasets();
      await loadOverview({ quiet: true });
    }, "Dataset created");
  }

  async function onUpload() {
    if (!uploadFile) {
      toast("Choose a file first");
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
      await loadDatasets({ quiet: true });
      await loadJobs();
      await loadOverview({ quiet: true });
    }, "Upload queued");
  }

  async function onImportLocal() {
    if (!localPath.trim()) {
      toast("Local path is required");
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
      await loadDatasets({ quiet: true });
      await loadOverview({ quiet: true });
    }, "Local import queued");
  }

  async function onImportHf() {
    if (!hfRepo.trim()) {
      toast("Repository id is required");
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
      setHfToken(""); // never persist token
      await loadJobs();
      await loadDatasets({ quiet: true });
      await loadOverview({ quiet: true });
    }, "Hugging Face repository import queued");
  }

  async function onCancelDatasetJob(jobId: string) {
    await withBusy(async () => {
      await api.cancelDatasetJob(jobId);
      await loadJobs();
    }, "Cancel requested");
  }

  async function onDelete(id: string) {
    if (!window.confirm("Delete this dataset?")) return;
    await withBusy(async () => {
      await api.deleteDataset(id);
      setMenuFor(null);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (activeId === id) setActiveId(null);
      await loadDatasets();
      await loadOverview({ quiet: true });
    }, "Dataset deleted");
  }

  async function onIndex(id: string) {
    await withBusy(async () => {
      const detail = await api.getDataset(id);
      const version =
        detail.versions.find((v) => v.status === "ready") ?? detail.versions[0] ?? null;
      if (!version) {
        toast("No version available to index");
        return;
      }
      await api.indexDatasetVersion(id, version.versionId);
      setMenuFor(null);
      await loadJobs();
    }, "Index queued");
  }

  async function onProcessQueue() {
    await withBusy(async () => {
      const res = await api.processDatasetJobs();
      toast(`Processed ${res.processed.length} job(s)`);
      await loadJobs();
    });
  }

  function openManageStorage() {
    navigate("/settings?section=opslag");
  }

  async function refresh(opts?: { quiet?: boolean }) {
    await Promise.all([
      loadDatasets(opts),
      loadOverview(opts),
      loadJobs(),
    ]);
  }

  const sidebarStatus = useMemo(
    () => [
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
        id: "dataset-inventory",
        label: "Inventory",
        value: String(filterCounts.all),
        tone: "muted" as const,
      },
    ],
    [error, stale, loading, jobsError, live, filterCounts.all],
  );

  return {
    // shell
    loading,
    error,
    stale,
    lastUpdated,
    busy,
    sidebarStatus,
    online: !error || stale,
    refreshing: loading || overviewLoading || busy,
    refresh,

    // inventory
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

    // detail
    detailTab,
    setDetailTab,
    detailVersions,
    detailPreview,
    detailError,
    previewError,
    detailLoading,

    // overview widgets
    overview,
    overviewLoading,
    overviewError,
    metrics,
    storage,
    pipelineItems,
    healthItems,

    // activity
    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    clearActivityView,
    live,
    onCancelDatasetJob,

    // modals / mutations
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
    openManageStorage,
    loadDatasets,
  };
}

export type DatasetsWorkspace = ReturnType<typeof useDatasetsWorkspace>;
