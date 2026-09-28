export type ServiceTone = "ok" | "warn" | "bad" | "muted";

export interface ServiceCardModel {
  id: string;
  name: string;
  state: string;
  detail: string;
  tone: ServiceTone;
}

export interface WorkerRowModel {
  id: string;
  state: string;
  task: string;
  pool: string;
  cpu: string;
  ram: string;
  queue: string;
  heartbeat: string;
}

export interface MetricCardModel {
  id: string;
  label: string;
  value: string;
  unit: string;
  samples: Array<number | null>;
  tone: "cyan" | "green" | "amber" | "violet" | "muted";
  detail?: string;
  chart?: "line" | "bars";
}

export interface LogRowModel {
  id: string;
  time: string;
  level: string;
  module: string;
  message: string;
}

export interface IngestionRowModel {
  id: string;
  source: string;
  type: string;
  state: string;
  progressPct: number | null;
  /** Optional for fixture/backward-compatible models; production mapping always supplies it. */
  progressEstimated?: boolean;
  progressSource?: "measured" | "phase_estimate" | "unmeasured";
  throughput: string;
  elapsed: string;
  worker: string;
  error: string | null;
}

export interface IngestionModel {
  queued: number | null;
  processing: number | null;
  completed: number | null;
  failed: number | null;
  overallProgressPct: number | null;
  /** Optional for fixture/backward-compatible models; production mapping always supplies it. */
  overallProgressEstimated?: boolean;
  jobs: IngestionRowModel[];
  unavailable: boolean;
}

export interface NativeModel {
  status: string;
  version: string;
  binaryPath: string | null;
  operations: string[];
  detail: string;
  recent: Array<{ at: string; message: string; operation: string }>;
  daemon: false;
}

export interface OperatorModel {
  host: import("./host").HostSnapshot;
  services: ServiceCardModel[];
  workers: WorkerRowModel[];
  workerSummary: string;
  metrics: MetricCardModel[];
  logs: LogRowModel[];
  ingestion: IngestionModel;
  native: NativeModel;
  uptime: string;
  servicesOnline: string;
  queue: string;
}
