/** Typed contracts for the LEVIATHAN execution fabric (jobs + generic workers). */

export type JobState =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "RETRY_WAIT"
  | "CANCEL_REQUESTED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export const JOB_STATES: readonly JobState[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "RETRY_WAIT",
  "CANCEL_REQUESTED",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;

export const TERMINAL_JOB_STATES: ReadonlySet<JobState> = new Set([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

export const ACTIVE_JOB_STATES: ReadonlySet<JobState> = new Set([
  "QUEUED",
  "RUNNING",
  "RETRY_WAIT",
  "CANCEL_REQUESTED",
]);

export type WorkerInstanceState =
  | "STARTING"
  | "READY"
  | "BUSY"
  | "DRAINING"
  | "STOPPED"
  | "STALE"
  | "CRASHED"
  | "DEGRADED"
  | "INCOMPATIBLE";

export interface WorkerInstance {
  worker_id: string;
  pool_id: string;
  slot: number;
  pid: number;
  process_start_identity: string;
  protocol_version: number;
  implementation_version: string;
  supported_job_kinds: string[];
  host: string;
  started_at: string | null;
  last_heartbeat_at: string | null;
  state: WorkerInstanceState;
  current_job_id: string | null;
  supervisor_generation: string | null;
  restart_count: number;
  degraded_reason: string | null;
  metadata: Record<string, unknown>;
  truth?: {
    pid_alive_is_not_healthy: boolean;
    stale_row_is_not_live_worker: boolean;
  };
}

export interface WorkerPoolStatus {
  pool_id: string;
  entrypoint: string;
  default_count: number;
  job_kinds: string[];
  resource_classes: string[];
  description: string;
  max_count: number;
  desired: number;
  instances?: number;
  ready?: number;
  busy?: number;
  draining?: number;
  degraded?: number | boolean;
  degraded_reason?: string | null;
  starting?: number;
  other?: number;
  owned?: number;
  workers?: WorkerInstance[];
}

/** Wire shape for job progress heartbeats / status streaming. */
export interface ProgressEnvelope {
  job_id: string;
  state: JobState;
  progress: number | null;
  phase: string | null;
  message: string | null;
  updated_at: string;
  attempt_number?: number;
  worker_pool?: string | null;
  lease_owner?: string | null;
}

/** Admission deferral while waiting on RAM/VRAM / exclusive GPU. */
export interface ResourceWait {
  waiting: boolean;
  reason: string;
  resource_class?: string | null;
  reservation_id?: string | null;
  ram_known?: boolean | null;
  vram_known?: boolean | null;
  details?: Record<string, unknown>;
}

export interface JobRecord {
  job_id: string;
  capability_id: string;
  arguments: Record<string, unknown>;
  state: JobState;
  created_at: string;
  updated_at: string;
  run_id: string | null;
  approval_id: string | null;
  requested_by: string;
  result: Record<string, unknown> | null;
  error: string | null;
  metadata: Record<string, unknown>;
  trace_id: string | null;
  idempotency_key: string | null;
  lease_owner: string | null;
  lease_expires_at: string | null;
  last_heartbeat_at: string | null;
  attempt_number: number;
  budget: Record<string, unknown>;
  latency_class: string;
  domain: string | null;
  consumer: string | null;
  correlation_id: string | null;
  root_job_id: string | null;
  parent_job_id: string | null;
  domain_entity_type: string | null;
  domain_entity_id: string | null;
  worker_pool: string | null;
  resource_class: string | null;
  priority: number;
  queued_at: string | null;
  claimed_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  max_attempts: number;
  next_attempt_at: string | null;
  timeout_seconds: number | null;
  deadline_at: string | null;
  cancel_requested_at: string | null;
  cancel_reason: string | null;
  progress: number | null;
  phase: string | null;
  message: string | null;
  resource_request: Record<string, unknown>;
  result_summary: Record<string, unknown> | null;
  artifact_refs: unknown[];
  error_code: string | null;
  retryable: boolean | null;
}

export function parseJobState(raw: string | null | undefined): JobState | null {
  const s = String(raw || "")
    .trim()
    .toUpperCase()
    .replace(/-/g, "_");
  return (JOB_STATES as readonly string[]).includes(s) ? (s as JobState) : null;
}

export function isTerminalJobState(state: JobState | string | null | undefined): boolean {
  const parsed = typeof state === "string" ? parseJobState(state) : state;
  return parsed != null && TERMINAL_JOB_STATES.has(parsed);
}

export function isActiveJobState(state: JobState | string | null | undefined): boolean {
  const parsed = typeof state === "string" ? parseJobState(state) : state;
  return parsed != null && ACTIVE_JOB_STATES.has(parsed);
}

export function progressFromJob(job: Pick<JobRecord, "job_id" | "state" | "progress" | "phase" | "message" | "updated_at" | "attempt_number" | "worker_pool" | "lease_owner">): ProgressEnvelope {
  return {
    job_id: job.job_id,
    state: job.state,
    progress: job.progress,
    phase: job.phase,
    message: job.message,
    updated_at: job.updated_at,
    attempt_number: job.attempt_number,
    worker_pool: job.worker_pool,
    lease_owner: job.lease_owner,
  };
}
