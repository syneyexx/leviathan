import type { IngestionModel, IngestionRowModel } from "../types/backend";

export function mapIngestion(payload: Record<string, unknown> | null, unavailable = false): IngestionModel {
  if (!payload) {
    return {
      queued: null,
      processing: null,
      completed: null,
      failed: null,
      overallProgressPct: null,
      jobs: [],
      unavailable,
    };
  }
  const counts = (payload.counts || {}) as Record<string, unknown>;
  const jobs = Array.isArray(payload.jobs) ? payload.jobs.map((job) => mapJob(job as Record<string, unknown>)) : [];
  return {
    queued: num(counts.queued),
    processing: num(counts.processing),
    completed: num(counts.completed),
    failed: num(counts.failed),
    overallProgressPct: num(payload.overallProgressPct),
    jobs,
    unavailable,
  };
}

function mapJob(job: Record<string, unknown>): IngestionRowModel {
  const progress = num(job.progressPct);
  const throughput = num(job.throughput);
  const elapsed = num(job.elapsedSeconds);
  return {
    id: String(job.id || job.jobId || "UNMEASURED"),
    source: String(job.source || "—"),
    type: String(job.type || "—"),
    state: String(job.state || job.phase || "UNMEASURED"),
    progressPct: progress,
    throughput: throughput == null ? "UNMEASURED" : `${throughput}`,
    elapsed: elapsed == null ? "UNMEASURED" : `${Math.round(elapsed)}s`,
    worker: job.worker ? String(job.worker) : "—",
    error: job.error ? String(job.error) : null,
  };
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function ingestionActive(model: IngestionModel): boolean {
  return (model.processing ?? 0) > 0 || (model.queued ?? 0) > 0;
}
