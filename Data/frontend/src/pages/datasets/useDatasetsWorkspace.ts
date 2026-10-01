/**
 * Onderzoek & Kennis → Datasets workspace orchestration (canonical `/datasets`).
 *
 * Composes inventory, detail, activity, mutations, and learning fleet.
 * DatasetService remains authority — no fake backends / production mocks.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppToast } from "../../state/useAppToast";
import { activityPeriodToQueryParams } from "./datasetFilterParams";
import { buildCatalogHealthItems } from "./datasetHealth";
import {
  formatBytes,
  jobProgressDetail,
  measuredProgressPct,
  phaseLabel,
  relativeTime,
} from "./datasetsMapping";
import { DS_ACTIVITY_PERIODS } from "./constants";
import { useDatasetActivity } from "./useDatasetActivity";
import { useDatasetDetail, type DetailTab } from "./useDatasetDetail";
import { useDatasetInventory } from "./useDatasetInventory";
import { useDatasetLearningFleet } from "./useDatasetLearningFleet";
import { useDatasetMutations, type ModalKind } from "./useDatasetMutations";

export type { DetailTab, ModalKind };
export type ViewMode = "list" | "grid";
export type ImportMenuKind = "upload" | "path" | null;

export function useDatasetsWorkspace() {
  const toast = useAppToast();
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);
  const importMenuRef = useRef<HTMLDivElement>(null);
  const externalMenuRef = useRef<HTMLDivElement>(null);
  const columnsMenuRef = useRef<HTMLDivElement>(null);
  const downloadMenuRef = useRef<HTMLDivElement>(null);

  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const [externalMenuOpen, setExternalMenuOpen] = useState(false);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [activityPeriod, setActivityPeriod] = useState<string>(DS_ACTIVITY_PERIODS[0]);

  const activityWindow = useMemo(
    () => activityPeriodToQueryParams(activityPeriod),
    [activityPeriod],
  );

  const inventoryHolder = useRef<{
    loadDatasets: (o?: { quiet?: boolean; offset?: number }) => Promise<void>;
    loadOverview: (o?: { quiet?: boolean }) => Promise<void>;
  }>({
    loadDatasets: async () => undefined,
    loadOverview: async () => undefined,
  });

  const {
    jobs,
    jobsError,
    jobsTotal,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    loadJobs,
    clearActivityView,
    live,
  } = useDatasetActivity({
    createdAfter: activityWindow.createdAfter ?? null,
    createdBefore: activityWindow.createdBefore ?? null,
    limit: 100,
    onLifecycleChange: () => {
      void inventoryHolder.current.loadDatasets({ quiet: true });
      void inventoryHolder.current.loadOverview({ quiet: true });
    },
  });

  const inventory = useDatasetInventory({ jobs });
  inventoryHolder.current = {
    loadDatasets: inventory.loadDatasets,
    loadOverview: inventory.loadOverview,
  };

  const detail = useDatasetDetail({
    activeId: inventory.activeId,
    onSelectedRecord: inventory.setSelectedRecord,
  });

  // Dataset-scoped activity when Activity tab is open.
  const detailActivity = useDatasetActivity({
    datasetId: inventory.activeId,
    limit: 50,
    enabled: Boolean(inventory.activeId) && detail.detailTab === "activity",
  });

  const learning = useDatasetLearningFleet({
    enabled: inventory.workspaceMode === "learning",
  });

  const mutations = useDatasetMutations({
    activeId: inventory.activeId,
    selectedIds: inventory.selectedIds,
    selectedVersionId: detail.selectedVersionId,
    selectedVersion: detail.selectedVersion,
    activeRecord: inventory.activeRecord,
    tagChips: detail.tagChips,
    setTagChips: detail.setTagChips,
    tagInput: detail.tagInput,
    setTagInput: detail.setTagInput,
    editDisplayName: detail.editDisplayName,
    editCategory: detail.editCategory,
    setSemanticEditing: detail.setSemanticEditing,
    setActiveId: inventory.setActiveId,
    setSelectedIds: inventory.setSelectedIds,
    setMenuFor,
    setPreferredJobId,
    loadDatasets: inventory.loadDatasets,
    loadOverview: inventory.loadOverview,
    loadJobs,
    bumpDetail: detail.bumpDetail,
    jobs,
  });

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(t)) setMenuFor(null);
      if (importMenuRef.current && !importMenuRef.current.contains(t)) setImportMenuOpen(false);
      if (externalMenuRef.current && !externalMenuRef.current.contains(t)) setExternalMenuOpen(false);
      if (columnsMenuRef.current && !columnsMenuRef.current.contains(t)) inventory.setColumnsOpen(false);
      if (downloadMenuRef.current && !downloadMenuRef.current.contains(t)) setDownloadMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [inventory]);

  const storage = useMemo(() => {
    const overview = inventory.overview;
    const liveRows = inventory.liveRows;
    if (overview?.storageBreakdown?.length) {
      const usedBytes = overview.attributableBytes ?? overview.usedBytes ?? 0;
      const capacity = overview.capacityBytes ?? null;
      return {
        usedLabel: formatBytes(usedBytes),
        capacityLabel: capacity != null ? formatBytes(capacity) : null,
        // Dataset Opslag bar reflects attributable corpus bytes, not whole-disk usage.
        pct:
          capacity != null && capacity > 0
            ? Math.min(100, Math.round((usedBytes / capacity) * 100))
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
    return {
      usedLabel: formatBytes(totalBytes),
      capacityLabel: null as string | null,
      pct: null as number | null,
      segments: [
        {
          id: "local",
          label: "Lokale datasets",
          bytesLabel: formatBytes(
            liveRows.filter((r) => r.sourceKind === "local").reduce((s, r) => s + (r.byteSize ?? 0), 0),
          ),
          pct: 0,
          color: "#2ec4b6",
        },
      ],
      estimated: true,
      measurementNote: "Geschat uit inventory byteSize — capaciteit UNMEASURED",
    };
  }, [inventory.overview, inventory.liveRows]);

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
        inventory.datasets.find((d) => d.datasetId === j.datasetId)?.displayName ||
        inventory.datasets.find((d) => d.datasetId === j.datasetId)?.name ||
        j.datasetId ||
        "dataset";
      return {
        id: j.jobId,
        title: j.jobType.replace(/_/g, " "),
        detail: jobProgressDetail(j) || dsName,
        pct,
        eta: j.phase ? phaseLabel(j.phase) : relativeTime(j.updatedAt),
        tone: (j.jobType.toLowerCase().includes("index") ? "cyan" : "purple") as "cyan" | "purple",
        jobId: j.jobId as string | null,
      };
    });
  }, [jobs, inventory.datasets]);

  const activeJobCount = useMemo(
    () =>
      jobs.filter((j) => {
        const s = j.status.toLowerCase();
        return s === "running" || s === "queued" || s === "pending";
      }).length,
    [jobs],
  );

  const healthItems = useMemo(
    () => buildCatalogHealthItems(inventory.overview),
    [inventory.overview],
  );

  // Activity entries already server-filtered by createdAfter — no client window filter.
  const filteredActivity = activityEntries;

  const sidebarStatus = useMemo(() => {
    const indexing = jobs.filter((j) => {
      const t = j.jobType.toLowerCase();
      const s = j.status.toLowerCase();
      return t.includes("index") && (s === "running" || s === "queued" || s === "pending");
    }).length;
    const used = inventory.overview?.usedBytes;
    const cap = inventory.overview?.capacityBytes;
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
        value:
          inventory.error && !inventory.stale
            ? "Error"
            : inventory.stale
              ? "Stale"
              : inventory.loading && inventory.liveRows.length === 0
                ? "Loading"
                : "Ready",
        tone: (inventory.error && !inventory.stale
          ? "danger"
          : inventory.stale
            ? "warning"
            : "success") as "success" | "warning" | "danger" | "muted",
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
  }, [inventory.error, inventory.stale, inventory.loading, jobsError, live, jobs, inventory.overview]);

  async function refresh(opts?: { quiet?: boolean }) {
    await Promise.all([
      inventory.loadDatasets({ ...opts, offset: inventory.offset }),
      inventory.loadOverview(opts),
      loadJobs(),
      inventory.workspaceMode === "learning" ? learning.loadFleet() : Promise.resolve(),
    ]);
  }

  function openInAnalyse(id: string) {
    navigate(`/research?dataset=${encodeURIComponent(id)}`);
  }

  function openManageStorage() {
    navigate("/settings?section=opslag");
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

  return {
    loading: inventory.loading,
    error: inventory.error,
    stale: inventory.stale,
    lastUpdated: inventory.lastUpdated,
    busy: mutations.busy,
    sidebarStatus,
    online: !inventory.error || inventory.stale,
    refreshing: inventory.loading || inventory.overviewLoading || mutations.busy,
    refresh,

    datasets: inventory.datasets,
    liveRows: inventory.liveRows,
    filteredRows: inventory.filteredRows,
    filterCounts: inventory.filterCounts,
    filter: inventory.filter,
    setFilter: inventory.setFilter,
    view: inventory.view,
    setView: inventory.setView,
    filtersOpen: inventory.filtersOpen,
    setFiltersOpen: inventory.setFiltersOpen,
    columnsOpen: inventory.columnsOpen,
    setColumnsOpen: inventory.setColumnsOpen,
    visibleColumns: inventory.visibleColumns,
    toggleColumn: inventory.toggleColumn,
    queryInput: inventory.queryInput,
    setQueryInput: inventory.setQueryInput,
    query: inventory.query,
    setQuery: inventory.setQueryInput, // debounced via queryInput
    typeFilter: inventory.typeFilter,
    setTypeFilter: inventory.setTypeFilter,
    updatedFilter: inventory.updatedFilter,
    setUpdatedFilter: inventory.setUpdatedFilter,
    selectedIds: inventory.selectedIds,
    toggleSelected: inventory.toggleSelected,
    toggleSelectAll: inventory.toggleSelectAll,
    activeId: inventory.activeId,
    setActiveId: inventory.setActiveId,
    activeRow: inventory.activeRow,
    activeRecord: inventory.activeRecord ?? detail.detailRecord,
    selectionOutsidePage: inventory.selectionOutsidePage,
    workspaceMode: inventory.workspaceMode,
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

    detailTab: detail.detailTab,
    setDetailTab: detail.setDetailTab,
    detailVersions: detail.detailVersions,
    selectedVersionId: detail.selectedVersionId,
    setSelectedVersionId: detail.setSelectedVersionId,
    selectedVersion: detail.selectedVersion,
    detailPreview: detail.detailPreview,
    detailError: detail.detailError,
    previewError: detail.previewError,
    detailLoading: detail.detailLoading,
    recovery: detail.recovery,
    sampleTab: detail.sampleTab,
    setSampleTab: detail.setSampleTab,
    tagChips: detail.tagChips,
    tagInput: detail.tagInput,
    setTagInput: detail.setTagInput,
    tagDraft: detail.tagChips.join(", "),
    setTagDraft: (v: string) => detail.setTagChips(
      v.split(",").map((t) => t.trim()).filter(Boolean),
    ),
    editDisplayName: detail.editDisplayName,
    setEditDisplayName: detail.setEditDisplayName,
    editCategory: detail.editCategory,
    setEditCategory: detail.setEditCategory,
    semanticEditing: detail.semanticEditing,
    setSemanticEditing: detail.setSemanticEditing,
    onSaveTags: mutations.onSaveTags,
    onAddTagChip: mutations.onAddTagChip,
    onRemoveTagChip: mutations.onRemoveTagChip,

    overview: inventory.overview,
    overviewLoading: inventory.overviewLoading,
    overviewError: inventory.overviewError,
    metrics: inventory.metrics,
    storage,
    pipelineItems,
    activeJobCount,
    healthItems,
    filteredActivity,
    activityPeriod,
    setActivityPeriod,

    offset: inventory.offset,
    hasMore: inventory.hasMore,
    catalogTotal: inventory.catalogTotal,
    pageSize: inventory.pageSize,
    goPage: inventory.goPage,

    jobs,
    jobsError,
    jobsTotal,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    clearActivityView,
    live,
    onCancelDatasetJob: mutations.onCancelDatasetJob,
    onRetryDatasetJob: mutations.onRetryDatasetJob,
    detailJobs: detailActivity.jobs,
    detailJobsError: detailActivity.jobsError,
    detailActivityEntries: detailActivity.activityEntries,

    modal: mutations.modal,
    setModal: mutations.setModal,
    closeModal: mutations.closeModal,
    // Backward-compatible form field accessors for DatasetsModals
    createName: mutations.createForm.name,
    setCreateName: (v: string) => mutations.setCreateForm((f) => ({ ...f, name: v })),
    createDesc: mutations.createForm.description,
    setCreateDesc: (v: string) => mutations.setCreateForm((f) => ({ ...f, description: v })),
    localPath: mutations.localImportForm.path,
    setLocalPath: (v: string) => mutations.setLocalImportForm((f) => ({ ...f, path: v })),
    localName: mutations.localImportForm.name,
    setLocalName: (v: string) => mutations.setLocalImportForm((f) => ({ ...f, name: v })),
    uploadFile: mutations.uploadForm.file,
    setUploadFile: (v: File | null) => mutations.setUploadForm((f) => ({ ...f, file: v })),
    hfRepo: mutations.hfImportForm.repositoryId,
    setHfRepo: (v: string) => mutations.setHfImportForm((f) => ({ ...f, repositoryId: v })),
    hfRevision: mutations.hfImportForm.revision,
    setHfRevision: (v: string) => mutations.setHfImportForm((f) => ({ ...f, revision: v })),
    hfToken: mutations.hfImportForm.token,
    setHfToken: (v: string) => mutations.setHfImportForm((f) => ({ ...f, token: v })),
    createForm: mutations.createForm,
    setCreateForm: mutations.setCreateForm,
    uploadForm: mutations.uploadForm,
    setUploadForm: mutations.setUploadForm,
    localImportForm: mutations.localImportForm,
    setLocalImportForm: mutations.setLocalImportForm,
    hfImportForm: mutations.hfImportForm,
    setHfImportForm: mutations.setHfImportForm,
    onCreate: mutations.onCreate,
    onUpload: mutations.onUpload,
    onImportLocal: mutations.onImportLocal,
    onImportHf: mutations.onImportHf,
    onDelete: mutations.onDelete,
    onIndex: mutations.onIndex,
    onBulkProcess: mutations.onBulkProcess,
    onBulkIndex: mutations.onBulkIndex,
    onExportDownload: mutations.onExportDownload,
    onDownloadExport: mutations.onDownloadExport,
    onEnqueueExport: mutations.onEnqueueExport,
    exportState: mutations.exportState,
    canProcess: mutations.canProcess,
    onShareLink,
    onSemanticAnalyze: mutations.onSemanticAnalyze,
    onSaveSemantic: mutations.onSaveSemantic,
    onValidate: mutations.onValidate,
    onDedupe: mutations.onDedupe,
    onTransform: mutations.onTransform,
    onSplit: mutations.onSplit,
    onTokenize: mutations.onTokenize,
    onScanPii: mutations.onScanPii,
    onContaminationScan: mutations.onContaminationScan,
    onMaterialize: mutations.onMaterialize,
    onLearn: mutations.onLearn,
    onDuplicate: mutations.onDuplicate,
    onRefreshLibrary: mutations.onRefreshLibrary,
    onPreflight: mutations.onPreflight,
    openInAnalyse,
    openManageStorage,
    loadDatasets: inventory.loadDatasets,

    // Learning fleet
    fleet: learning.fleet,
    fleetTotal: learning.fleetTotal,
    fleetLoading: learning.fleetLoading,
    fleetError: learning.fleetError,
    loadFleet: learning.loadFleet,
  };
}

export type DatasetsWorkspace = ReturnType<typeof useDatasetsWorkspace>;
