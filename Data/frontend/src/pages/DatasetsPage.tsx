import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import {
  DH_FILTER_PILLS,
  DH_PAGE_COPY,
  DH_TYPE_OPTIONS,
  DH_UPDATED_OPTIONS,
  type DhEmbedding,
  type DhFilterId,
  type DhRow,
  type DhSourceKind,
  type DhStatus,
} from "../mocks/datasets-dashboard";
import { useAppToast } from "../state/useAppToast";
import type { DatasetJob, DatasetRecord, HfDatasetFile } from "../types/api";

type ViewMode = "list" | "grid";
type ModalKind = "create" | "import" | "hf" | null;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
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

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const diff = Date.now() - t;
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(t).toLocaleDateString();
}

function mapSourceKind(sourceType: string): DhSourceKind {
  const s = sourceType.toLowerCase();
  if (s.includes("hugging") || s === "hf") return "huggingface";
  if (s.includes("local") || s === "path" || s.includes("upload") || s === "file") return "local";
  if (s.includes("curat")) return "curated";
  if (s.includes("arxiv")) return "arxiv";
  if (s.includes("ncbi") || s.includes("pubmed")) return "ncbi";
  return "other";
}

function mapSourceLabel(sourceType: string, kind: DhSourceKind): string {
  if (kind === "huggingface") return "Hugging Face";
  if (kind === "local") return "Local";
  if (kind === "curated") return "Curated";
  if (kind === "arxiv") return "arXiv";
  if (kind === "ncbi") return "NCBI";
  return sourceType || "—";
}

function mapStatus(status: string): DhStatus {
  const s = status.toLowerCase();
  if (s === "offline" || s === "cached") return "offline";
  if (s.includes("validat")) return "validating";
  if (
    s === "running" ||
    s === "processing" ||
    s === "importing" ||
    s === "materializing" ||
    s === "queued"
  ) {
    return "processing";
  }
  if (s === "ready" || s === "complete" || s === "completed" || s === "processed" || s === "materialized") {
    return "ready";
  }
  return "ready";
}

function mapType(ds: DatasetRecord): string {
  const fmt = (ds.detectedFormat ?? "").toLowerCase();
  if (fmt.includes("csv") || fmt.includes("tsv") || fmt.includes("parquet")) return "Structured";
  if (fmt.includes("pdf") || fmt.includes("md") || fmt.includes("doc")) return "Document";
  if (fmt.includes("code") || fmt.includes("py") || fmt.includes("js")) return "Code";
  if (fmt.includes("image") || fmt.includes("multi")) return "Multimodal";
  if (fmt) return "Text";
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const task = String(meta?.taskType ?? meta?.type ?? "").toLowerCase();
  if (task.includes("struct")) return "Structured";
  if (task.includes("code")) return "Code";
  if (task.includes("doc")) return "Document";
  return "Text";
}

function embeddingsForDataset(ds: DatasetRecord, jobs: DatasetJob[]): DhEmbedding {
  const related = jobs.filter((j) => j.datasetId === ds.datasetId);
  const indexing = related.find((j) => {
    const t = j.jobType.toLowerCase();
    const s = j.status.toLowerCase();
    return t.includes("index") && (s === "running" || s === "queued" || s === "pending");
  });
  if (indexing) {
    const pct =
      indexing.progress == null
        ? indexing.status.toLowerCase() === "queued"
          ? 0
          : 35
        : Math.round(Math.min(1, Math.max(0, indexing.progress)) * 100);
    if (indexing.status.toLowerCase() === "queued" || indexing.status.toLowerCase() === "pending") {
      return { kind: "queued" };
    }
    return { kind: "indexing", pct };
  }
  const done = related.some((j) => {
    const t = j.jobType.toLowerCase();
    const s = j.status.toLowerCase();
    return t.includes("index") && (s === "completed" || s === "succeeded" || s === "done");
  });
  if (done) return { kind: "indexed" };
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const emb = String(meta?.embeddings ?? meta?.indexStatus ?? "").toLowerCase();
  if (emb.includes("index")) return { kind: "indexed" };
  if (emb.includes("pending")) return { kind: "pending" };
  if (mapStatus(ds.status) === "ready") return { kind: "not_indexed" };
  return { kind: "pending" };
}

function recordToRow(ds: DatasetRecord, jobs: DatasetJob[]): DhRow {
  const sourceKind = mapSourceKind(ds.sourceType);
  return {
    id: ds.datasetId,
    name: ds.name,
    description: ds.description || ds.originalFilename || ds.datasetId,
    source: mapSourceLabel(ds.sourceType, sourceKind),
    sourceKind,
    type: mapType(ds),
    size: formatBytes(ds.byteSize),
    records: formatCompactCount(ds.rowCount),
    status: mapStatus(ds.status),
    embeddings: embeddingsForDataset(ds, jobs),
    updated: relativeTime(ds.updatedAt),
    live: true,
    byteSize: ds.byteSize,
    rowCount: ds.rowCount,
    updatedAt: ds.updatedAt,
  };
}

function matchesFilter(row: DhRow, filter: DhFilterId): boolean {
  if (filter === "all") return true;
  if (filter === "local") return row.sourceKind === "local";
  if (filter === "huggingface") return row.sourceKind === "huggingface";
  if (filter === "curated") return row.sourceKind === "curated";
  if (filter === "offline") return row.status === "offline";
  if (filter === "processing") return row.status === "processing" || row.status === "validating";
  return true;
}

function sourceGlyph(kind: DhSourceKind): string {
  if (kind === "huggingface") return "🤗";
  if (kind === "arxiv") return "χ";
  if (kind === "ncbi") return "🧬";
  if (kind === "local") return "△";
  if (kind === "curated") return "⛨";
  return "◉";
}

function filterIcon(icon: string): string {
  if (icon === "grid") return "▦";
  if (icon === "folder") return "▤";
  if (icon === "hf") return "🤗";
  if (icon === "shield") return "⛨";
  if (icon === "offline") return "⊘";
  if (icon === "pulse") return "∿";
  return "•";
}

function overviewIcon(icon: string): string {
  if (icon === "database") return "◫";
  if (icon === "folder") return "▤";
  if (icon === "offline") return "⊘";
  if (icon === "sync") return "↻";
  return "•";
}

function donutSegments(slices: { value: number; color: string }[]) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const c = 2 * Math.PI * 36;
  let offset = 0;
  return slices.map((slice) => {
    const len = (slice.value / total) * c;
    const seg = { dash: `${len} ${c - len}`, offset: -offset, color: slice.color };
    offset += len;
    return seg;
  });
}

function statusLabel(status: DhStatus): string {
  if (status === "ready") return "Ready";
  if (status === "offline") return "Offline";
  if (status === "validating") return "Validating";
  return "Processing";
}

function EmbeddingsCell({ emb }: { emb: DhEmbedding }) {
  if (emb.kind === "indexed") {
    return (
      <span className="lv-dh-embed is-indexed">
        <span className="lv-dh-dot" aria-hidden="true" />
        Indexed
      </span>
    );
  }
  if (emb.kind === "indexing") {
    return (
      <div className="lv-dh-embed-progress" aria-label={`Indexing ${emb.pct}%`}>
        <span>Indexing {emb.pct}%</span>
        <div className="lv-dh-bar">
          <i style={{ width: `${emb.pct}%` }} />
        </div>
      </div>
    );
  }
  const label =
    emb.kind === "not_indexed" ? "Not indexed" : emb.kind === "queued" ? "Queued" : "Pending";
  return <span className="lv-dh-embed is-muted">{label}</span>;
}

export function DatasetsPage() {
  const toast = useAppToast();
  const menuRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [jobs, setJobs] = useState<DatasetJob[]>([]);

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

  const [modal, setModal] = useState<ModalKind>(null);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [hfRepo, setHfRepo] = useState("");
  const [hfRevision, setHfRevision] = useState("main");
  const [hfToken, setHfToken] = useState("");
  const [hfFiles, setHfFiles] = useState<HfDatasetFile[]>([]);
  const [hfFilename, setHfFilename] = useState("");

  const liveRows = useMemo(
    () => datasets.map((ds) => recordToRow(ds, jobs)),
    [datasets, jobs],
  );

  const baseRows: DhRow[] = liveRows;

  const filterCounts = useMemo(() => {
    const counts: Record<DhFilterId, number> = {
      all: baseRows.length,
      local: 0,
      huggingface: 0,
      curated: 0,
      offline: 0,
      processing: 0,
    };
    for (const row of baseRows) {
      if (row.sourceKind === "local") counts.local += 1;
      if (row.sourceKind === "huggingface") counts.huggingface += 1;
      if (row.sourceKind === "curated") counts.curated += 1;
      if (row.status === "offline") counts.offline += 1;
      if (row.status === "processing" || row.status === "validating") counts.processing += 1;
    }
    return counts;
  }, [baseRows]);

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = baseRows.filter((row) => matchesFilter(row, filter));
    if (typeFilter !== "All Types") {
      rows = rows.filter((r) => r.type === typeFilter);
    }
    if (q) {
      rows = rows.filter(
        (r) =>
          r.name.toLowerCase().includes(q) ||
          r.description.toLowerCase().includes(q) ||
          r.source.toLowerCase().includes(q) ||
          (r.tags ?? []).some((t) => t.toLowerCase().includes(q)),
      );
    }
    if (updatedFilter === "Oldest first") {
      rows = [...rows].reverse();
    }
    return rows;
  }, [baseRows, filter, query, typeFilter, updatedFilter]);

  const overviewStats = useMemo(() => {
    const local = liveRows.filter((r) => r.sourceKind === "local").length;
    const offline = liveRows.filter((r) => r.status === "offline").length;
    const activeJobs = jobs.filter((j) => {
      const s = j.status.toLowerCase();
      return s === "running" || s === "queued" || s === "pending";
    }).length;
    return [
      { id: "total", label: "Total Datasets", value: String(liveRows.length), icon: "database" },
      { id: "local", label: "Local Datasets", value: String(local), icon: "folder" },
      { id: "offline", label: "Offline Ready", value: String(offline), icon: "offline" },
      { id: "sync", label: "Active Sync Jobs", value: String(activeJobs), icon: "sync" },
    ];
  }, [liveRows, jobs]);

  const storage = useMemo(() => {
    const totalBytes = liveRows.reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const usedGb = totalBytes / 1024 ** 3;
    const localBytes = liveRows
      .filter((r) => r.sourceKind === "local")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const processingBytes = liveRows
      .filter((r) => r.status === "processing" || r.status === "validating")
      .reduce((sum, r) => sum + (r.byteSize ?? 0), 0);
    const other = Math.max(0, totalBytes - localBytes - processingBytes);
    const cacheEstimate = Math.min(totalBytes * 0.18, 18.1 * 1024 ** 3);
    return {
      usedGb: Number(usedGb.toFixed(1)) || 0,
      totalGb: Math.max(200, Math.ceil(usedGb / 50) * 50 || 200),
      segments: [
        { id: "local", label: "Local Datasets", gb: Number((localBytes / 1024 ** 3).toFixed(1)), color: "#2ec4b6" },
        { id: "cache", label: "Cache & Indexes", gb: Number((cacheEstimate / 1024 ** 3).toFixed(1)), color: "#4f8cff" },
        {
          id: "processing",
          label: "Processing",
          gb: Number((processingBytes / 1024 ** 3).toFixed(1)),
          color: "#9b5cff",
        },
        { id: "other", label: "Other", gb: Number((other / 1024 ** 3).toFixed(1)), color: "#6b7280" },
      ],
    };
  }, [liveRows]);

  const storageDonut = useMemo(
    () => donutSegments(storage.segments.map((s) => ({ value: Math.max(s.gb, 0.01), color: s.color }))),
    [storage],
  );

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
          pct: 0,
          eta: "—",
          tone: "cyan" as const,
          icon: "pulse",
        },
      ];
    }
    return active.map((j) => {
      const pct =
        j.progress == null
          ? j.status.toLowerCase() === "queued"
            ? 0
            : 20
          : Math.round(Math.min(1, Math.max(0, j.progress)) * 100);
      const dsName = datasets.find((d) => d.datasetId === j.datasetId)?.name ?? j.datasetId ?? "dataset";
      return {
        id: j.jobId,
        title: j.jobType.replace(/_/g, " "),
        detail: dsName,
        pct,
        eta: j.phase ? String(j.phase) : relativeTime(j.updatedAt),
        tone: (j.jobType.toLowerCase().includes("index") ? "cyan" : "purple") as "cyan" | "purple" | "blue",
        icon: j.jobType.toLowerCase().includes("index") ? "brain" : "pulse",
      };
    });
  }, [jobs, datasets]);

  const healthItems = useMemo(() => {
    const total = liveRows.length || 1;
    const ready = liveRows.filter((r) => r.status === "ready").length;
    const indexed = liveRows.filter((r) => r.embeddings.kind === "indexed").length;
    const offline = liveRows.filter((r) => r.status === "offline").length;
    const validating = liveRows.filter((r) => r.status === "validating").length;
    return [
      {
        id: "ready",
        label: "Ready Coverage",
        pct: Math.round((ready / total) * 100),
        hint: `${ready}/${liveRows.length} ready (status counts, not integrity proof)`,
        tone: "green" as const,
      },
      {
        id: "schema",
        label: "Schema Validation",
        // Do not invent a health % from warning count.
        pct: null as number | null,
        hint: validating
          ? `${validating} validating`
          : liveRows.length
            ? "0 validating (no schema probe score)"
            : "unmeasured",
        tone: "teal" as const,
      },
      {
        id: "embedding",
        label: "Embedding Coverage",
        pct: Math.round((indexed / total) * 100),
        hint: `${Math.max(0, liveRows.length - indexed)} datasets not indexed`,
        tone: "blue" as const,
      },
      {
        id: "offline",
        label: "Offline Availability",
        pct: Math.round((offline / total) * 100),
        hint: `${offline} datasets marked offline`,
        tone: "orange" as const,
      },
    ];
  }, [liveRows]);

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listDatasets(200);
      setDatasets(res.datasets);
      if (res.datasets[0] && !activeId) setActiveId(res.datasets[0].datasetId);
    } catch (err) {
      setError(errMsg(err, "Failed to load datasets"));
      setDatasets([]);
    } finally {
      setLoading(false);
    }
  }, [activeId]);

  const loadJobs = useCallback(async () => {
    try {
      const res = await api.listDatasetJobs(undefined, 50);
      setJobs(res.jobs);
    } catch {
      /* jobs are supplementary */
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
    void loadJobs();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    const id = window.setInterval(() => void loadJobs(), 5000);
    return () => window.clearInterval(id);
  }, [loadJobs]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setMenuFor(null);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  async function withBusy(fn: () => Promise<void>, okMsg?: string) {
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
      await api.uploadDataset(form);
      setUploadFile(null);
      setModal(null);
      await loadDatasets();
      await loadJobs();
    }, "Upload queued");
  }

  async function onImportLocal() {
    if (!localPath.trim()) {
      toast("Local path is required");
      return;
    }
    await withBusy(async () => {
      await api.importDatasetLocal({
        path: localPath.trim(),
        name: localName.trim() || undefined,
        materialize: true,
      });
      setModal(null);
      await loadJobs();
      await loadDatasets();
    }, "Local import queued");
  }

  async function onListHf() {
    if (!hfRepo.trim()) {
      toast("Repository id is required");
      return;
    }
    setBusy(true);
    try {
      const res = await api.listHuggingFaceDatasetFiles({
        repositoryId: hfRepo.trim(),
        revision: hfRevision.trim() || "main",
        token: hfToken.trim() || null,
      });
      setHfFiles(res.files);
      if (res.files[0]) {
        setHfFilename(String(res.files[0].path ?? res.files[0].filename ?? ""));
      }
      if (res.files.length === 0) toast("No files returned");
    } catch (err) {
      toast(errMsg(err, "HuggingFace list failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onImportHf() {
    if (!hfRepo.trim() || !hfFilename.trim()) {
      toast("Repository and filename are required");
      return;
    }
    await withBusy(async () => {
      await api.importDatasetHuggingFace({
        repositoryId: hfRepo.trim(),
        filename: hfFilename.trim(),
        revision: hfRevision.trim() || "main",
        token: hfToken.trim() || null,
        materialize: true,
      });
      setModal(null);
      await loadJobs();
      await loadDatasets();
    }, "HuggingFace import queued");
  }

  async function onDelete(id: string) {
    if (!window.confirm("Delete this dataset?")) return;
    await withBusy(async () => {
      await api.deleteDataset(id);
      setMenuFor(null);
      await loadDatasets();
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

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Datasets Mode"
      searchPlaceholder="Search datasets…"
      pageClass="lv-app--datasets-dash"
      layout="wide"
      systemItems={[
        "DATASETS",
        loading ? "LOADING" : error ? "ERROR" : "LIVE",
        `${filterCounts.all}`,
      ]}
    >
      <main className="lv-main lv-dh-main">
        <header className="lv-dh-hero" aria-label="Datasets hero">
          <div className="lv-dh-hero-media">
            <img src="/assets/hero-datasets.jpg" alt="" width={1600} height={440} />
          </div>
          <div className="lv-dh-hero-shade" />
          <div className="lv-dh-hero-body">
            <div className="lv-dh-hero-copy">
              <h1 className="lv-dh-hero-title">{DH_PAGE_COPY.title}</h1>
              <p className="lv-dh-hero-sub">{DH_PAGE_COPY.subtitle}</p>
              <p className="lv-dh-hero-desc">{DH_PAGE_COPY.description}</p>
            </div>
            <p className="lv-dh-hero-quote">{DH_PAGE_COPY.quote}</p>
          </div>
        </header>

        <div className="lv-dh-toolbar">
          <div className="lv-dh-pills" role="tablist" aria-label="Dataset filters">
            {DH_FILTER_PILLS.map((pill) => (
              <button
                key={pill.id}
                type="button"
                role="tab"
                aria-selected={filter === pill.id}
                className={`lv-dh-pill${filter === pill.id ? " is-active" : ""}`}
                onClick={() => setFilter(pill.id)}
              >
                <span className="lv-dh-pill-ico" aria-hidden="true">
                  {filterIcon(pill.icon)}
                </span>
                {pill.label}
                <span className="lv-dh-pill-count">({filterCounts[pill.id]})</span>
              </button>
            ))}
          </div>
          <div className="lv-dh-view-tools">
            <span className="lv-dh-view-label">View</span>
            <div className="lv-dh-view-toggle" role="group" aria-label="View mode">
              <button
                type="button"
                className={`lv-dh-view-btn${view === "list" ? " is-active" : ""}`}
                aria-pressed={view === "list"}
                aria-label="List view"
                onClick={() => setView("list")}
              >
                ☰
              </button>
              <button
                type="button"
                className={`lv-dh-view-btn${view === "grid" ? " is-active" : ""}`}
                aria-pressed={view === "grid"}
                aria-label="Grid view"
                onClick={() => setView("grid")}
              >
                ▦
              </button>
            </div>
            <button
              type="button"
              className={`lv-dh-filters-btn${filtersOpen ? " is-open" : ""}`}
              aria-expanded={filtersOpen}
              onClick={() => setFiltersOpen((v) => !v)}
            >
              ▽ Filters
            </button>
          </div>
        </div>

        <div className="lv-dh-actions">
          <label className="lv-dh-search">
            <span className="lv-dh-search-ico" aria-hidden="true">
              ⌕
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search datasets by name, description, or tags..."
              aria-label="Search datasets"
            />
          </label>
          <select
            className="lv-dh-select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}
            aria-label="Filter by type"
          >
            {DH_TYPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          <select
            className="lv-dh-select"
            value={updatedFilter}
            onChange={(e) => setUpdatedFilter(e.target.value as typeof updatedFilter)}
            aria-label="Sort by updated"
          >
            {DH_UPDATED_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          <div className="lv-dh-action-btns">
            <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal("import")}>
              <span className="lv-dh-btn-ico" aria-hidden="true">
                ↓
              </span>
              Import Dataset
            </button>
            <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal("hf")}>
              <span className="lv-dh-btn-ico" aria-hidden="true">
                🤗
              </span>
              Connect Hugging Face
            </button>
            <button
              type="button"
              className="lv-dh-btn lv-dh-btn-gold"
              disabled={busy}
              onClick={() => setModal("create")}
            >
              Create Dataset +
            </button>
          </div>
        </div>

        {error ? (
          <div className="lv-dh-banner is-error" role="alert">
            <strong>Datasets unavailable</strong>
            <span>{error}</span>
            <button type="button" className="lv-dh-btn" onClick={() => void loadDatasets()}>
              Retry
            </button>
          </div>
        ) : null}

        {!loading && !error && datasets.length === 0 ? (
          <div className="lv-dh-banner" role="status">
            <strong>No datasets yet</strong>
            <span>Create, upload, or import a dataset to populate this inventory.</span>
          </div>
        ) : null}

        {loading ? (
          <div className="lv-dh-banner" role="status">
            Loading datasets…
          </div>
        ) : null}

        <section className="lv-dh-panel" aria-label="Datasets inventory">
          <span className="lv-dh-panel-corners" aria-hidden="true" />
          {view === "list" ? (
            <div className="lv-dh-table-wrap">
              <table className="lv-dh-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <input
                        type="checkbox"
                        className="lv-dh-check"
                        checked={
                          filteredRows.length > 0 && filteredRows.every((r) => selectedIds.has(r.id))
                        }
                        onChange={toggleSelectAll}
                        aria-label="Select all"
                      />
                    </th>
                    <th scope="col">Name</th>
                    <th scope="col">Source</th>
                    <th scope="col">Type</th>
                    <th scope="col">Size</th>
                    <th scope="col">Records</th>
                    <th scope="col">Status</th>
                    <th scope="col">Embeddings</th>
                    <th scope="col">Last Updated</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((row) => (
                    <tr
                      key={row.id}
                      className={activeId === row.id ? "is-selected" : undefined}
                      onClick={() => setActiveId(row.id)}
                    >
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          className="lv-dh-check"
                          checked={selectedIds.has(row.id)}
                          onChange={() => toggleSelected(row.id)}
                          aria-label={`Select ${row.name}`}
                        />
                      </td>
                      <td>
                        <div className="lv-dh-name">
                          <strong>{row.name}</strong>
                          <span>{row.description}</span>
                        </div>
                      </td>
                      <td>
                        <span className="lv-dh-source">
                          <span className={`lv-dh-source-ico is-${row.sourceKind}`} aria-hidden="true">
                            {sourceGlyph(row.sourceKind)}
                          </span>
                          {row.source}
                        </span>
                      </td>
                      <td>{row.type}</td>
                      <td>{row.size}</td>
                      <td>{row.records}</td>
                      <td>
                        <span className={`lv-dh-status is-${row.status}`}>
                          {row.status === "ready" || row.status === "offline" ? (
                            <span className="lv-dh-dot" aria-hidden="true" />
                          ) : (
                            <span className="lv-dh-spin" aria-hidden="true" />
                          )}
                          {statusLabel(row.status)}
                        </span>
                      </td>
                      <td>
                        <EmbeddingsCell emb={row.embeddings} />
                      </td>
                      <td>{row.updated}</td>
                      <td onClick={(e) => e.stopPropagation()} style={{ position: "relative" }}>
                        <button
                          type="button"
                          className="lv-dh-more"
                          aria-label={`Actions for ${row.name}`}
                          onClick={() => setMenuFor((m) => (m === row.id ? null : row.id))}
                        >
                          ⋯
                        </button>
                        {menuFor === row.id ? (
                          <div className="lv-dh-menu" ref={menuRef} role="menu">
                            <button type="button" role="menuitem" onClick={() => void onIndex(row.id)}>
                              Index embeddings
                            </button>
                            <Link
                              to="/offline-datasets"
                              role="menuitem"
                              onClick={() => setMenuFor(null)}
                              style={{
                                padding: "8px 10px",
                                borderRadius: 7,
                                color: "inherit",
                                textDecoration: "none",
                                fontSize: 12,
                              }}
                            >
                              Open offline view
                            </Link>
                            <button
                              type="button"
                              role="menuitem"
                              className="is-danger"
                              onClick={() => void onDelete(row.id)}
                            >
                              Delete
                            </button>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                  {filteredRows.length === 0 ? (
                    <tr>
                      <td colSpan={10} style={{ textAlign: "center", padding: 28, color: "#696964" }}>
                        No datasets match these filters.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="lv-dh-grid">
              {filteredRows.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={`lv-dh-card${activeId === row.id ? " is-selected" : ""}`}
                  onClick={() => setActiveId(row.id)}
                >
                  <div className="lv-dh-card-top">
                    <span className={`lv-dh-status is-${row.status}`}>{statusLabel(row.status)}</span>
                    <span className="lv-dh-source">
                      <span className={`lv-dh-source-ico is-${row.sourceKind}`} aria-hidden="true">
                        {sourceGlyph(row.sourceKind)}
                      </span>
                      {row.source}
                    </span>
                  </div>
                  <h3>{row.name}</h3>
                  <p>{row.description}</p>
                  <div className="lv-dh-card-meta">
                    <span>{row.type}</span>
                    <span>{row.size}</span>
                    <span>{row.records}</span>
                    <span>{row.updated}</span>
                  </div>
                  <EmbeddingsCell emb={row.embeddings} />
                </button>
              ))}
              {filteredRows.length === 0 ? (
                <p className="lv-dh-banner" style={{ gridColumn: "1 / -1" }}>
                  No datasets match these filters.
                </p>
              ) : null}
            </div>
          )}
        </section>

        <div className="lv-dh-widgets">
          <article className="lv-dh-widget">
            <span className="lv-dh-widget-foot-corners" aria-hidden="true" />
            <div className="lv-dh-widget-head">
              <h2>Dataset Overview</h2>
              <button type="button" className="lv-dh-widget-link" onClick={() => setFilter("all")}>
                View all →
              </button>
            </div>
            <div className="lv-dh-overview-grid">
              {overviewStats.map((stat, i) => (
                <div key={stat.id} className="lv-dh-stat">
                  <span className={`lv-dh-stat-ico${i % 2 === 1 ? " is-cyan" : ""}`} aria-hidden="true">
                    {overviewIcon(stat.icon)}
                  </span>
                  <b>{stat.value}</b>
                  <span>{stat.label}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="lv-dh-widget">
            <span className="lv-dh-widget-foot-corners" aria-hidden="true" />
            <div className="lv-dh-widget-head">
              <h2>Storage Usage</h2>
            </div>
            <div className="lv-dh-storage-body">
              <div className="lv-dh-donut-wrap" aria-hidden="true">
                <svg className="lv-dh-donut" viewBox="0 0 96 96">
                  <circle cx="48" cy="48" r="36" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
                  {storageDonut.map((seg, i) => (
                    <circle
                      key={storage.segments[i]?.id ?? i}
                      cx="48"
                      cy="48"
                      r="36"
                      fill="none"
                      stroke={seg.color}
                      strokeWidth="10"
                      strokeDasharray={seg.dash}
                      strokeDashoffset={seg.offset}
                      strokeLinecap="butt"
                    />
                  ))}
                </svg>
                <div className="lv-dh-donut-center">
                  <strong>{storage.usedGb} GB</strong>
                  <span>of {storage.totalGb} GB</span>
                </div>
              </div>
              <ul className="lv-dh-legend">
                {storage.segments.map((seg) => (
                  <li key={seg.id}>
                    <i style={{ background: seg.color }} />
                    <span>{seg.label}</span>
                    <b>{seg.gb} GB</b>
                  </li>
                ))}
              </ul>
            </div>
            <button
              type="button"
              className="lv-dh-btn"
              onClick={() => toast("Storage management opens from Settings → Storage")}
            >
              Manage Storage
            </button>
          </article>

          <article className="lv-dh-widget">
            <span className="lv-dh-widget-foot-corners" aria-hidden="true" />
            <div className="lv-dh-widget-head">
              <h2>Dataset Pipeline</h2>
              <button
                type="button"
                className="lv-dh-widget-link"
                onClick={() =>
                  void withBusy(async () => {
                    const res = await api.processDatasetJobs();
                    toast(`Processed ${res.processed.length} job(s)`);
                    await loadJobs();
                  })
                }
              >
                View Queue →
              </button>
            </div>
            <ul className="lv-dh-pipeline-list">
              {pipelineItems.map((item) => (
                <li key={item.id}>
                  <span className={`lv-dh-pipe-ico is-${item.tone}`} aria-hidden="true">
                    {item.icon === "brain" ? "◉" : item.icon === "check" ? "✓" : "∿"}
                  </span>
                  <div className="lv-dh-pipe-body">
                    <div className="lv-dh-pipe-title">{item.title}</div>
                    <div className="lv-dh-pipe-detail">{item.detail}</div>
                    <div className="lv-dh-bar">
                      <i style={{ width: `${item.pct}%` }} />
                    </div>
                    <div className="lv-dh-pipe-meta">
                      <span>{item.pct}%</span>
                      <span>{item.eta}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-dh-widget">
            <span className="lv-dh-widget-foot-corners" aria-hidden="true" />
            <div className="lv-dh-widget-head">
              <h2>Dataset Health</h2>
            </div>
            <ul className="lv-dh-health-list">
              {healthItems.map((item) => {
                const pctLabel = item.pct == null ? "unmeasured" : `${item.pct}%`;
                const barWidth = item.pct == null ? 0 : item.pct;
                return (
                  <li key={item.id}>
                    <span className="lv-dh-health-label">{item.label}</span>
                    <span className={`lv-dh-health-pct is-${item.tone}`}>{pctLabel}</span>
                    {item.hint ? <span className="lv-dh-health-hint">{item.hint}</span> : null}
                    <div className={`lv-dh-health-bar is-${item.tone}`}>
                      <i style={{ width: `${barWidth}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          </article>
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
            aria-labelledby="lv-dh-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            {modal === "create" ? (
              <>
                <h2 id="lv-dh-modal-title">Create Dataset</h2>
                <p>Register an empty dataset shell in LEVIATHAN.</p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dh-create-name">Name</label>
                    <input
                      id="dh-create-name"
                      value={createName}
                      onChange={(e) => setCreateName(e.target.value)}
                      placeholder="my-corpus"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dh-create-desc">Description</label>
                    <textarea
                      id="dh-create-desc"
                      value={createDesc}
                      onChange={(e) => setCreateDesc(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy}
                      onClick={() => void onCreate()}
                    >
                      Create
                    </button>
                  </div>
                </div>
              </>
            ) : null}

            {modal === "import" ? (
              <>
                <h2 id="lv-dh-modal-title">Import Dataset</h2>
                <p>Upload a file or import from a local server path.</p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dh-upload">Upload file</label>
                    <input
                      id="dh-upload"
                      type="file"
                      onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dh-import-name">Optional name</label>
                    <input
                      id="dh-import-name"
                      value={createName}
                      onChange={(e) => setCreateName(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy || !uploadFile}
                      onClick={() => void onUpload()}
                    >
                      Upload &amp; queue
                    </button>
                  </div>
                  <hr style={{ borderColor: "rgba(214,169,87,0.2)", width: "100%" }} />
                  <div className="lv-dh-field">
                    <label htmlFor="dh-local-path">Local absolute path</label>
                    <input
                      id="dh-local-path"
                      value={localPath}
                      onChange={(e) => setLocalPath(e.target.value)}
                      placeholder="/data/corpus.jsonl"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dh-local-name">Optional name</label>
                    <input
                      id="dh-local-name"
                      value={localName}
                      onChange={(e) => setLocalName(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy}
                      onClick={() => void onImportLocal()}
                    >
                      Import local
                    </button>
                  </div>
                </div>
              </>
            ) : null}

            {modal === "hf" ? (
              <>
                <h2 id="lv-dh-modal-title">Connect Hugging Face</h2>
                <p>List files from a repository, then queue an import job.</p>
                <div className="lv-dh-form">
                  <div className="lv-dh-field">
                    <label htmlFor="dh-hf-repo">Repository id</label>
                    <input
                      id="dh-hf-repo"
                      value={hfRepo}
                      onChange={(e) => setHfRepo(e.target.value)}
                      placeholder="org/dataset"
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dh-hf-rev">Revision</label>
                    <input
                      id="dh-hf-rev"
                      value={hfRevision}
                      onChange={(e) => setHfRevision(e.target.value)}
                    />
                  </div>
                  <div className="lv-dh-field">
                    <label htmlFor="dh-hf-token">Token (optional)</label>
                    <input
                      id="dh-hf-token"
                      type="password"
                      value={hfToken}
                      onChange={(e) => setHfToken(e.target.value)}
                      autoComplete="off"
                    />
                  </div>
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => void onListHf()}>
                      List files
                    </button>
                  </div>
                  {hfFiles.length > 0 ? (
                    <div className="lv-dh-field">
                      <label htmlFor="dh-hf-file">Filename</label>
                      <select
                        id="dh-hf-file"
                        value={hfFilename}
                        onChange={(e) => setHfFilename(e.target.value)}
                      >
                        {hfFiles.map((f) => {
                          const name = String(f.path ?? f.filename ?? "");
                          return (
                            <option key={name} value={name}>
                              {name}
                            </option>
                          );
                        })}
                      </select>
                    </div>
                  ) : (
                    <div className="lv-dh-field">
                      <label htmlFor="dh-hf-file-manual">Filename</label>
                      <input
                        id="dh-hf-file-manual"
                        value={hfFilename}
                        onChange={(e) => setHfFilename(e.target.value)}
                        placeholder="data/train.jsonl"
                      />
                    </div>
                  )}
                  <div className="lv-dh-modal-actions">
                    <button type="button" className="lv-dh-btn" disabled={busy} onClick={() => setModal(null)}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="lv-dh-btn lv-dh-btn-gold"
                      disabled={busy || !hfRepo.trim() || !hfFilename.trim()}
                      onClick={() => void onImportHf()}
                    >
                      Import from Hugging Face
                    </button>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
