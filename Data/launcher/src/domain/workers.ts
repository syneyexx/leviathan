import type { WorkerRowModel } from "../types/backend";
import { displayPercent } from "../lib/format";

export function mapWorkers(dashboard: Record<string, unknown> | null): { rows: WorkerRowModel[]; summary: string } {
  if (!dashboard) return { rows: [], summary: "UNMEASURED" };
  const workers = Array.isArray(dashboard.workers) ? dashboard.workers : [];
  const rows = workers.map((raw) => mapWorker(raw as Record<string, unknown>));
  const summary = dashboard.summary as Record<string, unknown> | undefined;
  const running = summary?.running_workers;
  const desired = summary?.desired_workers;
  const text =
    typeof running === "number" && typeof desired === "number" ? `${running} / ${desired}` : `${rows.length} registered`;
  return { rows, summary: text };
}

export function mapWorker(row: Record<string, unknown>): WorkerRowModel {
  const cpu = typeof row.cpu_percent === "number" ? displayPercent(row.cpu_percent) : "UNMEASURED";
  const ram = typeof row.rss_mb === "number" ? `${row.rss_mb.toFixed(0)} MB` : "UNMEASURED";
  const age = row.heartbeat_age_seconds;
  const heartbeat = typeof age === "number" ? `${Math.round(age)}s` : "UNMEASURED";
  const queue = typeof row.queue_depth === "number" ? String(row.queue_depth) : "—";
  return {
    id: String(row.worker_id || row.id || row.display_name || "UNMEASURED"),
    state: String(row.state || "UNMEASURED"),
    task: String(row.current_work || "—"),
    pool: String(row.pool_id || "—"),
    cpu,
    ram,
    queue,
    heartbeat,
  };
}
