/**
 * Leviathan V2 Dataset Management — workspace orchestration.
 *
 * Server-side search/pagination via api.listDatasets(limit, {offset, q, source,
 * category, split, sort}) plus api.getDatasetsOverview() for bounded KPI /
 * storage / services / tag truth. Type and status filters are heuristic NL
 * labels derived from multiple backend fields (detectedFormat + metadata,
 * status + brainStatus + canonicalState) and are therefore applied on the
 * current page only — they are not backend query columns.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useAppToast } from "../../state/useAppToast";
import type {
  DatasetJob,
  DatasetOverview,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetRecoveryAssessment,
  DatasetVersion,
} from "../../types/api";
import { isActiveJob, isCompletedJob } from "../datasets/datasetActivity";
import { useDatasetActivity } from "../datasets/useDatasetActivity";
import { mapDatasetStatus } from "../pixel/datasetStatus";
import {
  DM_PAGE_SIZE,
  DM_SEARCH_DEBOUNCE_MS,
  DM_CATEGORY_FILTERS,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
  DM_UPLOAD_SUFFIXES,
  type DatasetSampleTab,
} from "./constants";
import {
  categoryForDataset,
  displayNameForDataset,
  fileSuffix,
  mapTypeLabel,
  pickUsableVersion,
  sourceMatchesFilter,
  splitLabelFromVersion,
  tagsForDataset,
  triggerBlobDownload,
} from "./viewModels";

export type ModalKind = "create" | "local" | "hf" | "delete" | null;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function useDatasetManagementWorkspace() {
  const toast = useAppToast();
  const uploadRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DatasetRecord | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailEpoch, setDetailEpoch] = useState(0);

  const [preview, setPreview] = useState<DatasetPreviewRow[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sampleTab, setSampleTab] = useState<DatasetSampleTab>("JSON");

  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState(DM_TYPE_FILTERS[0]);
  const [sourceFilter, setSourceFilter] = useState(DM_SOURCE_FILTERS[0]);
  const [categoryFilter, setCategoryFilter] = useState(DM_CATEGORY_FILTERS[0]);
  const [splitFilter, setSplitFilter] = useState(DM_SPLIT_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(DM_STATUS_FILTERS[0]);

  const [recovery, setRecovery] = useState<DatasetRecoveryAssessment | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editTags, setEditTags] = useState("");
  const [semanticEditing, setSemanticEditing] = useState(false);

  const [modal, setModal] = useState<ModalKind>(null);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [createLicense, setCreateLicense] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [localDesc, setLocalDesc] = useState("");
  const [hfRepo, setHfRepo] = useState("");
  const [hfRevision, setHfRevision] = useState("main");
  const [hfFilename, setHfFilename] = useState("");
  const [hfName, setHfName] = useState("");
  const [hfDesc, setHfDesc] = useState("");
  const [hfToken, setHfToken] = useState("");

  const [exportArtifact, setExportArtifact] = useState<{
    datasetId: string;
    versionId: string;
    jobId: string;
  } | null>(null);
  const exportWatchRef = useRef<string | null>(null);
  const prevExportJobsRef = useRef<Map<string, DatasetJob>>(new Map());

  // Debounce search input → query (drives server refetch).
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(queryInput.trim()), DM_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [queryInput]);

  const loadPage = useCallback(
    async (opts?: { quiet?: boolean; offset?: number; preferId?: string | null }) => {
      const pageOffset = opts?.offset ?? offset;
      if (!opts?.quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await api.listDatasets(DM_PAGE_SIZE, {
          offset: pageOffset,
          q: query || undefined,
          source: sourceFilter === DM_SOURCE_FILTERS[0] ? undefined : sourceFilter,
          category: categoryFilter === DM_CATEGORY_FILTERS[0] ? undefined : categoryFilter,
          split: splitFilter === DM_SPLIT_FILTERS[0] ? undefined : splitFilter,
          sort: "created_at_desc",
        });
        setDatasets(res.datasets);
        setTotal(res.total ?? res.datasets.length);
        setOffset(res.offset ?? pageOffset);
        setHasMore(Boolean(res.hasMore));
        setSelectedId((prev) => {
          if (opts?.preferId && res.datasets.some((d) => d.datasetId === opts.preferId)) {
            return opts.preferId;
          }
          if (res.datasets.length === 0) return null;
          if (prev && res.datasets.some((d) => d.datasetId === prev)) return prev;
          return res.datasets[0].datasetId;
        });
        if (opts?.quiet) setError(null);
      } catch (err) {
        setError(errMsg(err, "Datasets laden mislukt"));
        if (!opts?.quiet) setDatasets([]);
      } finally {
        if (!opts?.quiet) setLoading(false);
      }
    },
    [offset, query, sourceFilter, categoryFilter, splitFilter],
  );

  const loadOverview = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setOverviewLoading(true);
    try {
      const res = await api.getDatasetsOverview();
      setOverview(res.overview);
      setOverviewError(null);
    } catch (err) {
      setOverviewError(errMsg(err, "Overzicht laden mislukt"));
    } finally {
      if (!opts?.quiet) setOverviewLoading(false);
    }
  }, []);

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
      void loadPage({ quiet: true });
      void loadOverview({ quiet: true });
      setDetailEpoch((n) => n + 1);
    },
  });

  const selected = datasets.find((d) => d.datasetId === selectedId) ?? detail;
  const selectedVersion =
    versions.find((v) => v.versionId === selectedVersionId) ??
    pickUsableVersion(versions);

  useEffect(() => {
    const prev = prevExportJobsRef.current;
    for (const job of jobs) {
      if (job.jobType !== "export") continue;
      const old = prev.get(job.jobId);
      if (old && old.status === job.status) continue;
      if (isCompletedJob(job)) {
        const exportVersionId =
          typeof job.result?.versionId === "string" ? job.result.versionId : null;
        const datasetId = job.datasetId;
        if (exportVersionId && datasetId) {
          setExportArtifact({ datasetId, versionId: exportVersionId, jobId: job.jobId });
          if (exportWatchRef.current === job.jobId) {
            toast("Export klaar — download beschikbaar");
          }
        }
      }
    }
    prevExportJobsRef.current = new Map(jobs.map((j) => [j.jobId, j]));
  }, [jobs, toast]);

  // Initial load.
  useEffect(() => {
    void loadPage({ offset: 0 });
    void loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load
  }, []);

  // Refetch page when search/filters change (server-side).
  const isFirstFilterRun = useRef(true);
  useEffect(() => {
    if (isFirstFilterRun.current) {
      isFirstFilterRun.current = false;
      return;
    }
    void loadPage({ offset: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, sourceFilter, categoryFilter, splitFilter]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setVersions([]);
      setSelectedVersionId(null);
      setDetailError(null);
      setRecovery(null);
      setSemanticEditing(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailError(null);
      try {
        const [res, recoveryRes] = await Promise.all([
          api.getDataset(selectedId),
          api.getDatasetRecovery(selectedId).catch(() => null),
        ]);
        if (cancelled) return;
        setDetail(res.dataset);
        setVersions(res.versions);
        setSelectedVersionId((prev) => {
          if (prev && res.versions.some((v) => v.versionId === prev)) return prev;
          return pickUsableVersion(res.versions)?.versionId ?? null;
        });
        setRecovery(recoveryRes?.recovery ?? null);
        setEditDisplayName(displayNameForDataset(res.dataset));
        setEditCategory(categoryForDataset(res.dataset));
        setEditTags(tagsForDataset(res.dataset).join(", "));
        setSemanticEditing(false);
      } catch (err) {
        if (!cancelled) {
          setDetail(null);
          setVersions([]);
          setSelectedVersionId(null);
          setRecovery(null);
          setDetailError(errMsg(err, "Details laden mislukt"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, detailEpoch]);

  useEffect(() => {
    if (!selectedVersionId) {
      setPreview([]);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setPreviewError(null);
      try {
        const res = await api.previewDatasetVersion(selectedVersionId, 20);
        if (cancelled) return;
        setPreview(res.rows);
      } catch (err) {
        if (!cancelled) {
          setPreview([]);
          setPreviewError(errMsg(err, "Voorbeeld niet beschikbaar"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedVersionId]);

  async function withBusy(fn: () => Promise<void>, okMsg?: string) {
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

  // Type/status filters are heuristic NL labels — applied on the fetched page only.
  const filtered = useMemo(() => {
    return datasets.filter((ds) => {
      const typeLabel = mapTypeLabel(ds);
      const statusNl = mapDatasetStatus(
        ds.status,
        ds.brainStatus ?? ds.brain?.brainStatus,
        ds.canonicalState ?? ds.learningState?.canonicalState ?? ds.brain?.canonicalState,
      );
      if (typeFilter !== DM_TYPE_FILTERS[0] && typeLabel !== typeFilter) return false;
      if (!sourceMatchesFilter(ds.sourceType, sourceFilter)) return false;
      if (statusFilter !== DM_STATUS_FILTERS[0] && statusNl !== statusFilter) return false;
      return true;
    });
  }, [datasets, typeFilter, sourceFilter, statusFilter]);

  const activeJobs = useMemo(() => jobs.filter(isActiveJob), [jobs]);

  const samplePreview = useMemo(() => {
    if (previewError) return previewError;
    if (preview.length === 0) {
      return selectedVersion
        ? "Geen voorbeeldrijen voor deze versie."
        : "Selecteer een dataset met versie.";
    }
    return null;
  }, [preview, previewError, selectedVersion]);

  function actionDisabledReason(actionId: string): string | null {
    const needsSelection = ["delete", "learn", "dup", "index", "validate", "export"];
    const needsVersion = ["index", "validate", "export"];
    if (needsSelection.includes(actionId) && !selectedId) {
      return "Selecteer eerst een dataset";
    }
    if (needsVersion.includes(actionId) && !selectedVersionId) {
      return "Selecteer eerst een datasetversie";
    }
    if (actionId === "learn" && selectedId) {
      const ds = datasets.find((d) => d.datasetId === selectedId);
      const brain = ds?.brainStatus ?? ds?.brain?.brainStatus;
      if (brain === "learned") {
        return "Al geleerd — gebruik Index opnieuw opbouwen om opnieuw te leren";
      }
      if (brain === "indexing" || brain === "queued") {
        return "Kennis leren is al bezig";
      }
      if (ds?.sourceMissing || ds?.brain?.sourceMissing) {
        return "Bronbestand ontbreekt op schijf";
      }
    }
    return null;
  }

  async function trackJob(job: DatasetJob, okMsg?: string) {
    setPreferredJobId(job.jobId);
    await loadJobs();
    if (okMsg) toast(okMsg);
  }

  async function onUploadFile(file: File | null) {
    if (!file) return;
    const suffix = fileSuffix(file.name);
    if (!DM_UPLOAD_SUFFIXES.has(suffix)) {
      toast(
        `Bestandstype niet ondersteund (${suffix || "onbekend"}). Toegestaan: ${[...DM_UPLOAD_SUFFIXES].join(", ")}`,
      );
      return;
    }
    await withBusy(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("materialize", "true");
      const res = await api.uploadDataset(form);
      await trackJob(res.job, "Upload in wachtrij");
      await loadPage({ quiet: true });
      await loadOverview({ quiet: true });
    });
  }

  async function onCreateSubmit() {
    if (!createName.trim()) {
      toast("Naam is verplicht");
      return;
    }
    await withBusy(async () => {
      const res = await api.createDataset({
        name: createName.trim(),
        description: createDesc,
        license: createLicense.trim() || null,
      });
      setModal(null);
      setCreateName("");
      setCreateDesc("");
      setCreateLicense("");
      await loadPage({ quiet: true, offset: 0, preferId: res.dataset.datasetId });
      await loadOverview({ quiet: true });
      toast("Dataset aangemaakt");
    });
  }

  async function onLocalSubmit() {
    if (!localPath.trim()) {
      toast("Lokaal pad is verplicht");
      return;
    }
    await withBusy(async () => {
      try {
        await api.inspectDatasetPath(localPath.trim());
      } catch (err) {
        toast(errMsg(err, "Padinspectie mislukt"));
        return;
      }
      const res = await api.importDatasetLocal({
        path: localPath.trim(),
        name: localName.trim() || undefined,
        description: localDesc || undefined,
        materialize: true,
      });
      setModal(null);
      setLocalPath("");
      setLocalName("");
      setLocalDesc("");
      await trackJob(res.job, "Lokale import in wachtrij");
      await loadPage({ quiet: true });
      await loadOverview({ quiet: true });
    });
  }

  async function onHfSubmit() {
    if (!hfRepo.trim()) {
      toast("Repository ID is verplicht");
      return;
    }
    await withBusy(async () => {
      const res = await api.importDatasetHuggingFace({
        repositoryId: hfRepo.trim(),
        filename: hfFilename.trim() || null,
        revision: hfRevision.trim() || "main",
        name: hfName.trim() || undefined,
        description: hfDesc || undefined,
        token: hfToken.trim() || null,
        materialize: true,
      });
      setModal(null);
      setHfRepo("");
      setHfFilename("");
      setHfName("");
      setHfDesc("");
      setHfToken("");
      setHfRevision("main");
      await trackJob(res.job, "Hugging Face import in wachtrij");
      await loadPage({ quiet: true });
      await loadOverview({ quiet: true });
    });
  }

  async function onDeleteConfirm() {
    if (!selectedId) return;
    const deletedId = selectedId;
    const remaining = datasets.filter((d) => d.datasetId !== deletedId);
    const nextId = remaining[0]?.datasetId ?? null;
    await withBusy(async () => {
      await api.deleteDataset(deletedId);
      setModal(null);
      setExportArtifact((prev) => (prev?.datasetId === deletedId ? null : prev));
      await loadPage({ quiet: true, preferId: nextId });
      await loadOverview({ quiet: true });
      toast("Dataset verwijderd");
    });
  }

  async function onRescanLibrary() {
    await withBusy(async () => {
      const res = await api.refreshDatasetLibrary();
      setDatasets(res.datasets);
      await loadOverview({ quiet: true });
      toast(
        `Scan klaar: ${res.created} nieuw, ${res.updated} bijgewerkt, ${res.discovered} bronnen`,
      );
    });
  }

  async function onLearnToBrain(opts?: { rebuild?: boolean }) {
    if (!selectedId) {
      toast("Selecteer eerst een dataset");
      return;
    }
    await withBusy(async () => {
      const res = await api.learnDataset(selectedId, {
        versionId: selectedVersionId,
        rebuild: opts?.rebuild ?? false,
        offlineOnly: true,
      });
      await trackJob(res.job, opts?.rebuild ? "Opnieuw leren in wachtrij" : "Kennis leren in wachtrij");
      await loadPage({ quiet: true });
    });
  }

  async function onDuplicate() {
    if (!selectedId) {
      toast("Selecteer eerst een dataset");
      return;
    }
    await withBusy(async () => {
      const res = await api.duplicateDataset(selectedId, { versionId: selectedVersionId });
      const targetId = res.job.datasetId;
      await trackJob(res.job, "Duplicatie in wachtrij");
      await loadPage({ quiet: true, preferId: targetId ?? undefined });
      await loadOverview({ quiet: true });
    });
  }

  async function runVersionJob(
    action: () => Promise<{ job: DatasetJob }>,
    label: string,
    opts?: { exportWatch?: boolean },
  ) {
    if (!selectedId || !selectedVersionId) {
      toast("Selecteer eerst een datasetversie");
      return;
    }
    await withBusy(async () => {
      const res = await action();
      if (opts?.exportWatch) {
        exportWatchRef.current = res.job.jobId;
      }
      await trackJob(res.job, `${label} in wachtrij gezet`);
    });
  }

  async function onDownloadExport() {
    if (!exportArtifact) {
      toast("Geen exportartifact beschikbaar");
      return;
    }
    await withBusy(async () => {
      const blob = await api.downloadDatasetExport(exportArtifact.datasetId, exportArtifact.versionId);
      triggerBlobDownload(blob, `export-${exportArtifact.versionId}.jsonl`);
      toast("Export gedownload");
    });
  }

  async function onSaveSemantic() {
    if (!selectedId) return;
    await withBusy(async () => {
      await api.patchDatasetSemantic(selectedId, {
        displayName: editDisplayName.trim() || undefined,
        primaryCategory: editCategory || undefined,
        tags: editTags.split(",").map((t) => t.trim()).filter(Boolean),
        versionId: selectedVersionId,
      });
      setSemanticEditing(false);
      setDetailEpoch((n) => n + 1);
      await loadPage({ quiet: true, preferId: selectedId });
    }, "Metagegevens opgeslagen");
  }

  async function onAnalyzeSemantic() {
    if (!selectedId) return;
    await withBusy(async () => {
      await api.analyzeDatasetSemantic(selectedId, {
        versionId: selectedVersionId,
        syncArtifacts: true,
      });
      setDetailEpoch((n) => n + 1);
      await loadPage({ quiet: true, preferId: selectedId });
    }, "Semantische analyse voltooid");
  }

  async function onSidebarAction(actionId: string) {
    const reason = actionDisabledReason(actionId);
    if (reason) {
      toast(reason);
      return;
    }
    switch (actionId) {
      case "upload":
        uploadRef.current?.click();
        return;
      case "create":
        setModal("create");
        return;
      case "local":
        setModal("local");
        return;
      case "hf":
        setModal("hf");
        return;
      case "rescan":
        await onRescanLibrary();
        return;
      case "delete":
        setModal("delete");
        return;
      case "learn":
        await onLearnToBrain();
        return;
      case "dup":
        await onDuplicate();
        return;
      case "validate":
        await runVersionJob(
          () => api.validateDatasetVersion(selectedId!, selectedVersionId!),
          "Validatie",
        );
        return;
      case "export":
        await runVersionJob(
          () => api.exportDatasetVersion(selectedId!, selectedVersionId!),
          "Export",
          { exportWatch: true },
        );
        return;
      case "index":
        await onLearnToBrain({ rebuild: true });
        return;
      default:
        return;
    }
  }

  async function onFooterAction(id: string) {
    if (id === "import") {
      uploadRef.current?.click();
      return;
    }
    if (id === "validate") return onSidebarAction("validate");
    if (id === "delete") return onSidebarAction("delete");
    if (id === "learn") return onSidebarAction("learn");
    if (id === "rescan") return onSidebarAction("rescan");
    if (id === "save") {
      await onSaveSemantic();
    }
  }

  async function onCancelDatasetJob(jobId: string) {
    await withBusy(async () => {
      await api.cancelDatasetJob(jobId);
      await loadJobs();
    }, "Annuleren aangevraagd");
  }

  function goToPage(nextOffset: number) {
    void loadPage({ offset: Math.max(0, nextOffset) });
  }

  return {
    uploadRef,
    loading,
    error,
    busy,
    datasets,
    filtered,
    total,
    offset,
    hasMore,
    pageSize: DM_PAGE_SIZE,
    goToPage,
    overview,
    overviewLoading,
    overviewError,
    selectedId,
    setSelectedId,
    detail,
    versions,
    selectedVersion,
    selectedVersionId,
    setSelectedVersionId,
    detailError,
    preview,
    previewError,
    samplePreview,
    sampleTab,
    setSampleTab,
    queryInput,
    setQueryInput,
    typeFilter,
    setTypeFilter,
    sourceFilter,
    setSourceFilter,
    categoryFilter,
    setCategoryFilter,
    splitFilter,
    setSplitFilter,
    statusFilter,
    setStatusFilter,
    recovery,
    editDisplayName,
    setEditDisplayName,
    editCategory,
    setEditCategory,
    editTags,
    setEditTags,
    semanticEditing,
    setSemanticEditing,
    modal,
    setModal,
    createName,
    setCreateName,
    createDesc,
    setCreateDesc,
    createLicense,
    setCreateLicense,
    localPath,
    setLocalPath,
    localName,
    setLocalName,
    localDesc,
    setLocalDesc,
    hfRepo,
    setHfRepo,
    hfRevision,
    setHfRevision,
    hfFilename,
    setHfFilename,
    hfName,
    setHfName,
    hfDesc,
    setHfDesc,
    hfToken,
    setHfToken,
    exportArtifact,
    selected,
    activeJobs,
    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    clearActivityView,
    live,
    actionDisabledReason,
    onUploadFile,
    onCreateSubmit,
    onLocalSubmit,
    onHfSubmit,
    onDeleteConfirm,
    onRescanLibrary,
    onLearnToBrain,
    onDuplicate,
    onDownloadExport,
    onSaveSemantic,
    onAnalyzeSemantic,
    onSidebarAction,
    onFooterAction,
    onCancelDatasetJob,
    loadPage,
    loadOverview,
  };
}

export type DatasetManagementWorkspace = ReturnType<typeof useDatasetManagementWorkspace>;
