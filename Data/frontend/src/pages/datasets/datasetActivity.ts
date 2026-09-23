/**
 * Dataset Activity view-model helpers.
 *
 * Pure derivation from durable DatasetJob payloads — not a second job store.
 */

import type {
  DatasetActivityEntry,
  DatasetActivityLevel,
  DatasetJob,
  DatasetJobDownloadSummary,
} from "../../types/api";

export type ActivityFilter = "all" | "active" | "errors" | "completed";

const ACTIVE_STATUSES = new Set(["queued", "pending", "running"]);
const COMPLETED_STATUSES = new Set(["completed", "succeeded", "done"]);
const ERROR_STATUSES = new Set(["failed", "interrupted"]);
const CANCELLED_STATUSES = new Set(["cancelled", "canceled"]);

const SECRET_PATTERNS = [
  /hf_[A-Za-z0-9]{10,}/g,
  /Bearer\s+[A-Za-z0-9._\-+=/]+/gi,
  /Authorization:\s*[^\s]+/gi,
  /(token|secret|password|api[_-]?key)\s*[:=]\s*["']?[^\s"',}]+/gi,
];

export function redactActivityText(text: string): string {
  let out = text;
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, "[REDACTED]");
  }
  return out;
}

export function isActiveJob(job: DatasetJob): boolean {
  return ACTIVE_STATUSES.has(job.status.toLowerCase());
}

export function isCompletedJob(job: DatasetJob): boolean {
  return COMPLETED_STATUSES.has(job.status.toLowerCase());
}

export function isErrorJob(job: DatasetJob): boolean {
  return ERROR_STATUSES.has(job.status.toLowerCase());
}

export function isCancelledJob(job: DatasetJob): boolean {
  return CANCELLED_STATUSES.has(job.status.toLowerCase());
}

export function jobTypeLabel(jobType: string): string {
  const t = jobType.toLowerCase();
  if (t === "import_hf") return "Hugging Face Import";
  if (t === "import_local") return "Local Import";
  if (t === "materialize") return "Materialize";
  if (t === "validate") return "Validate";
  if (t === "dedupe") return "Deduplicate";
  if (t === "transform") return "Transform";
  if (t === "split") return "Split";
  if (t === "tokenize_stats") return "Tokenize Stats";
  if (t === "export") return "Export";
  if (t === "index") return "Index";
  if (t === "duplicate") return "Duplicate";
  if (t === "shard_ingest") return "Shard Ingest";
  if (t === "contamination_scan") return "Contamination Scan";
  if (t.includes("offline") && t.includes("index")) return "Offline Brain Index";
  return jobType.replace(/_/g, " ");
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  return new Date(t).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function downloadSummary(job: DatasetJob): DatasetJobDownloadSummary | null {
  if (job.download) return job.download;
  const cp = job.checkpoint;
  const cfg = job.config ?? {};
  if (!cp && job.jobType !== "import_hf") return null;
  const fileCp = (cp?.file && typeof cp.file === "object" ? cp.file : null) as DatasetJob["checkpoint"];
  const manifest = (cp?.manifestSummary && typeof cp.manifestSummary === "object"
    ? cp.manifestSummary
    : {}) as Record<string, unknown>;

  const asNum = (v: unknown): number | null => {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
    return null;
  };

  const filename =
    (cp?.filename as string | undefined) ??
    (cp?.relativePath as string | undefined) ??
    (fileCp?.filename as string | undefined) ??
    (cfg.filename as string | undefined) ??
    null;

  const bytesDownloaded =
    asNum(cp?.bytesDownloaded) ?? asNum(fileCp?.bytesDownloaded) ?? asNum(manifest.bytesDownloaded);
  const bytesTotal =
    asNum(cp?.bytesTotal) ??
    asNum(cp?.totalBytes) ??
    asNum(fileCp?.totalBytes) ??
    asNum(fileCp?.bytesTotal) ??
    asNum(manifest.bytesTotal);

  let filesTotal = asNum(cp?.filesTotal) ?? asNum(manifest.filesTotal);
  let filesCompleted = asNum(cp?.filesCompleted) ?? asNum(manifest.filesCompleted);
  if (filesTotal == null && filename) {
    filesTotal = 1;
    filesCompleted =
      bytesDownloaded != null && bytesTotal != null && bytesTotal > 0
        ? bytesDownloaded >= bytesTotal
          ? 1
          : 0
        : null;
  }

  return {
    repositoryId:
      (cp?.repositoryId as string | undefined) ??
      (fileCp?.repositoryId as string | undefined) ??
      (cfg.repositoryId as string | undefined) ??
      null,
    revision:
      (cp?.revision as string | undefined) ??
      (fileCp?.revision as string | undefined) ??
      (cfg.revision as string | undefined) ??
      null,
    filename,
    bytesDownloaded,
    bytesTotal,
    filesTotal,
    filesCompleted,
    attempts: asNum(cp?.attempts) ?? asNum(fileCp?.attempts),
    lastHttpStatus:
      asNum(cp?.lastHttpStatus) ?? asNum(cp?.lastStatus) ?? asNum(fileCp?.lastStatus),
    rateLimitEvents: asNum(cp?.rateLimitEvents) ?? asNum(fileCp?.rateLimitEvents),
    etag: (cp?.etag as string | null | undefined) ?? (fileCp?.etag as string | null | undefined) ?? null,
    bytesPerSecond: asNum(cp?.bytesPerSecond),
    etaSeconds: asNum(cp?.etaSeconds),
  };
}

export function progressRatio(job: DatasetJob): number | null {
  const dl = downloadSummary(job);
  if (dl?.bytesDownloaded != null && dl.bytesTotal != null && dl.bytesTotal > 0) {
    return Math.min(1, Math.max(0, dl.bytesDownloaded / dl.bytesTotal));
  }
  if (
    dl?.filesCompleted != null &&
    dl.filesTotal != null &&
    dl.filesTotal > 0 &&
    // Avoid a fake 0% bar for single-file downloads with unknown byte totals.
    !(dl.filesTotal === 1 && dl.filesCompleted === 0 && dl.bytesTotal == null && isActiveJob(job))
  ) {
    return Math.min(1, Math.max(0, dl.filesCompleted / dl.filesTotal));
  }
  if (typeof job.progress === "number" && Number.isFinite(job.progress) && job.progress >= 0) {
    if (isCompletedJob(job)) return 1;
    if (dl?.bytesTotal != null && dl.bytesTotal > 0) {
      return Math.min(1, Math.max(0, job.progress));
    }
  }
  if (isCompletedJob(job)) return 1;
  return null;
}

export type TransferSample = {
  atMs: number;
  bytes: number;
};

/** Rolling observed transfer rate (bytes/sec) from recent samples. */
export function observedTransferRate(samples: TransferSample[], windowMs = 8000): number | null {
  if (samples.length < 2) return null;
  const latest = samples[samples.length - 1];
  const cutoff = latest.atMs - windowMs;
  const windowed = samples.filter((s) => s.atMs >= cutoff);
  if (windowed.length < 2) return null;
  const first = windowed[0];
  const last = windowed[windowed.length - 1];
  const dt = (last.atMs - first.atMs) / 1000;
  if (dt <= 0) return null;
  const db = last.bytes - first.bytes;
  if (db < 0) return null;
  return db / dt;
}

export function formatRate(bytesPerSec: number | null | undefined): string | null {
  if (bytesPerSec == null || !Number.isFinite(bytesPerSec) || bytesPerSec <= 0) return null;
  return `${formatBytes(bytesPerSec)}/s`;
}

export function estimatedRemainingSeconds(
  bytesDownloaded: number | null | undefined,
  bytesTotal: number | null | undefined,
  bytesPerSec: number | null | undefined,
): number | null {
  if (
    bytesDownloaded == null ||
    bytesTotal == null ||
    bytesPerSec == null ||
    !Number.isFinite(bytesDownloaded) ||
    !Number.isFinite(bytesTotal) ||
    !Number.isFinite(bytesPerSec) ||
    bytesTotal <= bytesDownloaded ||
    bytesPerSec < 32 * 1024
  ) {
    return null;
  }
  return (bytesTotal - bytesDownloaded) / bytesPerSec;
}

export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.ceil(seconds % 60);
  if (mins < 60) return `${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}m`;
}

function levelForStatus(status: string): DatasetActivityLevel {
  const s = status.toLowerCase();
  if (COMPLETED_STATUSES.has(s)) return "success";
  if (ERROR_STATUSES.has(s)) return "error";
  if (CANCELLED_STATUSES.has(s)) return "info";
  if (s === "running") return "progress";
  return "info";
}

function entryId(jobId: string, key: string): string {
  return `${jobId}:${key}`;
}

/**
 * Reconstruct a readable activity stream from durable job state.
 * Only reflects fields present on the job — does not invent phases.
 */
export function entriesFromJob(job: DatasetJob, prev?: DatasetJob | null): DatasetActivityEntry[] {
  const entries: DatasetActivityEntry[] = [];
  const label = jobTypeLabel(job.jobType);
  const datasetId = job.datasetId ?? undefined;
  const dl = downloadSummary(job);
  const status = job.status.toLowerCase();
  const phase = (job.phase || "").toLowerCase();

  const push = (partial: Omit<DatasetActivityEntry, "id" | "jobId" | "datasetId"> & { key: string }) => {
    entries.push({
      id: entryId(job.jobId, partial.key),
      jobId: job.jobId,
      datasetId,
      timestamp: partial.timestamp,
      level: partial.level,
      stage: partial.stage,
      message: redactActivityText(partial.message),
      bytesCompleted: partial.bytesCompleted,
      bytesTotal: partial.bytesTotal,
      filesCompleted: partial.filesCompleted,
      filesTotal: partial.filesTotal,
      retryCount: partial.retryCount,
    });
  };

  // Baseline lifecycle from durable timestamps (page reload recovery).
  push({
    key: "queued",
    timestamp: job.createdAt,
    level: "info",
    stage: "QUEUED",
    message: `${label} queued`,
  });

  if (job.startedAt) {
    push({
      key: "started",
      timestamp: job.startedAt,
      level: "progress",
      stage: (job.phase || "STARTING").toUpperCase(),
      message: `${label} started`,
    });
  }

  if (dl?.repositoryId) {
    push({
      key: "repo",
      timestamp: job.startedAt || job.createdAt,
      level: "info",
      stage: "PLAN",
      message: `Repository ${dl.repositoryId}${dl.revision ? `@${dl.revision}` : ""}`,
    });
  }

  if (dl?.filename) {
    const fileMsg =
      dl.bytesDownloaded != null
        ? dl.bytesTotal != null
          ? `DOWNLOAD  ${dl.filename}  ${formatBytes(dl.bytesDownloaded)} / ${formatBytes(dl.bytesTotal)}`
          : `DOWNLOAD  ${dl.filename}  ${formatBytes(dl.bytesDownloaded)} downloaded · total size unknown`
        : `DOWNLOAD  ${dl.filename}`;
    push({
      key: `download:${dl.bytesDownloaded ?? 0}:${dl.bytesTotal ?? "u"}`,
      timestamp: job.updatedAt,
      level: phase === "rate_limited" ? "warning" : "progress",
      stage: "DOWNLOAD",
      message: fileMsg,
      bytesCompleted: dl.bytesDownloaded ?? undefined,
      bytesTotal: dl.bytesTotal ?? undefined,
      filesCompleted: dl.filesCompleted ?? undefined,
      filesTotal: dl.filesTotal ?? undefined,
      retryCount: dl.attempts ?? undefined,
    });
  }

  if ((dl?.rateLimitEvents ?? 0) > 0 || phase === "rate_limited") {
    push({
      key: `retry:${dl?.rateLimitEvents ?? 0}:${dl?.attempts ?? 0}`,
      timestamp: job.updatedAt,
      level: "warning",
      stage: "RETRY",
      message: redactActivityText(
        `Hugging Face returned HTTP ${dl?.lastHttpStatus ?? 429}` +
          (dl?.filename ? ` · retrying ${dl.filename}` : "") +
          (dl?.attempts != null ? ` · attempt ${dl.attempts}` : "") +
          (dl?.rateLimitEvents != null ? ` · rate-limit events ${dl.rateLimitEvents}` : ""),
      ),
      retryCount: dl?.attempts ?? undefined,
    });
  }

  if (phase === "discovering" || phase === "planning") {
    push({
      key: `phase:${phase}`,
      timestamp: job.updatedAt,
      level: "info",
      stage: phase === "discovering" ? "DISCOVERING" : "PLAN",
      message:
        phase === "discovering"
          ? "Repository discovery started"
          : "Repository download plan ready",
    });
  }

  if (phase === "materializing" || phase === "raw_stored") {
    push({
      key: `phase:${phase}`,
      timestamp: job.updatedAt,
      level: "progress",
      stage: phase.toUpperCase(),
      message:
        phase === "materializing"
          ? "Materializing dataset — converting to canonical representation"
          : "Raw file stored — preparing materialization",
    });
  }

  if (phase === "validating") {
    push({
      key: "phase:validating",
      timestamp: job.updatedAt,
      level: "progress",
      stage: "VALIDATING",
      message: "Validating materialized records",
    });
  }

  if (phase && !["downloading", "rate_limited", "materializing", "validating", "raw_stored", "starting", "done", "completed", ""].includes(phase)) {
    push({
      key: `phase:${phase}`,
      timestamp: job.updatedAt,
      level: "info",
      stage: phase.toUpperCase(),
      message: `Phase ${phase}`,
    });
  }

  if (isCompletedJob(job)) {
    push({
      key: "completed",
      timestamp: job.finishedAt || job.updatedAt,
      level: "success",
      stage: "COMPLETED",
      message: `${label} completed`,
    });
  } else if (isErrorJob(job)) {
    const parts = [`${label} failed`];
    if (job.phase) parts.push(`phase ${job.phase}`);
    if (dl?.filename) parts.push(`file ${dl.filename}`);
    if (dl?.lastHttpStatus != null) parts.push(`HTTP ${dl.lastHttpStatus}`);
    if (dl?.attempts != null) parts.push(`retries ${dl.attempts}`);
    if (job.error) parts.push(String(job.error));
    push({
      key: "failed",
      timestamp: job.finishedAt || job.updatedAt,
      level: "error",
      stage: "FAILED",
      message: redactActivityText(parts.join(" · ")),
      retryCount: dl?.attempts ?? undefined,
    });
  } else if (isCancelledJob(job)) {
    push({
      key: "cancelled",
      timestamp: job.finishedAt || job.updatedAt,
      level: "info",
      stage: "CANCELLED",
      message: `${label} cancelled`,
    });
  } else if (!prev && status === "running") {
    push({
      key: `status:${status}:${phase}`,
      timestamp: job.updatedAt,
      level: levelForStatus(status),
      stage: (job.phase || status).toUpperCase(),
      message: `${label} · ${job.phase || status}`,
    });
  }

  // Deduplicate by id while preserving order
  const seen = new Set<string>();
  return entries.filter((e) => {
    if (seen.has(e.id)) return false;
    seen.add(e.id);
    return true;
  });
}

/**
 * Merge job snapshots into a bounded activity log.
 * Coalesces repetitive download progress lines per job.
 */
export function mergeActivityEntries(
  previous: DatasetActivityEntry[],
  jobs: DatasetJob[],
  prevJobsById: Map<string, DatasetJob>,
  maxEntries = 400,
): DatasetActivityEntry[] {
  const byId = new Map<string, DatasetActivityEntry>();
  for (const e of previous) byId.set(e.id, e);

  for (const job of jobs) {
    const derived = entriesFromJob(job, prevJobsById.get(job.jobId) ?? null);
    for (const entry of derived) {
      byId.set(entry.id, entry);
    }
    // Drop superseded download progress keys for this job (keep latest only)
    const downloadKeys = [...byId.keys()].filter((k) => k.startsWith(`${job.jobId}:download:`));
    if (downloadKeys.length > 1) {
      downloadKeys.sort();
      for (const k of downloadKeys.slice(0, -1)) byId.delete(k);
    }
  }

  const merged = [...byId.values()].sort((a, b) => {
    const ta = Date.parse(a.timestamp) || 0;
    const tb = Date.parse(b.timestamp) || 0;
    if (ta !== tb) return ta - tb;
    return a.id.localeCompare(b.id);
  });
  return merged.length > maxEntries ? merged.slice(merged.length - maxEntries) : merged;
}

export function filterEntries(
  entries: DatasetActivityEntry[],
  filter: ActivityFilter,
  jobId: string | "all",
): DatasetActivityEntry[] {
  return entries.filter((e) => {
    if (jobId !== "all" && e.jobId !== jobId) return false;
    if (filter === "all") return true;
    if (filter === "errors") return e.level === "error" || e.level === "warning";
    if (filter === "completed") return e.level === "success" || e.stage === "COMPLETED" || e.stage === "CANCELLED";
    if (filter === "active") {
      return e.level === "progress" || e.stage === "QUEUED" || e.stage === "DOWNLOAD" || e.stage === "RETRY";
    }
    return true;
  });
}

export function pickActiveJob(jobs: DatasetJob[], preferredJobId?: string | null): DatasetJob | null {
  if (preferredJobId) {
    const preferred = jobs.find((j) => j.jobId === preferredJobId);
    if (preferred && isActiveJob(preferred)) return preferred;
  }
  const active = jobs.filter(isActiveJob);
  if (active.length === 0) return null;
  active.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  return active[0] ?? null;
}

export function jobsMateriallyChanged(prev: DatasetJob[], next: DatasetJob[]): boolean {
  if (prev.length !== next.length) return true;
  const prevMap = new Map(prev.map((j) => [j.jobId, j]));
  for (const job of next) {
    const old = prevMap.get(job.jobId);
    if (!old) return true;
    if (
      old.status !== job.status ||
      old.phase !== job.phase ||
      old.progress !== job.progress ||
      old.updatedAt !== job.updatedAt ||
      old.error !== job.error ||
      JSON.stringify(old.checkpoint ?? {}) !== JSON.stringify(job.checkpoint ?? {})
    ) {
      return true;
    }
  }
  return false;
}

export function pollingIntervalMs(opts: {
  hasActive: boolean;
  hasJobs: boolean;
  consecutiveFailures: number;
}): number {
  if (opts.consecutiveFailures > 0) {
    return Math.min(30_000, 2000 * 2 ** Math.min(opts.consecutiveFailures, 4));
  }
  if (opts.hasActive) return 1000;
  if (opts.hasJobs) return 2500;
  return 12_000;
}

export function entriesToPlainText(entries: DatasetActivityEntry[]): string {
  return entries
    .map((e) => {
      const bits = [formatClock(e.timestamp), (e.stage || e.level).padEnd(10), e.message];
      return bits.join("  ");
    })
    .join("\n");
}
