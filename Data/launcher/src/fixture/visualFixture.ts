import type { OperatorModel } from "../types/backend";
import type { ConsoleLine, HostSnapshot } from "../types/host";
import { stoppedSnapshot } from "../domain/host";
import { metricCards, type MetricHistories } from "../domain/telemetry";

/** Test-only composition for visual regression. Never used when MODE is production. */

function wave(seed: number): number[] {
  return Array.from({ length: 36 }, (_, index) => 18 + Math.sin(index / 2.4 + seed) * 8 + (index % 5));
}

const histories: MetricHistories = {
  queue: wave(1),
  tasks: wave(2),
  completed: wave(3),
  cpu: wave(0.4),
  memory: wave(1.4),
  disk: wave(2.2),
  native: wave(0.8),
  docs: wave(1.7),
  network: wave(2.8),
};

export function fixtureHost(): HostSnapshot {
  return {
    ...stoppedSnapshot(),
    state: "RUNNING",
    ownership: "OWNED",
    pid: 4100,
    message: "Backend health is ready. This host owns the process.",
    apiBase: "http://127.0.0.1:8765",
    frontendUrl: "http://127.0.0.1:8765/",
    version: "0.1.0",
    startedAt: "2026-09-27T21:00:00Z",
    pythonVersion: "3.12.3",
    supervisorHealth: "RUNNING",
    safeModeArmed: false,
    safeModeActive: false,
  };
}

export function fixtureModel(): OperatorModel {
  const host = fixtureHost();
  return {
    host,
    services: [
      { id: "api", name: "API", state: "HEALTHY", detail: "alive", tone: "ok" },
      { id: "workers", name: "Workers", state: "HEALTHY", detail: "supervisor RUNNING", tone: "ok" },
      { id: "native", name: "Native Data Plane", state: "HEALTHY", detail: "protocol 1", tone: "ok" },
      { id: "python", name: "Python Runtime", state: "HEALTHY", detail: "3.12.3", tone: "ok" },
      { id: "control", name: "CONTROL DB", state: "HEALTHY", detail: "42 tables", tone: "ok" },
      { id: "knowledge", name: "KNOWLEDGE DB", state: "HEALTHY", detail: "18 tables", tone: "ok" },
      { id: "market", name: "MARKET DB", state: "HEALTHY", detail: "11 tables", tone: "ok" },
      { id: "model", name: "Model Runtime", state: "HEALTHY", detail: "local provider", tone: "ok" },
      { id: "queue", name: "Queue / Jobs", state: "HEALTHY", detail: "3 queued", tone: "ok" },
    ],
    workers: [
      ["research-0", "BUSY", "classifying batch", "research", "12.4%", "180 MB", "2", "1s"],
      ["coding-0", "READY", "waiting", "coding", "1.1%", "96 MB", "0", "1s"],
      ["source_ingestion-0", "BUSY", "parsing archive", "source_ingestion", "22.0%", "240 MB", "1", "2s"],
      ["dataset-0", "READY", "waiting", "dataset", "UNMEASURED", "UNMEASURED", "0", "4s"],
      ["embeddings-0", "BUSY", "embedding chunk", "embeddings", "31.0%", "410 MB", "3", "1s"],
      ["general-0", "READY", "idle", "general", "0.4%", "80 MB", "0", "3s"],
      ["maintenance-0", "READY", "heartbeat", "maintenance", "UNMEASURED", "64 MB", "0", "6s"],
      ["db_commit-0", "READY", "waiting for commit", "db_commit", "0.2%", "72 MB", "0", "2s"],
    ].map(([id, state, task, pool, cpu, ram, queue, heartbeat]) => ({ id, state, task, pool, cpu, ram, queue, heartbeat })),
    workerSummary: "8 / 8",
    metrics: metricCards(histories, {
      cpu: 34,
      memory: 48,
      queue: 3,
      nativeOps: 12.4,
      docs: 3.2,
      disk: null,
      network: null,
      completed: null,
      tasksPerMin: 18,
    }, 3).map((card, index) => (index === 5 || index === 8 ? { ...card, value: "UNMEASURED", tone: "muted" as const } : card)),
    logs: [
      { id: "1", time: "21:39:01", level: "INFO", module: "bootstrap", message: "API process started" },
      { id: "2", time: "21:39:02", level: "INFO", module: "workers", message: "supervisor lease acquired" },
      { id: "3", time: "21:39:03", level: "INFO", module: "jobs", message: "queue depth observed" },
      { id: "4", time: "21:39:04", level: "WARNING", module: "native", message: "probe returned BUILD_MISSING in a non-fixture run" },
      { id: "5", time: "21:39:05", level: "INFO", module: "sqlite", message: "CONTROL KNOWLEDGE MARKET readable" },
      { id: "6", time: "21:39:06", level: "SUCCESS", module: "host", message: "health ok" },
    ],
    ingestion: {
      queued: 1,
      processing: 1,
      completed: 4,
      failed: 0,
      overallProgressPct: 62,
      unavailable: false,
      jobs: [
        { id: "src-14", source: "archive.zip", type: "zip", state: "parsing", progressPct: 62, throughput: "UNMEASURED", elapsed: "40s", worker: "source_ingestion-0", error: null },
        { id: "src-15", source: "notes.md", type: "markdown", state: "queued", progressPct: 0, throughput: "UNMEASURED", elapsed: "4s", worker: "—", error: null },
        { id: "src-11", source: "manual.pdf", type: "pdf", state: "completed", progressPct: 100, throughput: "UNMEASURED", elapsed: "3m", worker: "source_ingestion-0", error: null },
        { id: "src-09", source: "scan.tiff", type: "image", state: "failed", progressPct: 12, throughput: "UNMEASURED", elapsed: "18s", worker: "source_ingestion-0", error: "extract failed" },
      ],
    },
    native: {
      status: "AVAILABLE",
      version: "protocol 1",
      binaryPath: "Data/native/bin/leviathan-data-plane",
      operations: ["parse", "embed"],
      detail: "fixture probe",
      recent: [
        { at: "21:39:02", message: "selected python fallback is not claimed as native success", operation: "probe" },
        { at: "21:39:04", message: "operation started", operation: "parse" },
        { at: "21:39:05", message: "operation complete", operation: "parse" },
        { at: "21:39:06", message: "receipt recorded", operation: "embed" },
      ],
      daemon: false,
    },
    uptime: "39m 07s",
    servicesOnline: "9/9",
    queue: "3",
  };
}

export function fixtureLines(): ConsoleLine[] {
  const rows = [
    ["host", "info", "PREFLIGHT install root, venv, env, imports, databases"],
    ["process", "info", "Starting via leviathan.py"],
    ["process", "info", "PYTHONPATH prepended with install root"],
    ["process", "info", "Loading Data.backend.main:app"],
    ["process", "info", "REST API listening on loopback"],
    ["supervisor", "info", "Worker supervisor lease acquired"],
    ["supervisor", "info", "pools started under one supervisor process"],
    ["native", "info", "native data-plane probe recorded"],
    ["jobs", "info", "JobStore readable"],
    ["state", "info", "RUNNING after /api/health"],
    ["host", "info", "stdout and stderr captured in this window"],
    ["host", "info", "no auxiliary console was opened"],
  ];
  return rows.map(([source, level, text], index) => ({
    seq: index + 1,
    at: `2026-09-27T21:39:${String(index).padStart(2, "0")}Z`,
    source,
    level,
    stream: source === "process" ? "stdout" : "system",
    text,
  }));
}
