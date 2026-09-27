import type { WorkerRowModel } from "../types/backend";
import { displayPercent } from "../lib/format";
import { asProjection, transportFailed, type ReadProjection } from "./projection";

export function mapWorkers(
  dashboard: ReadProjection<Record<string, unknown>> | Record<string, unknown> | null,
): { rows: WorkerRowModel[]; summary: string } {
  const projection = asProjection(dashboard);

  if (transportFailed(projection) && projection.data == null) {
    return { rows: [], summary: "TRANSPORT ERROR" };
  }
  if (projection.state === "LOADING" && projection.data == null) {
    return { rows: [], summary: "UNMEASURED" };
  }

  const body = projection.data;
  if (!body) return { rows: [], summary: "UNMEASURED" };

  const workers = Array.isArray(body.workers) ? body.workers : [];
  const rows = workers.map((raw) => mapWorker(raw as Record<string, unknown>));
  const summary = body.summary as Record<string, unknown> | undefined;
  const running = summary?.running_workers;
  const desired = summary?.desired_workers;

  if (typeof desired === "number" && desired === 0) {
    return { rows, summary: "DISABLED / NOT CONFIGURED" };
  }

  if (transportFailed(projection)) {
    const base =
      typeof running === "number" && typeof desired === "number"
        ? `${running} / ${desired}`
        : `${rows.length} registered`;
    return { rows, summary: projection.state === "STALE" ? `STALE · ${base}` : `TRANSPORT ERROR · ${base}` };
  }

  const text =
    typeof running === "number" && typeof desired === "number" ? `${running} / ${desired}` : `${rows.length} registered`;
  return { rows, summary: text };
}

export function mapWorker(row: Record<string, unknown>): WorkerRowModel {
  const cpu = typeof row.cpu_percent === "number" ? displayPercent(row.cpu_percent) : "UNMEASURED";
  const ram = typeof row.rss_mb === "number" ? `${row.rss_mb.toFixed(0)} MB` : "UNMEASURED";
  const age = row.heartbeat_age_seconds;
  const heartbeat = typeof age === "number" ? `${Math.round(age)}s` : "—";
  const queue = typeof row.queue_depth === "number" ? String(row.queue_depth) : "—";
  const state = String(row.state || "—");
  const work = row.current_work;
  const hasWork = work != null && String(work).trim() !== "" && String(work) !== "—";
  const task = hasWork
    ? String(work)
    : state.toUpperCase() === "READY"
      ? "IDLE/WAITING"
      : "—";
  return {
    id: String(row.worker_id || row.id || row.display_name || "—"),
    state,
    task,
    pool: String(row.pool_id || "—"),
    cpu,
    ram,
    queue,
    heartbeat,
  };
}
