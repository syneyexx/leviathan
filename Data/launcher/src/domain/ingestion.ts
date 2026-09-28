import type { IngestionModel, IngestionRowModel } from "../types/backend";

const PHASE_PROGRESS: Record<string, number> = {
  queued: 0,
  uploading: 3,
  stored: 6,
  inspecting: 14,
  expanding: 24,
  classifying: 34,
  parsing: 58,
  normalizing: 72,
  brain_pending: 82,
  brain_syncing: 92,
  completed: 100,
  skipped: 100,
};

const ACTIVE_TOKENS = new Set([
  "queued",
  "running",
  "claimed",
  "uploading",
  "stored",
  "inspecting",
  "expanding",
  "classifying",
  "parsing",
  "normalizing",
  "brain_pending",
  "brain_syncing",
]);

function clampPct(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value * 100) / 100));
}

function phaseEstimate(job: Record<string, unknown>): number | null {
  const candidates = [job.phase, job.state]
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim().toLowerCase());
  for (const token of candidates) {
    if (Object.prototype.hasOwnProperty.call(PHASE_PROGRESS, token)) return PHASE_PROGRESS[token];
  }
  return null;
}

function isActive(job: Record<string, unknown>): boolean {
  return [job.phase, job.state]
    .filter((value): value is string => typeof value === "string")
    .some((value) => ACTIVE_TOKENS.has(value.trim().toLowerCase()));
}

export function mapIngestion(payload: Record<string, unknown> | null, unavailable = false): IngestionModel {
  if (!payload) {
    return {
      queued: null,
      processing: null,
      completed: null,
      failed: null,
      overallProgressPct: null,
      overallProgressEstimated: false,
      jobs: [],
      unavailable,
    };
  }
  const counts = (payload.counts || {}) as Record<string, unknown>;
  const rawJobs = Array.isArray(payload.jobs)
    ? payload.jobs.filter((job): job is Record<string, unknown> => Boolean(job) && typeof job === "object")
    : [];
  const jobs = rawJobs.map((job) => mapJob(job));
  const measuredOverall = num(payload.overallProgressPct);

  let overallProgressPct = measuredOverall == null ? null : clampPct(measuredOverall);
  let overallProgressEstimated = Boolean(payload.overallProgressEstimated) && overallProgressPct != null;

  if (overallProgressPct == null) {
    const activeProgress = rawJobs
      .map((raw, index) => ({ raw, row: jobs[index] }))
      .filter(({ raw }) => isActive(raw))
      .map(({ row }) => row.progressPct)
      .filter((value): value is number => value != null);
    if (activeProgress.length) {
      overallProgressPct = clampPct(
        activeProgress.reduce((sum, value) => sum + value, 0) / activeProgress.length,
      );
      overallProgressEstimated = true;
    } else if (
      num(counts.completed) != null &&
      (num(counts.completed) ?? 0) > 0 &&
      (num(counts.queued) ?? 0) === 0 &&
      (num(counts.processing) ?? 0) === 0 &&
      (num(counts.failed) ?? 0) === 0
    ) {
      overallProgressPct = 100;
      overallProgressEstimated = false;
    }
  }

  return {
    queued: num(counts.queued),
    processing: num(counts.processing),
    completed: num(counts.completed),
    failed: num(counts.failed),
    overallProgressPct,
    overallProgressEstimated,
    jobs,
    unavailable,
  };
}

function mapJob(job: Record<string, unknown>): IngestionRowModel {
  const measuredProgress = num(job.progressPct);
  const estimate = measuredProgress == null ? phaseEstimate(job) : null;
  const progress = measuredProgress ?? estimate;
  const throughput = num(job.throughput);
  const elapsed = num(job.elapsedSeconds);
  const upstreamEstimated = Boolean(job.progressEstimated);
  return {
    id: String(job.id || job.jobId || "UNMEASURED"),
    source: String(job.source || "—"),
    type: String(job.type || "—"),
    state: String(job.state || job.phase || "UNMEASURED"),
    progressPct: progress == null ? null : clampPct(progress),
    progressEstimated: progress != null && (estimate != null || upstreamEstimated),
    progressSource:
      progress == null
        ? "unmeasured"
        : estimate != null || upstreamEstimated
          ? "phase_estimate"
          : "measured",
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
