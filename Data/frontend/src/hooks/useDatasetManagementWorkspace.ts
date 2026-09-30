/**
 * Dataset Management V2 workspace — `/dataset-management`.
 * Real APIs + optional Screen 1 visual fixture gate (Playwright only).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import {
  DATASET_MGMT_V2_VISUAL_FIXTURE,
  isDatasetManagementVisualFixtureActive,
} from "../mocks/datasetManagementV2VisualFixture";
import {
  DM_CATEGORY_FILTERS,
  DM_LIBRARY_PAGE_SIZE,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
  UPLOAD_SUFFIXES,
  sourceFilterToQuery,
  statusFilterToQuery,
  typeFilterToQuery,
  type DatasetSampleTab,
} from "../pages/datasets/datasetManagementConstants";
import {
  categoryForDataset,
  displayNameForDataset,
  fileSuffix,
  formatBytes,
  formatCompactCount,
  pickUsableVersion,
  previewSampleText,
  tagsForDataset,
  triggerBlobDownload,
} from "../pages/datasets/datasetManagementFormat";
import { isActiveJob, isCompletedJob } from "../pages/datasets/datasetActivity";
import { useDatasetActivity } from "../pages/datasets/useDatasetActivity";
import { useAppToast } from "../state/useAppToast";
import type {
  DatasetJob,
  DatasetOverview,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetRecoveryAssessment,
  DatasetVersion,
} from "../types/api";

export type DatasetMgmtModalKind = "create" | "local" | "hf" | "delete" | null;

export type DatasetServiceStatus = {
  id: string;
  label: string;
  state: "Ready" | "Running" | "Degraded" | "Offline" | "UNMEASURED";
  tone: "success" | "warning" | "danger" | "muted";
  detail?: string;
};

export type DatasetKpiCard = {
  id: string;
  label: string;
  value: string;
  hint?: string;
  delta?: string;
  tone: "cyan" | "gold" | "green" | "red";
  progress?: number;
  sparkline?: number[];
};

const SEARCH_DEBOUNCE_MS = 280;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function relativeSyncHint(iso: string | null | undefined): string {
  if (!iso) return "Laatste sync onbekend";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "Laatste sync onbekend";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60_000));
  if (mins < 1) return "Laatste sync zojuist";
  if (mins < 60) return `Laatste sync ${mins} min geleden`;
  const hrs = Math.round(mins / 60);
  return `Laatste sync ${hrs}u geleden`;
}

export function useDatasetManagementWorkspace() {
  const toast = useAppToast();
  const uploadRef = useRef<HTMLInputElement>(null);
  const searchTimer = useRef<number | null>(null);
  const exportWatchRef = useRef<string | null>(null);
  const prevExportJobsRef = useRef<Map<string, DatasetJob>>(new Map());
  const libraryReqGen = useRef(0);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [overview, setOverview] = useState<DatasetOverview | null>(null);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [libraryTotal, setLibraryTotal] = useState(0);
  const [libraryHasMore, setLibraryHasMore] = useState(false);
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [libraryLoading, setLibraryLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DatasetRecord | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailEpoch, setDetailEpoch] = useState(0);

  const [preview, setPreview] = useState<DatasetPreviewRow[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sampleTab, setSampleTab] = useState<DatasetSampleTab>("JSON");

  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState(DM_TYPE_FILTERS[0]);
  const [sourceFilter, setSourceFilter] = useState(DM_SOURCE_FILTERS[0]);
  const [categoryFilter, setCategoryFilter] = useState(DM_CATEGORY_FILTERS[0]);
  const [splitFilter, setSplitFilter] = useState(DM_SPLIT_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(DM_STATUS_FILTERS[0]);
  const [sort, setSort] = useState("newest");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [recovery, setRecovery] = useState<DatasetRecoveryAssessment | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editTags, setEditTags] = useState("");
  const [semanticEditing, setSemanticEditing] = useState(false);

  const [modal, setModal] = useState<DatasetMgmtModalKind>(null);
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

  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [catalogOk, setCatalogOk] = useState<boolean | null>(null);

  // Debounce library search
  useEffect(() => {
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => {
      setDebouncedQuery(query);
      setLibraryOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current);
    };
  }, [query]);

  const loadOverview = useCallback(async () => {
    if (isDatasetManagementVisualFixtureActive()) {
      setOverview(DATASET_MGMT_V2_VISUAL_FIXTURE.overview as unknown as DatasetOverview);
      setCatalogOk(DATASET_MGMT_V2_VISUAL_FIXTURE.overview.catalogStatus.state === "HEALTHY");
      setHealthOk(true);
      const artifact = (
        DATASET_MGMT_V2_VISUAL_FIXTURE as {
          exportArtifact?: { datasetId: string; versionId: string; jobId: string };
        }
      ).exportArtifact;
      if (artifact) setExportArtifact(artifact);
      return;
    }
    try {
      const [ov, health] = await Promise.all([
        api.getDatasetsOverview(),
        api.health().catch(() => null),
      ]);
      setOverview(ov.overview);
      setCatalogOk(ov.overview.catalogStatus?.state === "HEALTHY");
      setHealthOk(health?.ok ?? null);
    } catch (err) {
      setOverview(null);
      setCatalogOk(null);
      throw err;
    }
  }, []);

  const loadLibrary = useCallback(
    async (opts?: { quiet?: boolean; preferId?: string | null; offset?: number }) => {
      const offset = opts?.offset ?? libraryOffset;
      const gen = ++libraryReqGen.current;
      if (!opts?.quiet) setLibraryLoading(true);
      try {
        if (isDatasetManagementVisualFixtureActive()) {
          const fixture = DATASET_MGMT_V2_VISUAL_FIXTURE;
          let rows = fixture.datasets as DatasetRecord[];
          const q = debouncedQuery.trim().toLowerCase();
          if (q) {
            rows = rows.filter((d) => {
              const name = displayNameForDataset(d).toLowerCase();
              const tags = tagsForDataset(d).join(" ").toLowerCase();
              return (
                name.includes(q) ||
                d.name.toLowerCase().includes(q) ||
                tags.includes(q) ||
                (d.description || "").toLowerCase().includes(q)
              );
            });
          }
          if (gen !== libraryReqGen.current) return;
          setDatasets(rows);
          setLibraryTotal(fixture.overview.totalDatasets);
          setLibraryHasMore(false);
          setSelectedId((prev) => {
            if (opts?.preferId && rows.some((d) => d.datasetId === opts.preferId)) return opts.preferId;
            if (rows.length === 0) return null;
            if (prev && rows.some((d) => d.datasetId === prev)) return prev;
            return fixture.selectedDatasetId ?? rows[0].datasetId;
          });
          return;
        }

        const res = await api.listDatasets({
          q: debouncedQuery.trim() || undefined,
          limit: DM_LIBRARY_PAGE_SIZE,
          offset,
          status: statusFilterToQuery(statusFilter),
          source: sourceFilterToQuery(sourceFilter),
          category: categoryFilter === "Alle categorieën" ? undefined : categoryFilter,
          split: splitFilter === "Alle splits" ? undefined : splitFilter,
          type: typeFilterToQuery(typeFilter),
          tag: tagFilter || undefined,
          sort,
          includeBrain: true,
          includeQuality: true,
        });
        if (gen !== libraryReqGen.current) return;
        setDatasets((prev) =>
          offset > 0 ? [...prev, ...res.datasets.filter((d) => !prev.some((p) => p.datasetId === d.datasetId))] : res.datasets,
        );
        setLibraryTotal(res.total ?? res.datasets.length);
        setLibraryHasMore(Boolean(res.hasMore));
        setLibraryOffset(res.offset ?? offset);
        if (offset === 0) {
          setSelectedId((prev) => {
            if (opts?.preferId && res.datasets.some((d) => d.datasetId === opts.preferId)) {
              return opts.preferId;
            }
            if (res.datasets.length === 0) return null;
            if (prev && res.datasets.some((d) => d.datasetId === prev)) return prev;
            return res.datasets[0].datasetId;
          });
        }
        if (opts?.quiet) setError(null);
      } catch (err) {
        if (gen !== libraryReqGen.current) return;
        setError(errMsg(err, "Datasets laden mislukt"));
        if (!opts?.quiet) setDatasets([]);
      } finally {
        if (gen === libraryReqGen.current) setLibraryLoading(false);
      }
    },
    [
      libraryOffset,
      debouncedQuery,
      statusFilter,
      sourceFilter,
      categoryFilter,
      splitFilter,
      typeFilter,
      sort,
      tagFilter,
    ],
  );

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
      void loadLibrary({ quiet: true });
      void loadOverview().catch(() => undefined);
      setDetailEpoch((n) => n + 1);
    },
  });

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      await Promise.all([loadOverview(), loadLibrary({ quiet: true }), loadJobs()]);
    } catch (err) {
      setError(errMsg(err, "Vernieuwen mislukt"));
    } finally {
      setRefreshing(false);
    }
  }, [loadOverview, loadLibrary, loadJobs]);

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await Promise.all([loadOverview(), loadLibrary({ quiet: false, offset: 0 })]);
      } catch (err) {
        if (!cancelled) setError(errMsg(err, "Datasets laden mislukt"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
  }, []);

  // Re-query library when filters / debounced search change
  useEffect(() => {
    if (loading) return;
    void loadLibrary({ quiet: true, offset: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery, typeFilter, sourceFilter, categoryFilter, splitFilter, statusFilter, sort, tagFilter]);

  const selected = datasets.find((d) => d.datasetId === selectedId) ?? detail;
  const selectedVersion =
    versions.find((v) => v.versionId === selectedVersionId) ?? pickUsableVersion(versions);

  // Export job → download artifact
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

  // Detail + recovery
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
    if (isDatasetManagementVisualFixtureActive()) {
      const fixture = DATASET_MGMT_V2_VISUAL_FIXTURE;
      const ds =
        (fixture.datasets as DatasetRecord[]).find((d) => d.datasetId === selectedId) ??
        (fixture.detail as DatasetRecord);
      const vers = (fixture.versions[selectedId] ?? fixture.versions[fixture.selectedDatasetId] ?? []) as DatasetVersion[];
      setDetail(ds);
      setVersions(vers);
      setSelectedVersionId(pickUsableVersion(vers)?.versionId ?? null);
      setRecovery((fixture.recovery[selectedId] as DatasetRecoveryAssessment) ?? null);
      setEditDisplayName(displayNameForDataset(ds));
      setEditCategory(categoryForDataset(ds));
      setEditTags(tagsForDataset(ds).join(", "));
      setSemanticEditing(false);
      setDetailError(null);
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

  // Preview
  useEffect(() => {
    if (!selectedVersionId) {
      setPreview([]);
      setPreviewError(null);
      return;
    }
    if (isDatasetManagementVisualFixtureActive()) {
      const rows = (DATASET_MGMT_V2_VISUAL_FIXTURE.preview[selectedVersionId] ??
        DATASET_MGMT_V2_VISUAL_FIXTURE.previewDefault) as DatasetPreviewRow[];
      setPreview(rows);
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

  const activeJobs = useMemo(() => jobs.filter(isActiveJob), [jobs]);

  const exportDownloadCount = useMemo(() => {
    if (isDatasetManagementVisualFixtureActive()) {
      return (
        DATASET_MGMT_V2_VISUAL_FIXTURE.jobs.filter(
          (j) => j.jobType === "export" && j.status === "completed",
        ).length || (exportArtifact ? 1 : 0)
      );
    }
    return jobs.filter((j) => j.jobType === "export" && isCompletedJob(j)).length || (exportArtifact ? 1 : 0);
  }, [jobs, exportArtifact]);

  const tagCloud = useMemo(() => {
    if (overview?.tagCounts && Object.keys(overview.tagCounts).length) {
      return Object.entries(overview.tagCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12)
        .map(([tag, count]) => ({ tag, count }));
    }
    const counts = new Map<string, number>();
    for (const ds of datasets) {
      for (const tag of tagsForDataset(ds)) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([tag, count]) => ({ tag, count }));
  }, [overview, datasets]);

  const kpis = useMemo((): DatasetKpiCard[] => {
    const ov = overview;
    const loadingValue = loading && !ov;
    const catalog = ov?.catalogStatus;
    const catalogLabel =
      catalog?.label ||
      (catalog?.state === "HEALTHY"
        ? "Gezond"
        : catalog?.state
          ? String(catalog.state)
          : error || healthOk === false
            ? "Offline"
            : "—");
    return [
      {
        id: "datasets",
        label: "Totaal Datasets",
        value: loadingValue ? "…" : String(ov?.totalDatasets ?? libraryTotal),
        hint: ov ? undefined : error ? "Laden mislukt" : undefined,
        tone: "cyan",
      },
      {
        id: "samples",
        label: "Totaal Samples",
        value: loadingValue ? "…" : formatCompactCount(ov?.totalSamples),
        hint:
          ov?.samplesMeasurementStatus === "PARTIAL"
            ? `Gedeeltelijk gemeten (${ov.samplesUnmeasuredDatasets} ontbreken)`
            : ov?.samplesMeasurementStatus === "UNMEASURED"
              ? "Nog niet gemeten"
              : ov
                ? `${(ov.totalSamples ?? 0).toLocaleString()} rijen`
                : undefined,
        tone: "cyan",
      },
      {
        id: "storage",
        label: "Opslag Gebruikt",
        value: loadingValue ? "…" : formatBytes(ov?.storage.usedBytes ?? ov?.totalKnownBytes),
        hint:
          ov?.storage.capacityBytes != null
            ? `van ${formatBytes(ov.storage.capacityBytes)}`
            : ov
              ? "capaciteit ongemeten"
              : undefined,
        progress: ov?.storage.usedPercent ?? undefined,
        tone: "gold",
      },
      {
        id: "imports",
        label: "Actieve Imports",
        value: loadingValue ? "…" : ov ? String(ov.activeImports) : "—",
        hint: jobsError
          ? jobsError
          : ov
            ? `${ov.activeImportsRunning} bezig · ${ov.activeImportsQueued} in wachtrij`
            : "Geen overview",
        tone: "cyan",
      },
      {
        id: "validation",
        label: "Validatie Issues",
        value: loadingValue ? "…" : ov ? String(ov.validationIssues) : "—",
        hint: ov
          ? `${ov.criticalValidationIssues} kritiek · ${ov.validationWarnings} waarschuwingen`
          : "Geen overview",
        tone: "red",
      },
      {
        id: "sync",
        label: "Catalog Status",
        value: loadingValue ? "…" : catalogLabel,
        hint: relativeSyncHint(catalog?.lastReconcileAt),
        tone:
          error || healthOk === false
            ? "red"
            : catalog?.state === "HEALTHY"
              ? "green"
              : catalogOk === false
                ? "gold"
                : "cyan",
      },
    ];
  }, [overview, loading, libraryTotal, error, jobsError, healthOk, catalogOk]);

  const datasetServices = useMemo((): DatasetServiceStatus[] => {
    const catalogState = overview?.catalogStatus?.state;
    const catalogReady = catalogState === "HEALTHY";
    const online = !error && healthOk !== false;
    const indexingBusy = activeJobs.some(
      (j) =>
        isActiveJob(j) &&
        (j.jobType === "index" || String(j.config?.learnToBrain ?? "") === "true"),
    );
    const validationBusy = activeJobs.some((j) => isActiveJob(j) && j.jobType === "validate");
    const semanticBusy = activeJobs.some(
      (j) => isActiveJob(j) && (j.jobType === "enrich_metadata" || j.jobType.includes("semantic")),
    );
    return [
      {
        id: "embedding",
        label: "Embedding Pipeline",
        state: online ? (indexingBusy ? "Running" : "Ready") : error ? "Offline" : "UNMEASURED",
        tone: online ? (indexingBusy ? "success" : "success") : error ? "danger" : "muted",
        detail: "via Knowledge embedding provider",
      },
      {
        id: "indexing",
        label: "Indexing Service",
        state: indexingBusy ? "Running" : online ? "Ready" : "Offline",
        tone: indexingBusy || online ? "success" : "danger",
        detail: "Dataset → Brain/Knowledge index jobs",
      },
      {
        id: "validation",
        label: "Validation Engine",
        state: validationBusy ? "Running" : online ? "Ready" : "Offline",
        tone: validationBusy || online ? "success" : "danger",
        detail: "dataset worker / validate capability",
      },
      {
        id: "semantic",
        label: "Semantic Enrichment",
        state: semanticBusy ? "Running" : online ? "Ready" : "Offline",
        tone: semanticBusy || online ? "success" : "danger",
        detail: "semantic profile analyze / enrich jobs",
      },
      {
        id: "training",
        label: "Training Connector",
        state: online ? "Ready" : "Offline",
        tone: online ? "success" : "danger",
        detail: "immutable datasetVersionId towards /training",
      },
      {
        id: "brain-sync",
        label: "Brain Sync",
        state: catalogReady ? (indexingBusy ? "Running" : "Ready") : catalogState ? "Degraded" : "UNMEASURED",
        tone: catalogReady ? "success" : catalogState ? "warning" : "muted",
        detail: overview?.catalogStatus?.label,
      },
    ];
  }, [overview, error, healthOk, activeJobs]);

  const samplePreview = useMemo(() => {
    if (previewError) return previewError;
    if (preview.length === 0) {
      return selectedVersion
        ? "Geen voorbeeldrijen voor deze versie."
        : "Selecteer een dataset met versie.";
    }
    if (sampleTab === "JSON") return JSON.stringify(preview, null, 2);
    if (sampleTab === "Tekst") return previewSampleText(preview);
    const cols = new Set<string>();
    for (const row of preview.slice(0, 5)) {
      Object.keys(row as object).forEach((k) => cols.add(k));
    }
    const headers = [...cols].slice(0, 6);
    const lines = [headers.join(" | ")];
    for (const row of preview.slice(0, 8)) {
      const r = row as Record<string, unknown>;
      lines.push(
        headers
          .map((h) => {
            const v = r[h];
            return v == null ? "—" : typeof v === "string" || typeof v === "number" ? String(v) : String(v);
          })
          .join(" | "),
      );
    }
    return lines.join("\n");
  }, [preview, previewError, sampleTab, selectedVersion]);

  const trainingDeepLink = useMemo(() => {
    const params = new URLSearchParams();
    if (selectedId) params.set("datasetId", selectedId);
    if (selectedVersionId) params.set("datasetVersionId", selectedVersionId);
    const qs = params.toString();
    return qs ? `/training?${qs}` : "/training";
  }, [selectedId, selectedVersionId]);

  function actionDisabledReason(actionId: string): string | null {
    if (actionId === "advanced") return null;
    const needsSelection = [
      "delete",
      "learn",
      "dup",
      "index",
      "validate",
      "export",
      "save",
      "dedupe",
      "split",
      "tokenize",
      "contamination",
      "pii",
      "materialize",
      "train",
    ];
    const needsVersion = [
      "index",
      "validate",
      "export",
      "dedupe",
      "split",
      "tokenize",
      "contamination",
      "pii",
      "train",
    ];
    if (needsSelection.includes(actionId) && !selectedId) return "Selecteer eerst een dataset";
    if (needsVersion.includes(actionId) && !selectedVersionId) return "Selecteer eerst een datasetversie";
    if (actionId === "learn" && selectedId) {
      const row = datasets.find((d) => d.datasetId === selectedId) ?? detail;
      const brain = row?.brainStatus ?? row?.brain?.brainStatus;
      if (brain === "learned") {
        return "Al geleerd — gebruik Index opnieuw opbouwen om opnieuw te leren";
      }
      if (brain === "indexing" || brain === "queued") return "Kennis leren is al bezig";
      if (row?.sourceMissing || row?.brain?.sourceMissing) return "Bronbestand ontbreekt op schijf";
    }
    if (actionId === "train") {
      if (recovery?.recoveryState === "HASH_MISMATCH" || recovery?.recoveryState === "CONFLICT") {
        return `Recovery blokkeert training (${recovery.recoveryState})`;
      }
      if (recovery?.recoveryState === "SOURCE_MISSING" || selected?.sourceMissing) {
        return "Bron ontbreekt — niet trainbaar";
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
    if (!UPLOAD_SUFFIXES.has(suffix)) {
      toast(
        `Bestandstype niet ondersteund (${suffix || "onbekend"}). Toegestaan: ${[...UPLOAD_SUFFIXES].join(", ")}`,
      );
      return;
    }
    await withBusy(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("materialize", "true");
      const res = await api.uploadDataset(form);
      await trackJob(res.job, "Upload in wachtrij");
      await loadLibrary({ quiet: true });
      await loadOverview().catch(() => undefined);
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
      await loadLibrary({ quiet: true, preferId: res.dataset.datasetId });
      await loadOverview().catch(() => undefined);
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
      await loadLibrary({ quiet: true });
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
      await loadLibrary({ quiet: true });
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
      await loadLibrary({ quiet: true, preferId: nextId });
      await loadOverview().catch(() => undefined);
      toast("Dataset verwijderd");
    });
  }

  async function onRescanLibrary() {
    await withBusy(async () => {
      const res = await api.refreshDatasetLibrary();
      toast(
        `Scan klaar: ${res.created} nieuw, ${res.updated} bijgewerkt, ${res.discovered} bronnen`,
      );
      // Re-query catalog + overview — never treat scan page length as KPI truth.
      await Promise.all([
        loadLibrary({ quiet: true, offset: 0 }),
        loadOverview().catch(() => undefined),
      ]);
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
      await loadLibrary({ quiet: true });
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
      await loadLibrary({ quiet: true, preferId: targetId ?? undefined });
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
      if (opts?.exportWatch) exportWatchRef.current = res.job.jobId;
      await trackJob(res.job, `${label} in wachtrij gezet`);
    });
  }

  async function onDownloadExport() {
    if (!exportArtifact) {
      toast("Geen exportartifact beschikbaar");
      return;
    }
    await withBusy(async () => {
      const blob = await api.downloadDatasetExport(
        exportArtifact.datasetId,
        exportArtifact.versionId,
      );
      triggerBlobDownload(blob, `export-${exportArtifact.versionId}.jsonl`);
      toast("Export gedownload");
    });
  }

  async function onSaveMetadata() {
    if (!selectedId) {
      toast("Selecteer eerst een dataset");
      return;
    }
    await withBusy(async () => {
      await api.patchDatasetSemantic(selectedId, {
        displayName: editDisplayName.trim() || undefined,
        primaryCategory: editCategory || undefined,
        tags: editTags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        versionId: selectedVersionId,
      });
      setSemanticEditing(false);
      setDetailEpoch((n) => n + 1);
      await loadLibrary({ quiet: true, preferId: selectedId });
    }, "Metagegevens opgeslagen");
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
      case "advanced":
        setShowAdvanced((v) => !v);
        return;
      case "dedupe":
        await runVersionJob(
          () => api.dedupeDatasetVersion(selectedId!, selectedVersionId!),
          "Deduplicatie",
        );
        return;
      case "split":
        await runVersionJob(
          () => api.splitDatasetVersion(selectedId!, selectedVersionId!),
          "Split",
        );
        return;
      case "tokenize":
        await runVersionJob(
          () => api.tokenizeStatsDatasetVersion(selectedId!, selectedVersionId!),
          "Token-statistieken",
        );
        return;
      case "contamination":
        await runVersionJob(
          () => api.contaminationScanDatasetVersion(selectedId!, selectedVersionId!),
          "Contamination scan",
        );
        return;
      case "pii":
        await withBusy(async () => {
          const res = await api.scanDatasetPii(selectedVersionId!);
          const findings = Number(
            (res.pii as { findingCount?: number; count?: number } | undefined)?.findingCount ??
              (res.pii as { count?: number } | undefined)?.count ??
              0,
          );
          toast(
            findings > 0
              ? `PII scan: ${findings} bevinding(en) (details beperkt)`
              : "PII scan: geen bevindingen in sample",
          );
        });
        return;
      case "materialize":
        await withBusy(async () => {
          const res = await api.materializeDataset(selectedId!);
          await trackJob(res.job, "Materialisatie in wachtrij");
        });
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
    if (id === "validate") {
      await onSidebarAction("validate");
      return;
    }
    if (id === "delete") {
      await onSidebarAction("delete");
      return;
    }
    if (id === "learn") {
      await onSidebarAction("learn");
      return;
    }
    if (id === "rescan") {
      await onSidebarAction("rescan");
      return;
    }
    if (id === "save") {
      // Ensure edit fields are populated even if user didn't open the editor.
      if (!semanticEditing && selected) {
        setEditDisplayName(displayNameForDataset(selected));
        setEditCategory(categoryForDataset(selected));
        setEditTags(tagsForDataset(selected).join(", "));
      }
      await onSaveMetadata();
    }
  }

  async function onCancelDatasetJob(jobId: string) {
    await withBusy(async () => {
      await api.cancelDatasetJob(jobId);
      await loadJobs();
    }, "Annuleren aangevraagd");
  }

  async function onAnalyzeSemantic() {
    if (!selectedId) return;
    await withBusy(async () => {
      await api.analyzeDatasetSemantic(selectedId, {
        versionId: selectedVersionId,
        syncArtifacts: true,
      });
      setDetailEpoch((n) => n + 1);
      await loadLibrary({ quiet: true, preferId: selectedId });
    }, "Semantische analyse voltooid");
  }

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    return datasetServices.slice(0, 5).map((s) => ({
      id: s.id,
      label: s.label,
      value: s.state,
      tone: s.tone === "success" ? "success" : s.tone === "warning" ? "warning" : s.tone === "danger" ? "danger" : "muted",
    }));
  }, [datasetServices]);

  const online: boolean | null = error ? false : healthOk === false ? false : overview ? true : null;

  function loadMore() {
    if (!libraryHasMore || libraryLoading) return;
    const next = libraryOffset + DM_LIBRARY_PAGE_SIZE;
    setLibraryOffset(next);
    void loadLibrary({ quiet: true, offset: next });
  }

  return {
    loading,
    refreshing,
    libraryLoading,
    error,
    busy,
    online,
    sidebarStatus,
    refresh,
    uploadRef,

    overview,
    datasets,
    libraryTotal,
    libraryHasMore,
    loadMore,
    kpis,
    datasetServices,
    tagCloud,

    selectedId,
    setSelectedId,
    selected,
    detail,
    detailError,
    versions,
    selectedVersionId,
    setSelectedVersionId,
    selectedVersion,
    recovery,

    preview,
    previewError,
    sampleTab,
    setSampleTab,
    samplePreview,

    query,
    setQuery,
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
    sort,
    setSort,
    tagFilter,
    setTagFilter,
    showAdvanced,
    setShowAdvanced,

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
    exportDownloadCount,
    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    live,
    clearActivityView,

    trainingDeepLink,
    actionDisabledReason,
    onSidebarAction,
    onFooterAction,
    onUploadFile,
    onCreateSubmit,
    onLocalSubmit,
    onHfSubmit,
    onDeleteConfirm,
    onDownloadExport,
    onSaveMetadata,
    onAnalyzeSemantic,
    onCancelDatasetJob,
    withBusy,
  };
}

export type DatasetManagementWorkspace = ReturnType<typeof useDatasetManagementWorkspace>;
