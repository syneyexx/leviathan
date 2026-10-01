/**
 * Pure DatasetRecord → DhRow mapping for Onderzoek & Kennis → Datasets.
 * Backend status/job truth only — never invent Ready / 100% / measured zero.
 */

import type {
  DhEmbedding,
  DhRow,
  DhSourceKind,
  DhStatus,
} from "./constants";
import type { DatasetJob, DatasetRecord } from "../../types/api";

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatCompactCount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function relativeTime(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const diff = nowMs - t;
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(t).toLocaleDateString();
}

export function mapSourceKind(sourceType: string): DhSourceKind {
  const s = sourceType.toLowerCase();
  if (s.includes("hugging") || s === "hf") return "huggingface";
  if (s.includes("local") || s === "path" || s.includes("upload") || s === "file") return "local";
  if (s.includes("curat")) return "curated";
  if (s.includes("arxiv")) return "arxiv";
  if (s.includes("ncbi") || s.includes("pubmed")) return "ncbi";
  return "other";
}

export function mapSourceLabel(sourceType: string, kind: DhSourceKind): string {
  if (kind === "huggingface") return "Hugging Face";
  if (kind === "local") return "Lokaal";
  if (kind === "curated") return "Curated";
  if (kind === "arxiv") return "arXiv";
  if (kind === "ncbi") return "NCBI";
  return sourceType || "—";
}

/**
 * Unknown backend states must NOT become Ready.
 * Distinct `unknown` remains visible / unsafe — never green.
 */
export function mapStatus(status: string): DhStatus {
  const s = status.toLowerCase().trim();
  if (!s) return "unknown";
  if (s === "offline" || s === "cached") return "offline";
  if (s.includes("validat")) return "validating";
  if (
    s === "failed" ||
    s === "error" ||
    s === "interrupted" ||
    s.includes("fail") ||
    s.includes("error")
  ) {
    return "failed";
  }
  if (s === "cancelled" || s === "canceled") return "cancelled";
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
  if (s === "created" || s === "raw") return "created";
  if (s === "archived") return "offline";
  return "unknown";
}

export function statusLabel(status: DhStatus): string {
  if (status === "ready") return "Gereed";
  if (status === "created") return "Aangemaakt";
  if (status === "offline") return "Offline";
  if (status === "validating") return "Valideren";
  if (status === "failed") return "Mislukt";
  if (status === "cancelled") return "Geannuleerd";
  if (status === "unknown") return "UNKNOWN";
  return "Verwerking";
}

/** Combined row status chip — prefers index state when that is the operator signal. */
export function rowStatusLabel(row: DhRow): string {
  if (row.embeddings.kind === "indexed" && row.status === "ready") return "Geïndexeerd";
  if (row.embeddings.kind === "indexing") return "Indexeren";
  if (row.embeddings.kind === "queued") return "Indexeren";
  return statusLabel(row.status);
}

export function mapType(ds: DatasetRecord): string {
  const fmt = (ds.detectedFormat ?? "").toLowerCase();
  if (fmt.includes("csv") || fmt.includes("tsv") || fmt.includes("parquet")) return "Tabel";
  if (fmt.includes("json")) return "JSON";
  if (fmt.includes("pdf") || fmt.includes("md") || fmt.includes("doc")) return "Documenten";
  if (fmt.includes("code") || fmt.includes("py") || fmt.includes("js")) return "Code";
  if (fmt.includes("image") || fmt.includes("png") || fmt.includes("jpg")) return "Afbeeldingen";
  if (fmt.includes("multi")) return "Multimodal";
  if (fmt) return "Tekst";
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const task = String(meta?.taskType ?? meta?.type ?? "").toLowerCase();
  if (task.includes("struct") || task.includes("table")) return "Tabel";
  if (task.includes("code")) return "Code";
  if (task.includes("doc")) return "Documenten";
  if (task.includes("image")) return "Afbeeldingen";
  return "Tekst";
}

export function embeddingsForDataset(ds: DatasetRecord, jobs: DatasetJob[]): DhEmbedding {
  const related = jobs.filter((j) => j.datasetId === ds.datasetId);
  const indexing = related.find((j) => {
    const t = j.jobType.toLowerCase();
    const s = j.status.toLowerCase();
    return t.includes("index") && (s === "running" || s === "queued" || s === "pending");
  });
  if (indexing) {
    if (indexing.status.toLowerCase() === "queued" || indexing.status.toLowerCase() === "pending") {
      return { kind: "queued" };
    }
    if (indexing.progress == null) {
      // Measured progress unavailable — do not invent a percentage.
      return { kind: "indexing", pct: -1 };
    }
    return {
      kind: "indexing",
      pct: Math.round(Math.min(1, Math.max(0, indexing.progress)) * 100),
    };
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

export function formatRate(bytesPerSecond: number | null | undefined): string | null {
  if (bytesPerSecond == null || !Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return null;
  if (bytesPerSecond >= 1024 ** 3) return `${(bytesPerSecond / 1024 ** 3).toFixed(2)} GB/s`;
  if (bytesPerSecond >= 1024 ** 2) return `${(bytesPerSecond / 1024 ** 2).toFixed(1)} MB/s`;
  if (bytesPerSecond >= 1024) return `${(bytesPerSecond / 1024).toFixed(0)} KB/s`;
  return `${Math.round(bytesPerSecond)} B/s`;
}

export function formatEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function phaseLabel(phase: string | null | undefined): string {
  const p = (phase || "").toLowerCase();
  if (!p) return "Processing";
  if (p.includes("discover")) return "Discovering repository";
  if (p.includes("plan")) return "Planning download";
  if (p === "rate_limited" || p.includes("rate_limit")) return "Rate limited / retrying";
  if (p.includes("download")) return "Downloading";
  if (p.includes("material")) return "Materializing";
  if (p.includes("validat")) return "Validating";
  if (p.includes("final")) return "Finalizing";
  if (p === "done" || p === "completed") return "Ready";
  if (p.includes("fail")) return "Failed";
  if (p.includes("cancel")) return "Cancelled";
  return phase || "Processing";
}

export function jobProgressDetail(job: DatasetJob | undefined): string | null {
  if (!job) return null;
  const cp = (job.checkpoint || {}) as Record<string, unknown>;
  const phase = phaseLabel(job.phase);
  const filesTotal = typeof cp.filesTotal === "number" ? cp.filesTotal : null;
  const filesCompleted = typeof cp.filesCompleted === "number" ? cp.filesCompleted : null;
  const bytesTotal = typeof cp.bytesTotal === "number" ? cp.bytesTotal : null;
  const bytesDownloaded = typeof cp.bytesDownloaded === "number" ? cp.bytesDownloaded : null;
  const bps = typeof cp.bytesPerSecond === "number" ? cp.bytesPerSecond : null;
  const eta = typeof cp.etaSeconds === "number" ? cp.etaSeconds : null;
  const pct =
    job.progress == null
      ? null
      : Math.round(Math.min(1, Math.max(0, job.progress)) * 1000) / 10;

  const parts: string[] = [phase];
  if (pct != null) parts[0] = `${phase} · ${pct}%`;
  const backendRaw =
    job.backend ||
    (typeof job.compute?.backend === "string" ? job.compute.backend : null) ||
    (typeof job.result?.backend === "string" ? (job.result.backend as string) : null);
  const bn = (backendRaw || "").toLowerCase().replace(/-/g, "_");
  if (bn === "rust_native" || backendRaw === "RUST_NATIVE") parts.push("Rust Native");
  else if (bn === "python_streaming" || backendRaw === "PYTHON_STREAMING") parts.push("Python Streaming");
  const recordsProcessed =
    typeof job.recordsProcessed === "number"
      ? job.recordsProcessed
      : typeof job.compute?.recordsProcessed === "number"
        ? job.compute.recordsProcessed
        : typeof job.result?.recordsProcessed === "number"
          ? (job.result.recordsProcessed as number)
          : null;
  if (recordsProcessed != null) parts.push(`${recordsProcessed.toLocaleString()} records`);
  const peak = job.peakMemory ?? job.peakRssBytes ?? job.compute?.peakMemory ?? null;
  if (backendRaw) {
    parts.push(
      peak == null || peak === "UNMEASURED" || (typeof peak === "number" && !Number.isFinite(peak))
        ? "RSS UNMEASURED"
        : typeof peak === "number"
          ? `RSS ${formatBytes(peak)}`
          : `RSS ${String(peak)}`,
    );
  }
  if (filesTotal != null && filesCompleted != null) {
    parts.push(`${filesCompleted} / ${filesTotal} files`);
  }
  if (bytesDownloaded != null) {
    parts.push(
      bytesTotal != null
        ? `${formatBytes(bytesDownloaded)} / ${formatBytes(bytesTotal)}`
        : `${formatBytes(bytesDownloaded)} downloaded (total unknown)`,
    );
  }
  const rate = formatRate(bps);
  if (rate) parts.push(rate);
  const etaLabel = formatEta(eta);
  if (etaLabel) parts.push(`ETA ${etaLabel}`);
  return parts.join(" · ");
}

export function recordToRow(ds: DatasetRecord, jobs: DatasetJob[]): DhRow {
  const sourceKind = mapSourceKind(ds.sourceType);
  const related = jobs.filter((j) => j.datasetId === ds.datasetId);
  const activeJob = related.find((j) => {
    const s = j.status.toLowerCase();
    return s === "running" || s === "queued" || s === "pending";
  });
  const latestJob = related[0];
  // Prefer live job status when this dataset has an active job.
  let status = mapStatus(ds.status);
  if (activeJob) status = "processing";
  const detail =
    status === "processing" || status === "validating"
      ? jobProgressDetail(activeJob || latestJob)
      : status === "failed"
        ? jobProgressDetail(latestJob) || latestJob?.error || null
        : null;
  const seenTags = new Set<string>();
  const tags: string[] = [];
  for (const raw of [
    ...(ds.semanticTags ?? []),
    ...((ds.metadata as { tags?: string[] } | undefined)?.tags ?? []),
  ]) {
    const tag = String(raw || "").trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seenTags.has(key)) continue;
    seenTags.add(key);
    tags.push(tag);
  }
  return {
    id: ds.datasetId,
    name: ds.displayName || ds.semanticProfile?.displayName || ds.name,
    description: detail || ds.description || ds.originalFilename || ds.datasetId,
    source: mapSourceLabel(ds.sourceType, sourceKind),
    sourceKind,
    type: mapType(ds),
    size: formatBytes(ds.byteSize),
    records: formatCompactCount(ds.rowCount),
    status,
    embeddings: embeddingsForDataset(ds, jobs),
    updated: relativeTime(ds.updatedAt),
    tags: tags.length ? tags : undefined,
    live: true,
    byteSize: ds.byteSize,
    rowCount: ds.rowCount,
    updatedAt: ds.updatedAt,
  };
}

export function sourceGlyph(kind: DhSourceKind): string {
  if (kind === "huggingface") return "HF";
  if (kind === "arxiv") return "χ";
  if (kind === "ncbi") return "N";
  if (kind === "local") return "L";
  if (kind === "curated") return "C";
  return "•";
}

export function filterIcon(icon: string): string {
  if (icon === "grid") return "▦";
  if (icon === "folder") return "▤";
  if (icon === "external") return "⧉";
  if (icon === "indexed") return "◎";
  if (icon === "pending") return "○";
  if (icon === "hf") return "HF";
  if (icon === "shield") return "⛨";
  if (icon === "offline") return "⊘";
  if (icon === "pulse") return "∿";
  return "•";
}

/** Measured progress only — null when backend did not report progress. */
export function measuredProgressPct(job: DatasetJob | undefined): number | null {
  if (!job || job.progress == null) return null;
  return Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
}
