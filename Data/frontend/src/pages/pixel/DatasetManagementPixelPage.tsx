import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import {
  DM_FOOTER_ACTIONS,
  DM_PAGE_COPY,
  DM_SAMPLE_TABS,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
  type DatasetMgmtStatus,
  type DatasetSampleTab,
} from "../../mocks/dataset-management";
import { useAppToast } from "../../state/useAppToast";
import type { DatasetJob, DatasetPreviewRow, DatasetRecord, DatasetVersion } from "../../types/api";
import { DatasetActivityConsole } from "../datasets/DatasetActivityConsole";
import { isActiveJob, isCompletedJob } from "../datasets/datasetActivity";
import { useDatasetActivity } from "../datasets/useDatasetActivity";
import { PxHero, PxIcon, PxKpi } from "./pixel-shared";

const UPLOAD_ACCEPT =
  ".jsonl,.ndjson,.json,.csv,.tsv,.txt,.md,.markdown,.parquet";
const UPLOAD_SUFFIXES = new Set([
  ".jsonl",
  ".ndjson",
  ".json",
  ".csv",
  ".tsv",
  ".txt",
  ".md",
  ".markdown",
  ".parquet",
]);

type ModalKind = "create" | "local" | "hf" | "delete" | null;

type SidebarAction = {
  id: string;
  label: string;
  icon: string;
  danger?: boolean;
};

const SIDEBAR_ACTIONS: SidebarAction[] = [
  { id: "upload", label: "Dataset toevoegen", icon: "plus" },
  { id: "hf", label: "Importeren (Hugging Face)", icon: "download" },
  { id: "local", label: "Lokale bestanden importeren", icon: "upload" },
  { id: "create", label: "Nieuwe dataset aanmaken", icon: "squareplus" },
  { id: "rescan", label: "Opnieuw scannen", icon: "refresh" },
  { id: "delete", label: "Geselecteerde verwijderen", icon: "trash", danger: true },
  { id: "learn", label: "Kennis leren", icon: "database" },
  { id: "dup", label: "Dupliceren", icon: "copy" },
  { id: "index", label: "Index opnieuw opbouwen", icon: "refresh" },
  { id: "validate", label: "Valideren", icon: "checkcircle" },
  { id: "export", label: "Exporteren", icon: "download" },
];

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatCompactCount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function mapDatasetStatus(
  status: string,
  brainStatus?: string | null,
  canonicalState?: string | null,
): DatasetMgmtStatus {
  const canonical = (canonicalState || "").toUpperCase();
  if (canonical === "LEARNED" || canonical === "STALE_JOB") return "Klaar";
  if (canonical === "REBUILDING" || canonical === "INDEXING") return "Bezig";
  if (canonical === "INDEX_QUEUED") return "Wachtrij";
  if (canonical === "FAILED") return "Fout";
  const brain = (brainStatus || "").toLowerCase();
  if (brain === "learned") return "Klaar";
  if (brain === "indexing" || brain === "queued") return brain === "queued" ? "Wachtrij" : "Bezig";
  if (brain === "failed") return "Fout";
  const s = status.toLowerCase();
  if (s === "ready" || s === "complete" || s === "completed") return "Verwerkt";
  if (s === "processed" || s === "materialized" || s === "raw") return "Verwerkt";
  if (s === "running" || s === "processing" || s === "importing") return "Bezig";
  if (s === "queued" || s === "pending") return "Wachtrij";
  if (s === "warning" || s === "degraded") return "Waarschuwing";
  if (s === "failed" || s === "error" || s === "cancelled") return "Fout";
  return "Verwerkt";
}

function toneForStatus(status: DatasetMgmtStatus) {
  if (status === "Klaar") return "green";
  if (status === "Verwerkt" || status === "Bezig") return "cyan";
  if (status === "Wachtrij") return "gold";
  if (status === "Waarschuwing") return "orange";
  return "red";
}

function mapSourceLabel(sourceType: string): string {
  const s = sourceType.toLowerCase();
  if (s.includes("hugging") || s === "hf") return "Hugging Face";
  if (s.includes("local") || s === "path") return "Lokaal";
  if (s.includes("upload") || s === "file") return "Lokaal";
  if (s.includes("derived")) return "Afgeleid";
  if (s.includes("synthetic")) return "Synthetic";
  if (s.includes("open")) return "Open Data";
  return sourceType || "—";
}

function sourceMatchesFilter(sourceType: string, filter: string): boolean {
  if (filter === "Alle bronnen") return true;
  return mapSourceLabel(sourceType) === filter;
}

function mapTypeLabel(ds: DatasetRecord): string {
  const fmt = (ds.detectedFormat ?? "").toLowerCase();
  if (fmt.includes("pdf")) return "PDF";
  if (fmt.includes("log")) return "Logs";
  if (fmt.includes("chat") || fmt.includes("dialog")) return "Chat";
  if (fmt.includes("code") || fmt.includes("py") || fmt.includes("js")) return "Code";
  if (fmt) return "Tekst";
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const task = String(meta?.taskType ?? meta?.task ?? "").toLowerCase();
  if (task.includes("chat")) return "Chat";
  if (task.includes("code")) return "Code";
  return "Tekst";
}

function typeToneForLabel(type: string): "cyan" | "gold" | "green" | "purple" | "blue" {
  if (type === "Code") return "gold";
  if (type === "Chat") return "purple";
  if (type === "PDF") return "blue";
  if (type === "Logs") return "green";
  return "cyan";
}

function tagsForDataset(ds: DatasetRecord): string[] {
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const raw = meta?.tags;
  if (Array.isArray(raw)) return raw.map((t) => String(t)).filter(Boolean).slice(0, 6);
  const lang = meta?.language ?? meta?.lang;
  if (typeof lang === "string" && lang) return [lang];
  return [];
}

function splitLabelFromVersion(v: DatasetVersion | null): string {
  if (!v?.split || typeof v.split !== "object") return "—";
  const keys = Object.keys(v.split);
  if (keys.length === 0) return "—";
  return keys[0];
}

function previewSampleText(rows: DatasetPreviewRow[]): string {
  if (rows.length === 0) return "Geen voorbeeldrijen.";
  const first = rows[0] as Record<string, unknown>;
  const text =
    first.text ??
    first.content ??
    first.body ??
    first.message ??
    first.prompt ??
    first.input;
  if (typeof text === "string") return text.slice(0, 2000);
  return JSON.stringify(first, null, 2).slice(0, 2000);
}

function fileSuffix(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function pickUsableVersion(versions: DatasetVersion[]): DatasetVersion | null {
  const ready = versions.filter((v) => v.status === "ready");
  const order = ["materialized", "transformed", "split", "raw", "export"];
  for (const kind of order) {
    const hit = ready.find((v) => v.kind === kind);
    if (hit) return hit;
  }
  return ready[0] ?? versions[0] ?? null;
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function DatasetManagementPixelPage() {
  const toast = useAppToast();
  const uploadRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
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
  const [typeFilter, setTypeFilter] = useState(DM_TYPE_FILTERS[0]);
  const [sourceFilter, setSourceFilter] = useState(DM_SOURCE_FILTERS[0]);
  const [splitFilter, setSplitFilter] = useState(DM_SPLIT_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(DM_STATUS_FILTERS[0]);

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

  const loadDatasets = useCallback(async (opts?: { quiet?: boolean; preferId?: string | null }) => {
    if (!opts?.quiet) {
      setLoading(true);
      setError(null);
    }
    try {
      const res = await api.listDatasets();
      setDatasets(res.datasets);
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
      void loadDatasets({ quiet: true });
      setDetailEpoch((n) => n + 1);
    },
  });

  const selected = datasets.find((d) => d.datasetId === selectedId) ?? detail;
  const selectedVersion =
    versions.find((v) => v.versionId === selectedVersionId) ??
    pickUsableVersion(versions);

  // Watch export jobs → surface download when a real EXPORT version exists.
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
          setExportArtifact({
            datasetId,
            versionId: exportVersionId,
            jobId: job.jobId,
          });
          if (exportWatchRef.current === job.jobId) {
            toast("Export klaar — download beschikbaar");
          }
        }
      }
    }
    prevExportJobsRef.current = new Map(jobs.map((j) => [j.jobId, j]));
  }, [jobs, toast]);

  useEffect(() => {
    void loadDatasets();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setVersions([]);
      setSelectedVersionId(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailError(null);
      try {
        const res = await api.getDataset(selectedId);
        if (cancelled) return;
        setDetail(res.dataset);
        setVersions(res.versions);
        setSelectedVersionId((prev) => {
          if (prev && res.versions.some((v) => v.versionId === prev)) return prev;
          return pickUsableVersion(res.versions)?.versionId ?? null;
        });
      } catch (err) {
        if (!cancelled) {
          setDetail(null);
          setVersions([]);
          setSelectedVersionId(null);
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return datasets.filter((ds) => {
      const typeLabel = mapTypeLabel(ds);
      const statusNl = mapDatasetStatus(
        ds.status,
        ds.brainStatus ?? ds.brain?.brainStatus,
        ds.canonicalState ?? ds.learningState?.canonicalState ?? ds.brain?.canonicalState,
      );
      if (typeFilter !== "Alle types" && typeLabel !== typeFilter) return false;
      if (!sourceMatchesFilter(ds.sourceType, sourceFilter)) return false;
      if (statusFilter !== "Alle statussen" && statusNl !== statusFilter) return false;
      if (splitFilter !== "Alle splits") {
        const split =
          selected?.datasetId === ds.datasetId && selectedVersion
            ? splitLabelFromVersion(selectedVersion)
            : "—";
        if (split !== "—" && split !== splitFilter) return false;
        if (split === "—" && splitFilter !== "Alle splits") return false;
      }
      if (!q) return true;
      const tags = tagsForDataset(ds);
      return (
        ds.name.toLowerCase().includes(q) ||
        ds.sourceType.toLowerCase().includes(q) ||
        ds.description.toLowerCase().includes(q) ||
        tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [datasets, query, typeFilter, sourceFilter, splitFilter, statusFilter, selected, selectedVersion]);

  const totalBytes = useMemo(
    () => datasets.reduce((acc, d) => acc + (d.byteSize ?? 0), 0),
    [datasets],
  );
  const totalRows = useMemo(
    () => datasets.reduce((acc, d) => acc + (d.rowCount ?? 0), 0),
    [datasets],
  );
  const activeJobs = useMemo(() => jobs.filter(isActiveJob), [jobs]);

  const tagCloud = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ds of datasets) {
      for (const tag of tagsForDataset(ds)) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([tag, count]) => ({ tag, count }));
  }, [datasets]);

  const kpiStats = useMemo(
    () => [
      {
        id: "datasets",
        label: "Totaal Datasets",
        value: loading ? "…" : String(datasets.length),
        hint: error ? "Laden mislukt" : undefined,
        icon: "database",
        tone: "cyan" as const,
      },
      {
        id: "samples",
        label: "Totaal Samples",
        value: loading ? "…" : formatCompactCount(totalRows),
        hint: totalRows ? `${totalRows.toLocaleString()} rijen` : "Geen rijtelling",
        icon: "file",
        tone: "cyan" as const,
      },
      {
        id: "storage",
        label: "Opslag Gebruikt",
        value: loading ? "…" : formatBytes(totalBytes),
        hint: datasets.length ? `${datasets.length} datasets` : "Leeg",
        progress: undefined,
        icon: "save",
        tone: "gold" as const,
      },
      {
        id: "imports",
        label: "Actieve Imports",
        value: String(activeJobs.length),
        hint: jobsError
          ? jobsError
          : activeJobs.length
            ? `${activeJobs.filter((j) => j.status.toLowerCase() === "running").length} bezig`
            : "Geen actieve jobs",
        icon: "refresh",
        tone: "cyan" as const,
      },
      {
        id: "validation",
        label: "Validatie Issues",
        value: selectedVersion?.validation
          ? String(
              Number(
                (selectedVersion.validation as Record<string, unknown>).errorCount ??
                  (selectedVersion.validation as Record<string, unknown>).errors ??
                  "—",
              ),
            )
          : "—",
        hint: selectedVersion?.validation
          ? "Uit laatste validatie van geselecteerde versie"
          : "Geen validatieresultaat op geselecteerde versie",
        icon: "shield",
        tone: "red" as const,
      },
      {
        id: "sync",
        label: "Sync Status",
        value: error ? "Offline" : "Online",
        hint: error ?? "DatasetService bereikbaar",
        icon: "globe",
        tone: error ? ("red" as const) : ("green" as const),
      },
    ],
    [
      loading,
      datasets.length,
      totalRows,
      totalBytes,
      activeJobs,
      jobsError,
      error,
      selectedVersion,
    ],
  );

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
            return dash(
              typeof v === "string" || typeof v === "number" ? v : v == null ? null : String(v),
            );
          })
          .join(" | "),
      );
    }
    return lines.join("\n");
  }, [preview, previewError, sampleTab, selectedVersion]);

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
      const selected = datasets.find((d) => d.datasetId === selectedId);
      const brain = selected?.brainStatus ?? selected?.brain?.brainStatus;
      if (brain === "learned") {
        return "Al geleerd — gebruik Index opnieuw opbouwen om opnieuw te leren";
      }
      if (brain === "indexing" || brain === "queued") {
        return "Kennis leren is al bezig";
      }
      if (selected?.sourceMissing || selected?.brain?.sourceMissing) {
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
      await loadDatasets({ quiet: true });
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
      await loadDatasets({ quiet: true, preferId: res.dataset.datasetId });
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
      await loadDatasets({ quiet: true });
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
      await loadDatasets({ quiet: true });
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
      await loadDatasets({ quiet: true, preferId: nextId });
      toast("Dataset verwijderd");
    });
  }

  async function onRescanLibrary() {
    await withBusy(async () => {
      const res = await api.refreshDatasetLibrary();
      setDatasets(res.datasets);
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
      await loadDatasets({ quiet: true });
    });
  }

  async function onDuplicate() {
    if (!selectedId) {
      toast("Selecteer eerst een dataset");
      return;
    }
    await withBusy(async () => {
      const res = await api.duplicateDataset(selectedId, {
        versionId: selectedVersionId,
      });
      const targetId = res.job.datasetId;
      await trackJob(res.job, "Duplicatie in wachtrij");
      await loadDatasets({ quiet: true, preferId: targetId ?? undefined });
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
      const blob = await api.downloadDatasetExport(
        exportArtifact.datasetId,
        exportArtifact.versionId,
      );
      triggerBlobDownload(blob, `export-${exportArtifact.versionId}.jsonl`);
      toast("Export gedownload");
    });
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
      toast("Metagegevens opslaan is nog niet beschikbaar via de API.");
    }
  }

  async function onCancelDatasetJob(jobId: string) {
    await withBusy(async () => {
      await api.cancelDatasetJob(jobId);
      await loadJobs();
    }, "Annuleren aangevraagd");
  }

  const systemItems = [
    "DATASETS",
    formatBytes(totalBytes),
    `${activeJobs.length} IMPORTS`,
    error ? "OFFLINE" : "SYNC",
  ];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Dataset Management"
      searchPlaceholder="Zoek datasets, tags, bronnen..."
      systemItems={systemItems}
      layout="wide"
      pageClass="lv-app--pixel-datasets"
    >
      <input
        ref={uploadRef}
        type="file"
        hidden
        accept={UPLOAD_ACCEPT}
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          e.target.value = "";
          void onUploadFile(file);
        }}
      />
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero
            title={DM_PAGE_COPY.title}
            subtitle={DM_PAGE_COPY.subtitle}
            quote={DM_PAGE_COPY.quote}
            pillars={DM_PAGE_COPY.pillars}
          />

          <div className="lv-px-kpi-row is-6">
            {kpiStats.map((stat) => (
              <PxKpi
                key={stat.id}
                label={stat.label}
                value={stat.value}
                hint={stat.hint}
                hintTone={
                  stat.tone === "cyan"
                    ? "cyan"
                    : stat.tone === "gold"
                      ? "gold"
                      : stat.tone === "green"
                        ? "green"
                        : stat.tone === "red"
                          ? "red"
                          : "muted"
                }
                icon={stat.icon}
                progress={stat.progress}
              />
            ))}
          </div>

          {error ? (
            <div className="lv-px-panel" role="alert">
              <p style={{ fontSize: 11, color: "var(--lv-text-bright)" }}>Datasets niet beschikbaar</p>
              <p style={{ fontSize: 10, color: "var(--lv-text-secondary)" }}>{error}</p>
              <button
                type="button"
                className="lv-px-btn"
                style={{ marginTop: 8 }}
                disabled={busy}
                onClick={() => void loadDatasets()}
              >
                Opnieuw proberen
              </button>
            </div>
          ) : null}

          <div className="lv-px-workspace">
            <aside className="lv-px-panel">
              <h2 className="lv-px-panel-title">Dataset Acties</h2>
              <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                Geselecteerd: {selected ? "1 dataset" : "geen"}
              </p>
              <div className="lv-px-action-list" style={{ marginTop: 8 }}>
                {SIDEBAR_ACTIONS.map((action) => {
                  const reason = actionDisabledReason(action.id);
                  return (
                    <button
                      key={action.id}
                      type="button"
                      className={action.danger ? "is-danger" : ""}
                      disabled={busy || Boolean(reason)}
                      title={reason ?? undefined}
                      onClick={() => void onSidebarAction(action.id)}
                    >
                      <PxIcon name={action.icon} />
                      <span>{action.label}</span>
                    </button>
                  );
                })}
              </div>
              {exportArtifact ? (
                <button
                  type="button"
                  className="lv-px-btn is-gold"
                  style={{ marginTop: 12, width: "100%" }}
                  disabled={busy}
                  onClick={() => void onDownloadExport()}
                >
                  Download export
                </button>
              ) : null}
            </aside>

            <section className="lv-px-panel">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">Dataset bibliotheek</h2>
                <span style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                  {loading ? "Laden…" : `${filtered.length} zichtbaar · ${datasets.length} totaal`}
                </span>
              </div>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Zoek..."
                    aria-label="Zoek datasets"
                  />
                </label>
                <select className="lv-px-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  {DM_TYPE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select
                  className="lv-px-select"
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                >
                  {DM_SOURCE_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select className="lv-px-select" value={splitFilter} onChange={(e) => setSplitFilter(e.target.value)}>
                  {DM_SPLIT_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <select
                  className="lv-px-select"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  {DM_STATUS_FILTERS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>
              <div className="lv-px-table-wrap">
                {loading ? (
                  <p style={{ fontSize: 10, padding: 12, color: "var(--lv-text-muted)" }}>Datasets laden…</p>
                ) : filtered.length === 0 ? (
                  <p style={{ fontSize: 10, padding: 12, color: "var(--lv-text-muted)" }}>
                    {datasets.length === 0
                      ? "Geen datasets. Upload of importeer om te beginnen."
                      : "Geen datasets passen bij de filters."}
                  </p>
                ) : (
                  <table className="lv-px-table">
                    <thead>
                      <tr>
                        <th>Naam</th>
                        <th>Type</th>
                        <th>Bron</th>
                        <th>Split</th>
                        <th>Grootte</th>
                        <th>Tokens</th>
                        <th>Status</th>
                        <th>Tags</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((row) => {
                        const typeLabel = mapTypeLabel(row);
                        const statusNl = mapDatasetStatus(
                          row.status,
                          row.brainStatus ?? row.brain?.brainStatus,
                          row.canonicalState ?? row.learningState?.canonicalState ?? row.brain?.canonicalState,
                        );
                        const split =
                          row.datasetId === selectedId && selectedVersion
                            ? splitLabelFromVersion(selectedVersion)
                            : "—";
                        const tokenHint =
                          row.datasetId === selectedId && selectedVersion?.tokenStats
                            ? formatCompactCount(
                                Number(
                                  (selectedVersion.tokenStats as Record<string, unknown>).total_tokens ??
                                    (selectedVersion.tokenStats as Record<string, unknown>).token_count,
                                ) || null,
                              )
                            : formatCompactCount(row.rowCount);
                        const tags = tagsForDataset(row);
                        return (
                          <tr
                            key={row.datasetId}
                            className={row.datasetId === selectedId ? "is-active" : ""}
                            onClick={() => setSelectedId(row.datasetId)}
                          >
                            <td><strong>{row.name}</strong></td>
                            <td>
                              <span className={`lv-px-pill is-${typeToneForLabel(typeLabel)}`}>{typeLabel}</span>
                            </td>
                            <td>{mapSourceLabel(row.sourceType)}</td>
                            <td>{split}</td>
                            <td>{formatBytes(row.byteSize)}</td>
                            <td>{tokenHint}</td>
                            <td>
                              <span className={`lv-px-pill is-${toneForStatus(statusNl)}`}>{statusNl}</span>
                            </td>
                            <td>
                              <div className="lv-px-pills">
                                {tags.length === 0 ? (
                                  <span className="lv-px-pill">—</span>
                                ) : (
                                  tags.map((t) => (
                                    <span key={t} className="lv-px-pill">{t}</span>
                                  ))
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </section>

            <aside className="lv-px-stack">
              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Details</h2>
                {detailError ? (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>{detailError}</p>
                ) : selected ? (
                  <>
                    <p style={{ fontSize: 11, color: "var(--lv-text-bright)", margin: "8px 0" }}>{selected.name}</p>
                    <p style={{ fontSize: 10, color: "var(--lv-text-secondary)" }}>
                      {selected.description || "Geen beschrijving"}
                    </p>
                    {versions.length === 0 ? (
                      <p style={{ fontSize: 10, color: "var(--lv-text-muted)", marginTop: 8 }}>
                        Lege dataset — nog geen versies of rijen.
                      </p>
                    ) : null}
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>Bron</dt>
                      <dd>{mapSourceLabel(selected.sourceType)}</dd>
                      <dt>Type</dt>
                      <dd>{mapTypeLabel(selected)}</dd>
                      <dt>Locatie</dt>
                      <dd>{dash(selected.rawPath ?? selected.originalUri)}</dd>
                      <dt>Versie</dt>
                      <dd>
                        {versions.length > 1 ? (
                          <select
                            className="lv-px-select"
                            value={selectedVersionId ?? ""}
                            onChange={(e) => setSelectedVersionId(e.target.value || null)}
                          >
                            {versions.map((v) => (
                              <option key={v.versionId} value={v.versionId}>
                                {v.versionLabel} ({v.kind})
                              </option>
                            ))}
                          </select>
                        ) : (
                          dash(selectedVersion?.versionLabel)
                        )}
                      </dd>
                      <dt>Taal</dt>
                      <dd>
                        {dash(
                          String(
                            (selected.metadata as Record<string, unknown> | undefined)?.language ??
                              (selected.metadata as Record<string, unknown> | undefined)?.lang ??
                              "",
                          ),
                        )}
                      </dd>
                      <dt>Licentie</dt>
                      <dd>{dash(selected.license)}</dd>
                    </dl>
                    {selectedVersion?.validation ? (
                      <pre className="lv-px-code" style={{ marginTop: 8, maxHeight: 120 }}>
                        {JSON.stringify(selectedVersion.validation, null, 2)}
                      </pre>
                    ) : null}
                    <div className="lv-px-action-list" style={{ marginTop: 8 }}>
                      <button
                        type="button"
                        disabled={busy || !selectedId}
                        title="Nog niet ondersteund via API"
                        onClick={() => toast("Metagegevens bewerken is nog niet beschikbaar via de API.")}
                      >
                        <PxIcon name="sliders" />
                        <span>Metagegevens bewerken</span>
                      </button>
                      <button
                        type="button"
                        disabled={!selectedVersionId}
                        onClick={() => setSampleTab("JSON")}
                      >
                        <PxIcon name="file" />
                        <span>Voorbeeld bekijken</span>
                      </button>
                      <Link
                        to={
                          selectedVersionId
                            ? `/training?datasetVersionId=${encodeURIComponent(selectedVersionId)}`
                            : "/training"
                        }
                        style={{ textDecoration: "none", display: "contents" }}
                      >
                        <button type="button">
                          <PxIcon name="play" />
                          <span>Gebruik in training</span>
                        </button>
                      </Link>
                      <Link to="/offline-datasets" style={{ textDecoration: "none", display: "contents" }}>
                        <button type="button">
                          <PxIcon name="database" />
                          <span>Geleerd in Brain</span>
                        </button>
                      </Link>
                    </div>
                  </>
                ) : (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Selecteer een dataset</p>
                )}
              </section>

              <section className="lv-px-panel">
                <div className="lv-px-tabs">
                  {DM_SAMPLE_TABS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`lv-px-tab${sampleTab === t ? " is-active" : ""}`}
                      onClick={() => setSampleTab(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                <pre className="lv-px-code" style={{ marginTop: 8 }}>{samplePreview}</pre>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Opslag</h2>
                <p style={{ fontSize: 10 }}>
                  {formatBytes(totalBytes)} gebruikt ({datasets.length} datasets)
                </p>
                <div className="lv-px-progress is-thin">
                  <i
                    style={{
                      width: `${Math.min(100, datasets.length ? Math.max(4, (totalBytes / (1024 ** 3 * 100)) * 100) : 0)}%`,
                    }}
                  />
                </div>
                <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 6 }}>
                  Geen cluster-quota in API · alleen som van datasetgroottes
                </p>
                <div className="lv-px-tag-cloud" style={{ marginTop: 8 }}>
                  {tagCloud.length === 0 ? (
                    <span className="lv-px-tag">Geen tags in metadata</span>
                  ) : (
                    tagCloud.map((t) => (
                      <span key={t.tag} className="lv-px-tag">
                        {t.tag} ({t.count})
                      </span>
                    ))
                  )}
                </div>
              </section>
            </aside>
          </div>

          <div className="lv-px-footer-bar">
            {DM_FOOTER_ACTIONS.map((a) => {
              let reason: string | null = null;
              if (a.id === "delete") reason = actionDisabledReason("delete");
              if (a.id === "validate") reason = actionDisabledReason("validate");
              if (a.id === "learn") reason = actionDisabledReason("learn");
              if (a.id === "rescan") reason = actionDisabledReason("rescan");
              return (
                <button
                  key={a.id}
                  type="button"
                  className={`lv-px-btn${a.tone === "gold" ? " is-gold" : ""}${a.tone === "danger" ? " is-danger" : ""}`}
                  disabled={busy || Boolean(reason)}
                  title={reason ?? undefined}
                  onClick={() => void onFooterAction(a.id)}
                >
                  {a.label}
                </button>
              );
            })}
          </div>

          <DatasetActivityConsole
            jobs={jobs}
            entries={activityEntries}
            preferredJobId={preferredJobId}
            onPreferredJobIdChange={setPreferredJobId}
            apiError={jobsError}
            live={live}
            busy={busy}
            onCancelJob={onCancelDatasetJob}
            onClearView={clearActivityView}
          />
        </div>
      </main>

      {modal ? (
        <div
          className="lv-dh-modal-backdrop"
          role="presentation"
          onClick={() => !busy && setModal(null)}
        >
          <div
            className="lv-dh-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dm-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            {modal === "create" ? (
              <>
                <h2 id="dm-modal-title">Nieuwe dataset</h2>
                <p>Maak een lege dataset-shell in DatasetService.</p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dm-create-name">Naam</label>
                    <input
                      id="dm-create-name"
                      value={createName}
                      onChange={(e) => setCreateName(e.target.value)}
                      placeholder="mijn-corpus"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-create-desc">Beschrijving</label>
                    <textarea
                      id="dm-create-desc"
                      value={createDesc}
                      onChange={(e) => setCreateDesc(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-create-license">Licentie (optioneel)</label>
                    <input
                      id="dm-create-license"
                      value={createLicense}
                      onChange={(e) => setCreateLicense(e.target.value)}
                      placeholder="MIT"
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Annuleren
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy || !createName.trim()}
                      onClick={() => void onCreateSubmit()}
                    >
                      Aanmaken
                    </button>
                  </div>
                </div>
              </>
            ) : null}

            {modal === "local" ? (
              <>
                <h2 id="dm-modal-title">Lokale bestanden importeren</h2>
                <p>Importeer een bestand dat al bereikbaar is op de LEVIATHAN-server (allowed roots).</p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dm-local-path">Absoluut of toegestaan pad</label>
                    <input
                      id="dm-local-path"
                      value={localPath}
                      onChange={(e) => setLocalPath(e.target.value)}
                      placeholder="/data/corpus.jsonl"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-local-name">Optionele naam</label>
                    <input
                      id="dm-local-name"
                      value={localName}
                      onChange={(e) => setLocalName(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-local-desc">Optionele beschrijving</label>
                    <textarea
                      id="dm-local-desc"
                      value={localDesc}
                      onChange={(e) => setLocalDesc(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Annuleren
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy || !localPath.trim()}
                      onClick={() => void onLocalSubmit()}
                    >
                      Importeren
                    </button>
                  </div>
                </div>
              </>
            ) : null}

            {modal === "hf" ? (
              <>
                <h2 id="dm-modal-title">Importeren (Hugging Face)</h2>
                <p>
                  Importeer een volledige repository (bestandsnaam optioneel) of één bestand.
                  Token wordt niet in jobconfig of logs bewaard.
                </p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-repo">Repository ID</label>
                    <input
                      id="dm-hf-repo"
                      value={hfRepo}
                      onChange={(e) => setHfRepo(e.target.value)}
                      placeholder="owner/dataset"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-rev">Revision</label>
                    <input
                      id="dm-hf-rev"
                      value={hfRevision}
                      onChange={(e) => setHfRevision(e.target.value)}
                      placeholder="main"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-file">Bestandsnaam (optioneel — leeg = volledige repo)</label>
                    <input
                      id="dm-hf-file"
                      value={hfFilename}
                      onChange={(e) => setHfFilename(e.target.value)}
                      placeholder="train.jsonl"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-name">Weergavenaam (optioneel)</label>
                    <input
                      id="dm-hf-name"
                      value={hfName}
                      onChange={(e) => setHfName(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-desc">Beschrijving (optioneel)</label>
                    <textarea
                      id="dm-hf-desc"
                      value={hfDesc}
                      onChange={(e) => setHfDesc(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dm-hf-token">Access token (optioneel)</label>
                    <input
                      id="dm-hf-token"
                      type="password"
                      value={hfToken}
                      onChange={(e) => setHfToken(e.target.value)}
                      autoComplete="off"
                      placeholder="********"
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Annuleren
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy || !hfRepo.trim()}
                      onClick={() => void onHfSubmit()}
                    >
                      {hfFilename.trim() ? "Bestand importeren" : "Volledige repository importeren"}
                    </button>
                  </div>
                </div>
              </>
            ) : null}

            {modal === "delete" ? (
              <>
                <h2 id="dm-modal-title">Dataset verwijderen</h2>
                <p>
                  Bevestig verwijdering van{" "}
                  <strong>{selected?.name ?? selectedId}</strong>. Afhankelijkheden (zoals
                  training-referenties) blokkeren delete via DatasetService.
                </p>
                <div className="lv-dh-modal-actions">
                  <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                    Annuleren
                  </button>
                  <button
                    type="button"
                    className="lv-dh-btn"
                    style={{ background: "rgba(220,80,80,0.25)", borderColor: "rgba(220,80,80,0.5)" }}
                    disabled={busy}
                    onClick={() => void onDeleteConfirm()}
                  >
                    Verwijderen
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
