/**
 * Research async op contracts — distinguish accepted/queued from completed.
 * Used by plan / run / probe / url-fetch / report regenerate frontend handlers.
 */

import type { JobState } from "./executionFabric";
import { ACTIVE_JOB_STATES, TERMINAL_JOB_STATES } from "./executionFabric";
import type {
  ResearchPlan,
  ResearchProject,
  ResearchReport,
  ResearchSource,
  ResearchWebProbe,
} from "../types/api";

/** Lifecycle for a web probe job from the UI's perspective. */
export type WebProbePhase = "idle" | "queued" | "running" | "completed" | "failed";

export type WebProbeExecutionState = {
  phase: WebProbePhase;
  jobId: string | null;
  probe: ResearchWebProbe | null;
  error: string | null;
  /** True only after a terminal completed probe result (not mere queue accept). */
  measuredReachability: boolean;
};

export function idleWebProbeState(): WebProbeExecutionState {
  return {
    phase: "idle",
    jobId: null,
    probe: null,
    error: null,
    measuredReachability: false,
  };
}

export type ResearchAsyncOutcome = "queued" | "completed";

export type ResearchQueuedEnvelope = {
  outcome: "queued";
  queued: true;
  status: string;
  job_id?: string | null;
  job?: Record<string, unknown> | null;
  truth?: Record<string, unknown>;
};

export type ResearchPlanQueued = ResearchQueuedEnvelope & {
  project?: ResearchProject;
  plan?: ResearchPlan | null;
};

export type ResearchPlanCompleted = {
  outcome: "completed";
  queued?: false;
  project: ResearchProject;
  plan: ResearchPlan | null;
  status?: string;
  truth?: Record<string, unknown>;
};

export type ResearchPlanResponse = ResearchPlanQueued | ResearchPlanCompleted;

export type ResearchRunQueued = ResearchQueuedEnvelope & {
  project: ResearchProject;
};

export type ResearchRunCompleted = {
  outcome: "completed";
  queued?: false;
  project: ResearchProject;
};

export type ResearchRunResponse = ResearchRunQueued | ResearchRunCompleted;

export type ResearchProbeQueued = ResearchQueuedEnvelope & {
  probe: ResearchWebProbe;
};

export type ResearchProbeCompleted = {
  outcome: "completed";
  queued?: false;
  probe: ResearchWebProbe;
  truth?: Record<string, unknown>;
};

export type ResearchProbeResponse = ResearchProbeQueued | ResearchProbeCompleted;

export type ResearchUrlQueued = ResearchQueuedEnvelope & {
  source: ResearchSource;
};

export type ResearchUrlCompleted = {
  outcome: "completed";
  queued?: false;
  source: ResearchSource;
  status?: string;
  truth?: Record<string, unknown>;
};

export type ResearchUrlResponse = ResearchUrlQueued | ResearchUrlCompleted;

export type ResearchReportQueued = ResearchQueuedEnvelope & {
  project_id?: string;
  report?: ResearchReport | null;
};

export type ResearchReportCompleted = {
  outcome: "completed";
  queued?: false;
  report: ResearchReport;
};

export type ResearchReportResponse = ResearchReportQueued | ResearchReportCompleted;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

export function isQueuedFlag(payload: unknown): boolean {
  const row = asRecord(payload);
  if (!row) return false;
  if (row.queued === true) return true;
  const status = String(row.status ?? "").toUpperCase();
  if (status === "QUEUED" || status === "ACCEPTED" || status === "PENDING") {
    // Only treat as queue accept when there is no completed artifact payload
    // that would indicate inline completion alongside a status field.
    if (row.probe && typeof row.probe === "object") {
      const probeStatus = String((row.probe as ResearchWebProbe).status ?? "").toUpperCase();
      if (probeStatus === "QUEUED" || probeStatus === "RUNNING") return true;
    }
    if (row.job_id || row.job) return true;
  }
  const probe = asRecord(row.probe);
  if (probe) {
    const probeStatus = String(probe.status ?? "").toUpperCase();
    if (probeStatus === "QUEUED" || probeStatus === "RUNNING") return true;
  }
  return false;
}

export function classifyResearchAsync<T extends Record<string, unknown>>(
  payload: T,
): ResearchAsyncOutcome {
  return isQueuedFlag(payload) ? "queued" : "completed";
}

export function normalizePlanResponse(raw: Record<string, unknown>): ResearchPlanResponse {
  if (isQueuedFlag(raw)) {
    return {
      outcome: "queued",
      queued: true,
      status: String(raw.status ?? "QUEUED"),
      job_id: (raw.job_id as string | null | undefined) ?? null,
      job: (raw.job as Record<string, unknown> | null | undefined) ?? null,
      project: raw.project as ResearchProject | undefined,
      plan: (raw.plan as ResearchPlan | null | undefined) ?? null,
      truth: raw.truth as Record<string, unknown> | undefined,
    };
  }
  return {
    outcome: "completed",
    queued: false,
    project: raw.project as ResearchProject,
    plan: (raw.plan as ResearchPlan | null | undefined) ?? null,
    status: raw.status as string | undefined,
    truth: raw.truth as Record<string, unknown> | undefined,
  };
}

export function normalizeProbeResponse(raw: Record<string, unknown>): ResearchProbeResponse {
  const probe = (raw.probe as ResearchWebProbe) ?? {
    status: isQueuedFlag(raw) ? "QUEUED" : "UNKNOWN",
  };
  if (isQueuedFlag(raw)) {
    return {
      outcome: "queued",
      queued: true,
      status: String(raw.status ?? probe.status ?? "QUEUED"),
      job_id: (raw.job_id as string | null | undefined) ?? null,
      job: (raw.job as Record<string, unknown> | null | undefined) ?? null,
      probe: { ...probe, status: probe.status || "QUEUED" },
      truth: raw.truth as Record<string, unknown> | undefined,
    };
  }
  return {
    outcome: "completed",
    queued: false,
    probe,
    truth: raw.truth as Record<string, unknown> | undefined,
  };
}

export function normalizeUrlResponse(raw: Record<string, unknown>): ResearchUrlResponse {
  if (isQueuedFlag(raw)) {
    return {
      outcome: "queued",
      queued: true,
      status: String(raw.status ?? "PENDING"),
      job_id: (raw.job_id as string | null | undefined) ?? null,
      job: (raw.job as Record<string, unknown> | null | undefined) ?? null,
      source: raw.source as ResearchSource,
      truth: raw.truth as Record<string, unknown> | undefined,
    };
  }
  return {
    outcome: "completed",
    queued: false,
    source: raw.source as ResearchSource,
    status: raw.status as string | undefined,
    truth: raw.truth as Record<string, unknown> | undefined,
  };
}

export function normalizeReportResponse(raw: Record<string, unknown>): ResearchReportResponse {
  if (isQueuedFlag(raw)) {
    return {
      outcome: "queued",
      queued: true,
      status: String(raw.status ?? "QUEUED"),
      job_id: (raw.job_id as string | null | undefined) ?? null,
      job: (raw.job as Record<string, unknown> | null | undefined) ?? null,
      project_id: raw.project_id as string | undefined,
      report: (raw.report as ResearchReport | null | undefined) ?? null,
      truth: raw.truth as Record<string, unknown> | undefined,
    };
  }
  return {
    outcome: "completed",
    queued: false,
    report: raw.report as ResearchReport,
  };
}

export function normalizeRunResponse(project: ResearchProject): ResearchRunResponse {
  const status = String(project.status || "").toLowerCase();
  if (status === "queued") {
    return {
      outcome: "queued",
      queued: true,
      status: "QUEUED",
      project,
    };
  }
  // Active researching is also an accepted handoff, but project already left queue.
  if (status === "researching" || status === "synthesizing" || status === "verifying") {
    return { outcome: "completed", queued: false, project };
  }
  return { outcome: "completed", queued: false, project };
}

/** Probe toast / measured-update policy. */
export function probeStatusNorm(status: string | null | undefined): string {
  return String(status || "").trim().toUpperCase();
}

export function isProbeTerminalSuccess(status: string | null | undefined): boolean {
  const s = probeStatusNorm(status);
  return s === "OK" || s === "DEGRADED";
}

export function isProbeTerminalFailure(status: string | null | undefined): boolean {
  const s = probeStatusNorm(status);
  return s === "FAILED" || s === "UNAVAILABLE" || s === "ERROR";
}

export function isProbeInFlight(status: string | null | undefined): boolean {
  const s = probeStatusNorm(status);
  return s === "QUEUED" || s === "RUNNING" || s === "ACCEPTED" || s === "PENDING";
}

/**
 * Toast copy for probe accept/complete. Never says "finished" for queued accepts.
 */
export function probeToastMessage(
  outcome: ResearchAsyncOutcome,
  probe: ResearchWebProbe | null | undefined,
): string {
  if (outcome === "queued") return "Web probe queued";
  const status = probeStatusNorm(probe?.status);
  if (status === "OK") return "Web research probe OK";
  if (status === "DEGRADED") return probe?.error || "Web probe degraded";
  if (status === "FAILED" || status === "UNAVAILABLE" || status === "ERROR") {
    return probe?.error || `Web probe ${status.toLowerCase()}`;
  }
  if (isProbeInFlight(status)) return "Web probe queued";
  return probe?.error || `Web probe ${status || "completed"}`;
}

export function applyProbeAccept(
  prev: WebProbeExecutionState,
  response: ResearchProbeResponse,
): WebProbeExecutionState {
  if (response.outcome === "queued") {
    const jobId =
      response.job_id ||
      (typeof response.job?.job_id === "string" ? response.job.job_id : null) ||
      (typeof response.job?.jobId === "string" ? response.job.jobId : null) ||
      null;
    return {
      phase: "queued",
      jobId,
      probe: response.probe,
      error: null,
      measuredReachability: false,
    };
  }
  const status = probeStatusNorm(response.probe.status);
  if (isProbeTerminalFailure(status)) {
    return {
      phase: "failed",
      jobId: prev.jobId,
      probe: response.probe,
      error: response.probe.error || status,
      measuredReachability: true,
    };
  }
  return {
    phase: "completed",
    jobId: prev.jobId,
    probe: response.probe,
    error: null,
    measuredReachability: true,
  };
}

export function jobStateFromRecord(job: Record<string, unknown> | null | undefined): JobState | string {
  if (!job) return "UNKNOWN";
  const raw = String(job.state ?? job.status ?? "UNKNOWN").toUpperCase();
  return raw;
}

export function mapJobStateToProbePhase(state: string): WebProbePhase {
  const s = state.toUpperCase();
  if (s === "QUEUED" || s === "CREATED" || s === "RETRY_WAIT") return "queued";
  if (s === "RUNNING" || s === "CANCEL_REQUESTED") return "running";
  if (s === "COMPLETED") return "completed";
  if (s === "FAILED" || s === "CANCELLED") return "failed";
  return "running";
}

export function shouldRefreshMeasuredReachability(phase: WebProbePhase): boolean {
  return phase === "completed" || phase === "failed";
}

/** Polling race helpers (R-014). */
export type PollController = {
  generation: number;
  inFlight: boolean;
  aborted: boolean;
};

export function createPollController(): PollController {
  return { generation: 0, inFlight: false, aborted: false };
}

export function beginPollGeneration(ctrl: PollController): number {
  ctrl.generation += 1;
  ctrl.aborted = false;
  return ctrl.generation;
}

export function abortPoll(ctrl: PollController): void {
  ctrl.aborted = true;
  ctrl.generation += 1;
}

export function canStartPollTick(ctrl: PollController, generation: number): boolean {
  if (ctrl.aborted) return false;
  if (generation !== ctrl.generation) return false;
  if (ctrl.inFlight) return false;
  return true;
}

export function markPollStarted(ctrl: PollController): void {
  ctrl.inFlight = true;
}

export function markPollFinished(ctrl: PollController): void {
  ctrl.inFlight = false;
}

export function isPollResultCurrent(ctrl: PollController, generation: number): boolean {
  return !ctrl.aborted && generation === ctrl.generation;
}

/** Research project terminal / immutable statuses — stop active polling. */
export const RESEARCH_TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export function isResearchTerminalStatus(status: string | null | undefined): boolean {
  return RESEARCH_TERMINAL_STATUSES.has(String(status || "").toLowerCase());
}

export function isJobTerminal(state: string | null | undefined): boolean {
  const s = String(state || "").toUpperCase() as JobState;
  return TERMINAL_JOB_STATES.has(s);
}

export function isJobActive(state: string | null | undefined): boolean {
  const s = String(state || "").toUpperCase() as JobState;
  return ACTIVE_JOB_STATES.has(s) || s === "CREATED";
}

/** Hidden-tab poll interval multiplier / pause policy. */
export const HIDDEN_POLL_PAUSE = true;
export const HIDDEN_POLL_MS_FACTOR = 4;

export function effectivePollMs(baseMs: number, visible: boolean): number {
  if (visible) return baseMs;
  if (HIDDEN_POLL_PAUSE) return Number.POSITIVE_INFINITY; // caller should skip
  return baseMs * HIDDEN_POLL_MS_FACTOR;
}

export function shouldSkipPollForVisibility(visible: boolean): boolean {
  return HIDDEN_POLL_PAUSE && !visible;
}
