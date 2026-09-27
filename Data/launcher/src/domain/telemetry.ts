import type { MetricCardModel } from "../types/backend";
import { displayNumber, displayPercent } from "../lib/format";

export interface MetricHistories {
  queue: Array<number | null>;
  tasks: Array<number | null>;
  completed: Array<number | null>;
  cpu: Array<number | null>;
  memory: Array<number | null>;
  disk: Array<number | null>;
  native: Array<number | null>;
  docs: Array<number | null>;
  network: Array<number | null>;
}

export function emptyHistories(): MetricHistories {
  return { queue: [], tasks: [], completed: [], cpu: [], memory: [], disk: [], native: [], docs: [], network: [] };
}

export function readPerformance(snapshot: Record<string, unknown> | null): {
  cpu: number | null;
  memory: number | null;
  queue: number | null;
  nativeOps: number | null;
  docs: number | null;
  disk: number | null;
  network: number | null;
  completed: number | null;
  tasksPerMin: number | null;
} {
  const system = (snapshot?.system || {}) as Record<string, unknown>;
  const cpu = nestedNumber(system, ["cpu", "utilizationPct"]) ?? nestedNumber(system, ["dashboard", "cpuPct"]);
  const memory = nestedNumber(system, ["memory", "utilizationPct"]) ?? nestedNumber(system, ["dashboard", "ramPct"]);
  const metrics = (snapshot?.metrics || {}) as Record<string, unknown>;
  const counters = (metrics.counters || metrics.gauges || metrics) as Record<string, unknown>;
  return {
    cpu,
    memory,
    queue: null,
    nativeOps: firstNumber(counters, ["native_ops_per_sec", "embeddings_per_sec"]),
    docs: firstNumber(counters, ["docs_per_sec", "documents_per_sec"]),
    disk: nestedNumber(system, ["disk", "utilizationPct"]),
    network: nestedNumber(system, ["network", "bytesPerSec"]),
    completed: firstNumber(counters, ["jobs_completed_24h"]),
    tasksPerMin: firstNumber(counters, ["tasks_per_min"]),
  };
}

function nestedNumber(root: Record<string, unknown>, path: string[]): number | null {
  let current: unknown = root;
  for (const key of path) {
    if (!current || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "number" && Number.isFinite(current) ? current : null;
}

function firstNumber(bag: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = bag[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

export function metricCards(samples: MetricHistories, latest: ReturnType<typeof readPerformance>, queueDepth: number | null): MetricCardModel[] {
  const queue = queueDepth;
  return [
    metric("queue", "QUEUE DEPTH", queue == null ? "UNMEASURED" : displayNumber(queue), "", samples.queue, "cyan"),
    metric("tasks", "TASKS / MIN", displayNumber(latest.tasksPerMin, 1), "", samples.tasks, "green"),
    metric("done", "COMPLETED / 24H", displayNumber(latest.completed), "", samples.completed, "cyan"),
    metric("cpu", "CPU USAGE", displayPercent(latest.cpu), "", samples.cpu, "cyan"),
    metric("mem", "MEMORY USAGE", displayPercent(latest.memory), "", samples.memory, "green"),
    metric("disk", "DISK USAGE", displayPercent(latest.disk), "", samples.disk, "amber"),
    metric("native", "NATIVE OPS / SEC", displayNumber(latest.nativeOps, 1), "", samples.native, "green"),
    metric("docs", "DOCS / SEC", displayNumber(latest.docs, 1), "", samples.docs, "cyan"),
    metric("net", "NETWORK I/O", latest.network == null ? "UNMEASURED" : displayNumber(latest.network, 1), latest.network == null ? "" : "B/s", samples.network, "violet"),
  ];
}

function metric(id: string, label: string, value: string, unit: string, samples: Array<number | null>, tone: MetricCardModel["tone"]): MetricCardModel {
  return { id, label, value, unit, samples, tone };
}
