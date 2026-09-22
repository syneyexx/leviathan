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
import { PxHero, PxIcon, PxKpi } from "./pixel-shared";

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

function mapDatasetStatus(status: string): DatasetMgmtStatus {
  const s = status.toLowerCase();
  if (s === "ready" || s === "complete" || s === "completed") return "Klaar";
  if (s === "processed" || s === "materialized") return "Verwerkt";
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

function jobStatusNl(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded" || s === "done") return "Klaar";
  if (s === "running") return "Bezig";
  if (s === "queued" || s === "pending") return "Wachtrij";
  if (s === "failed" || s === "cancelled") return "Fout";
  return status;
}

function jobProgressPct(job: DatasetJob): number {
  if (job.progress == null) {
    const s = job.status.toLowerCase();
    if (s === "completed" || s === "succeeded") return 100;
    return 0;
  }
  return Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
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

type SidebarAction = {
  id: string;
  label: string;
  icon: string;
  danger?: boolean;
  disabled?: boolean;
  disabledReason?: string;
};

const SIDEBAR_ACTIONS: SidebarAction[] = [
  { id: "upload", label: "Dataset toevoegen", icon: "plus" },
  { id: "hf", label: "Importeren (Hugging Face)", icon: "download" },
  { id: "local", label: "Lokale bestanden importeren", icon: "upload" },
  { id: "create", label: "Nieuwe dataset aanmaken", icon: "squareplus" },
  { id: "delete", label: "Geselecteerde verwijderen", icon: "trash", danger: true },
  {
    id: "offline",
    label: "Converteren naar offline",
    icon: "save",
    disabled: true,
    disabledReason: "Offline-conversie wordt niet ondersteund door DatasetService.",
  },
  {
    id: "dup",
    label: "Dupliceren",
    icon: "copy",
    disabled: true,
    disabledReason: "Dupliceren is nog niet beschikbaar via de API.",
  },
  { id: "index", label: "Index opnieuw opbouwen", icon: "refresh" },
  { id: "validate", label: "Valideren", icon: "checkcircle" },
  { id: "export", label: "Exporteren", icon: "download" },
];

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

  const [preview, setPreview] = useState<DatasetPreviewRow[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sampleTab, setSampleTab] = useState<DatasetSampleTab>("JSON");

  const [jobs, setJobs] = useState<DatasetJob[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState(DM_TYPE_FILTERS[0]);
  const [sourceFilter, setSourceFilter] = useState(DM_SOURCE_FILTERS[0]);
  const [splitFilter, setSplitFilter] = useState(DM_SPLIT_FILTERS[0]);
  const [statusFilter, setStatusFilter] = useState(DM_STATUS_FILTERS[0]);

  const selected = datasets.find((d) => d.datasetId === selectedId) ?? detail;
  const selectedVersion =
    versions.find((v) => v.versionId === selectedVersionId) ??
    versions.find((v) => v.status === "ready") ??
    versions[0] ??
    null;

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listDatasets();
      setDatasets(res.datasets);
      if (res.datasets.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !res.datasets.some((d) => d.datasetId === selectedId)) {
        setSelectedId(res.datasets[0].datasetId);
      }
    } catch (err) {
      setError(errMsg(err, "Datasets laden mislukt"));
      setDatasets([]);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadJobs = useCallback(async () => {
    try {
      const res = await api.listDatasetJobs(undefined, 50);
      setJobs(res.jobs);
      setJobsError(null);
    } catch (err) {
      setJobsError(errMsg(err, "Jobs laden mislukt"));
    }
  }, []);

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
        const ready = res.versions.find((v) => v.status === "ready") ?? res.versions[0];
        setSelectedVersionId(ready?.versionId ?? null);
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
  }, [selectedId]);

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

  useEffect(() => {
    void loadJobs();
    const id = window.setInterval(() => {
      void loadJobs();
    }, 4000);
    return () => window.clearInterval(id);
  }, [loadJobs]);

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
      const statusNl = mapDatasetStatus(ds.status);
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
  const activeJobs = useMemo(
    () =>
      jobs.filter((j) => {
        const s = j.status.toLowerCase();
        return s === "queued" || s === "pending" || s === "running";
      }),
    [jobs],
  );

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
        value: "—",
        hint: "Geen centrale validatieteller in API",
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
    [loading, datasets.length, totalRows, totalBytes, activeJobs, jobsError, error],
  );

  const samplePreview = useMemo(() => {
    if (previewError) return previewError;
    if (preview.length === 0) {
      return selectedVersion ? "Geen voorbeeldrijen voor deze versie." : "Selecteer een dataset met versie.";
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
            return dash(typeof v === "string" || typeof v === "number" ? v : v == null ? null : String(v));
          })
          .join(" | "),
      );
    }
    return lines.join("\n");
  }, [preview, previewError, sampleTab, selectedVersion]);

  async function runVersionJob(
    action: () => Promise<{ job: DatasetJob }>,
    label: string,
  ) {
    if (!selectedId || !selectedVersionId) {
      toast("Selecteer eerst een datasetversie");
      return;
    }
    await withBusy(async () => {
      await action();
      await loadJobs();
    }, `${label} in wachtrij gezet`);
  }

  async function onSidebarAction(actionId: string) {
    switch (actionId) {
      case "upload":
        uploadRef.current?.click();
        return;
      case "create": {
        const name = window.prompt("Naam voor nieuwe dataset:");
        if (!name?.trim()) return;
        const description = window.prompt("Beschrijving (optioneel):") ?? "";
        await withBusy(async () => {
          await api.createDataset({ name: name.trim(), description });
          await loadDatasets();
        }, "Dataset aangemaakt");
        return;
      }
      case "local": {
        const path = window.prompt("Absoluut pad op de server:");
        if (!path?.trim()) return;
        const name = window.prompt("Optionele naam:") ?? undefined;
        await withBusy(async () => {
          await api.importDatasetLocal({
            path: path.trim(),
            name: name?.trim() || undefined,
            materialize: true,
          });
          await loadDatasets();
          await loadJobs();
        }, "Lokale import in wachtrij");
        return;
      }
      case "hf": {
        const repo = window.prompt("Hugging Face repository (org/dataset):");
        if (!repo?.trim()) return;
        const filename = window.prompt("Bestandsnaam in de repo:");
        if (!filename?.trim()) return;
        await withBusy(async () => {
          await api.importDatasetHuggingFace({
            repositoryId: repo.trim(),
            filename: filename.trim(),
            materialize: true,
          });
          await loadJobs();
        }, "Hugging Face import in wachtrij");
        return;
      }
      case "delete":
        if (!selectedId) {
          toast("Geen dataset geselecteerd");
          return;
        }
        if (!window.confirm(`Dataset "${selected?.name ?? selectedId}" verwijderen?`)) return;
        await withBusy(async () => {
          await api.deleteDataset(selectedId);
          await loadDatasets();
        }, "Dataset verwijderd");
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
        );
        return;
      case "index":
        await runVersionJob(
          () => api.indexDatasetVersion(selectedId!, selectedVersionId!),
          "Index",
        );
        return;
      default:
        return;
    }
  }

  async function onUploadFile(file: File | null) {
    if (!file) return;
    await withBusy(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("materialize", "true");
      await api.uploadDataset(form);
      await loadDatasets();
      await loadJobs();
    }, "Upload in wachtrij");
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
    if (id === "offline") {
      toast("Offline-conversie wordt niet ondersteund door DatasetService.");
      return;
    }
    if (id === "save") {
      toast("Metagegevens opslaan is nog niet beschikbaar via de API.");
    }
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
        accept=".jsonl,.ndjson,.json,.csv,.tsv,.txt,.md"
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
                {SIDEBAR_ACTIONS.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    className={action.danger ? "is-danger" : ""}
                    disabled={busy || action.disabled || (action.id === "delete" && !selectedId)}
                    title={action.disabledReason ?? undefined}
                    onClick={() => {
                      if (action.disabled) {
                        toast(action.disabledReason ?? "Niet ondersteund");
                        return;
                      }
                      void onSidebarAction(action.id);
                    }}
                  >
                    <PxIcon name={action.icon} />
                    <span>{action.label}</span>
                  </button>
                ))}
              </div>
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
                        const statusNl = mapDatasetStatus(row.status);
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
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>Bron</dt>
                      <dd>{mapSourceLabel(selected.sourceType)}</dd>
                      <dt>Type</dt>
                      <dd>{mapTypeLabel(selected)}</dd>
                      <dt>Locatie</dt>
                      <dd>{dash(selected.rawPath ?? selected.originalUri)}</dd>
                      <dt>Versie</dt>
                      <dd>{dash(selectedVersion?.versionLabel)}</dd>
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
                        disabled={busy || !selectedId}
                        title="Nog niet ondersteund via API"
                        onClick={() => toast("Tags beheren is nog niet beschikbaar via de API.")}
                      >
                        <PxIcon name="book" />
                        <span>Tags beheren</span>
                      </button>
                      <button
                        type="button"
                        disabled={!selectedVersionId}
                        onClick={() => setSampleTab("JSON")}
                      >
                        <PxIcon name="file" />
                        <span>Voorbeeld bekijken</span>
                      </button>
                      <Link to="/training" style={{ textDecoration: "none", display: "contents" }}>
                        <button type="button">
                          <PxIcon name="play" />
                          <span>Gebruik in training</span>
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
                <h2 className="lv-px-panel-title">Import jobs</h2>
                {jobsError ? (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>{jobsError}</p>
                ) : jobs.length === 0 ? (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Geen jobs in de wachtrij.</p>
                ) : (
                  jobs.slice(0, 8).map((job) => {
                    const dsName =
                      datasets.find((d) => d.datasetId === job.datasetId)?.name ??
                      dash(job.datasetId);
                    const pct = jobProgressPct(job);
                    const cancellable =
                      job.status.toLowerCase() === "queued" || job.status.toLowerCase() === "running";
                    return (
                      <div key={job.jobId} className="lv-px-queue-item">
                        <div className="lv-px-queue-top">
                          <strong>{dsName}</strong>
                          <span>{jobStatusNl(job.status)}</span>
                        </div>
                        <div className="lv-px-progress">
                          <i style={{ width: `${pct}%` }} />
                        </div>
                        <div className="lv-px-queue-meta">
                          <span>{job.jobType}{job.phase ? ` · ${job.phase}` : ""}</span>
                          <span>
                            {cancellable ? (
                              <button
                                type="button"
                                style={{ fontSize: 9, background: "none", border: 0, color: "inherit", cursor: "pointer" }}
                                disabled={busy}
                                onClick={() =>
                                  void withBusy(async () => {
                                    await api.cancelDatasetJob(job.jobId);
                                    await loadJobs();
                                  }, "Annuleren aangevraagd")
                                }
                              >
                                Annuleren
                              </button>
                            ) : (
                              job.updatedAt
                            )}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
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
            {DM_FOOTER_ACTIONS.map((a) => (
              <button
                key={a.id}
                type="button"
                className={`lv-px-btn${a.tone === "gold" ? " is-gold" : ""}${a.tone === "danger" ? " is-danger" : ""}`}
                disabled={busy || (a.id === "delete" && !selectedId) || (a.id === "validate" && !selectedVersionId)}
                onClick={() => void onFooterAction(a.id)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </main>
    </AppShell>
  );
}
