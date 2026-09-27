import type { MetricCardModel, OperatorModel } from "../types/backend";
import type { ConsoleLine, HostSnapshot } from "../types/host";
import { stoppedSnapshot } from "../domain/host";

/** Test-only composition that reproduces Screen 1 density. Never used in production. */

function bars(seed: number, base: number, swing: number): number[] {
  return Array.from({ length: 28 }, (_, index) => base + Math.sin(index / 2.1 + seed) * swing + ((index * 7) % 5) - 2);
}

function line(seed: number, base: number, swing: number): number[] {
  return Array.from({ length: 32 }, (_, index) => base + Math.sin(index / 3.2 + seed) * swing + Math.sin(index / 1.3) * swing * 0.35);
}

function card(
  id: string,
  label: string,
  value: string,
  tone: MetricCardModel["tone"],
  samples: number[],
  chart: "line" | "bars",
  detail = "",
  unit = "",
): MetricCardModel {
  return { id, label, value, unit, samples, tone, chart, detail };
}

export function fixtureHost(): HostSnapshot {
  return {
    ...stoppedSnapshot(),
    state: "RUNNING",
    ownership: "OWNED",
    pid: 4100,
    message: "All core services running normally.",
    apiBase: "http://127.0.0.1:8000",
    frontendUrl: "http://127.0.0.1:8000/",
    version: "0.2.6",
    startedAt: "2024-12-30T07:25:00Z",
    pythonVersion: "3.11.8",
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
      { id: "api", name: "API", state: "Healthy", detail: "Uptime: 27d 14h", tone: "ok" },
      { id: "workers", name: "Workers", state: "Healthy", detail: "8 / 8 online", tone: "ok" },
      { id: "native", name: "Rust Runtime", state: "Healthy", detail: "v1.82.6", tone: "ok" },
      { id: "python", name: "Python Runtime", state: "Healthy", detail: "v3.11.8", tone: "ok" },
      { id: "vector", name: "Vector DB", state: "Healthy", detail: "Qdrant 1.9.1", tone: "ok" },
      { id: "database", name: "Database", state: "Healthy", detail: "PostgreSQL 16", tone: "ok" },
      { id: "model", name: "Model Runtime", state: "Healthy", detail: "Ollama · Transformers", tone: "ok" },
      { id: "queue", name: "Queue", state: "Healthy", detail: "Redis 7.2", tone: "ok" },
      { id: "watcher", name: "File Watcher", state: "Healthy", detail: "Monitoring", tone: "ok" },
    ],
    workers: [
      ["wrk-01", "Active", "Ingesting document smithsonian_1947.pdf", "ingest", "12%", "1.2 GB", "3", "2d 14h"],
      ["wrk-02", "Active", "Embedding chunks (1,240 / 1,880)", "embed", "38%", "1.8 GB", "7", "3d 02h"],
      ["wrk-03", "Active", "Generating summaries", "summary", "24%", "1.1 GB", "1", "1d 07h"],
      ["wrk-04", "Active", "Vector indexing (batch 12/24)", "index", "56%", "2.1 GB", "5", "6d 11h"],
      ["wrk-05", "Active", "Knowledge graph extraction", "graph", "18%", "1.0 GB", "0", "4d 09h"],
      ["wrk-06", "Active", "Classifying content", "classify", "31%", "1.4 GB", "2", "1d 18h"],
      ["wrk-07", "Active", "Generating embeddings", "embed", "44%", "1.6 GB", "6", "5d 03h"],
      ["wrk-08", "Active", "Idle (waiting for tasks)", "idle", "2%", "0.8 GB", "0", "12h 26m"],
    ].map(([id, state, task, pool, cpu, ram, queue, heartbeat]) => ({ id, state, task, pool, cpu, ram, queue, heartbeat })),
    workerSummary: "8 / 8 Online",
    metrics: [
      card("tasks", "TASKS / MIN", "84.2", "cyan", bars(0.2, 70, 16), "bars"),
      card("queue", "TASKS IN QUEUE", "42", "cyan", bars(1.4, 36, 14), "bars"),
      card("done", "COMPLETED (24H)", "12,846", "green", bars(2.1, 80, 12), "bars"),
      card("cpu", "CPU USAGE", "34%", "cyan", line(0.4, 34, 8), "line", "8 cores"),
      card("mem", "MEMORY USAGE", "48%", "green", line(1.1, 48, 6), "line", "12.3 / 32 GB"),
      card("disk", "DISK USAGE", "26%", "amber", line(2.2, 26, 3), "line", "248 / 1,000 GB"),
      card("native", "EMBEDDINGS / SEC", "426.8", "green", line(0.6, 420, 40), "line"),
      card("docs", "DOCS / SEC", "12.6", "cyan", line(1.7, 12, 2), "line"),
      card("net", "NETWORK I/O", "12.4 MB/s", "violet", line(2.4, 12, 3), "line", "↑ 8.7 MB/s"),
    ],
    logs: [
      ["21:38:01", "INFO", "ingest", "Queued document: vatican_archives_1932.pdf"],
      ["21:38:02", "SUCCESS", "embed", "Generated 1,824 embeddings (batch 8/8)"],
      ["21:38:03", "INFO", "vector", "Indexed vectors in 2.4s (1,024 items)"],
      ["21:38:05", "WARNING", "worker", "High memory usage (worker wrk-04): 82%"],
      ["21:38:07", "INFO", "api", "POST /v1/ingest — 200 (1.2s)"],
      ["21:38:11", "SUCCESS", "graph", "Knowledge graph updated (342 entities)"],
      ["21:38:14", "INFO", "rust", "Pipeline stage complete: classify_documents"],
      ["21:38:16", "INFO", "db", "Vacuum completed (0.8s)"],
      ["21:38:19", "SUCCESS", "monitor", "All workers healthy (8/8)"],
      ["21:38:21", "INFO", "queue", "Processed 12 tasks from ingest queue"],
      ["21:38:24", "INFO", "models", "Loaded model: llama3.2 (7B)"],
      ["21:38:28", "SUCCESS", "ingest", "Completed document: smithsonian_1947.pdf (1,580 chunks)"],
    ].map(([time, level, module, message], index) => ({ id: String(index + 1), time, level, module, message })),
    ingestion: {
      queued: 128,
      processing: 6,
      completed: 1248,
      failed: 3,
      overallProgressPct: 78,
      unavailable: false,
      jobs: [
        ["4129", "smithsonian_1947.pdf", "PDF", "Processing", 68, "12m 14s"],
        ["4130", "vatican_archives_1932.pdf", "PDF", "Processing", 42, "8m 21s"],
        ["4131", "tartaria_maps_collection.zip", "ZIP", "Completed", 100, "3h 02m"],
        ["4132", "forbidden_histories.txt", "TXT", "Completed", 100, "1h 48m"],
        ["4133", "ancient_structures.pdf", "PDF", "Processing", 76, "14m 06s"],
        ["4134", "mudflood_research.docx", "DOCX", "Processing", 33, "6m 11s"],
        ["4135", "lost_technologies.pdf", "PDF", "Completed", 100, "2h 55m"],
        ["4136", "geodetic_evidence.zip", "ZIP", "Pending", 0, "—"],
        ["4137", "cathedral_networks.pdf", "PDF", "Pending", 0, "—"],
        ["4138", "old_world_documents.rar", "RAR", "Pending", 0, "—"],
      ].map(([id, source, type, state, progressPct, elapsed]) => ({
        id: String(id),
        source: String(source),
        type: String(type),
        state: String(state),
        progressPct: Number(progressPct),
        throughput: "UNMEASURED",
        elapsed: String(elapsed),
        worker: "—",
        error: null,
      })),
    },
    native: {
      status: "AVAILABLE",
      version: "v1.82.6",
      binaryPath: "native runtime",
      operations: ["embed", "index", "classify"],
      detail: "fixture native log",
      recent: [
        ["21:37:15", "Leviathan native runtime v1.82.6"],
        ["21:37:15", "Initializing vector pipeline..."],
        ["21:37:16", "Loading SIMD optimizations (AVX2, FMA)..."],
        ["21:37:16", "Compiled embedding pipeline (release)"],
        ["21:37:17", "Indexing engine ready (HNSW, 768 dim)"],
        ["21:37:18", "Starting document processing pipeline..."],
        ["21:38:02", "Processed 1,024 embeddings in 2.3s"],
        ["21:38:07", "Graph extraction: 342 entities, 1,248 relations"],
        ["21:38:14", "Classification pipeline completed (18.6s)"],
        ["21:38:21", "Batch indexing 1,880 vectors..."],
        ["21:38:24", "Index commit successful"],
        ["21:38:28", "Memory usage: 1.2 GB (peak: 2.1 GB)"],
        ["21:38:28", "Throughput: 426.8 embeddings/sec"],
        ["21:38:28", "Native runtime idle — waiting for next batch..."],
      ].map(([at, message]) => ({ at, message, operation: "rust" })),
      daemon: false,
    },
    uptime: "27d 14h 12m",
    servicesOnline: "8/8",
    queue: "42",
  };
}

export function fixtureLines(): ConsoleLine[] {
  const rows = [
    ["SYSTEM", "Starting LEVIATHAN backend host v0.2.6..."],
    ["SYSTEM", "Loading configuration from config/leviathan.yaml"],
    ["CORE", "Initializing core services..."],
    ["API", "REST API server listening on http://127.0.0.1:8000"],
    ["WORKERS", "Spawning worker processes (8/8)..."],
    ["RUST", "Rust runtime initialized (v1.82.6)"],
    ["PYTHON", "Python runtime initialized (v3.11.8)"],
    ["VECTOR", "Connected to Qdrant (qdrant://localhost:6333)"],
    ["DB", "Connected to PostgreSQL (localhost:5432)"],
    ["QUEUE", "Connected to Redis (localhost:6379)"],
    ["MODELS", "Model runtime ready (Ollama, transformers)"],
    ["WATCHER", "File system watcher active (content/, sources/, docs/)"],
    ["SYSTEM", "LEVIATHAN backend host fully initialized."],
    ["SYSTEM", "Backend host active. Waiting for tasks..."],
  ];
  return rows.map(([source, text], index) => ({
    seq: index + 1,
    at: `2025-01-26T21:37:${String(12 + index).padStart(2, "0")}Z`,
    source,
    level: "info",
    stream: "system",
    text,
  }));
}
