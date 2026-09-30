import type { ActivityEvent, ActivityLifecycle, ActivityProjection } from "../types/activity";
import { parseActivityEvent } from "../types/activity";

const TERMINAL: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "cancelled",
  "skipped",
]);

function lifecycleRank(lifecycle: ActivityLifecycle): number {
  const order: Record<string, number> = {
    queued: 10,
    starting: 20,
    running: 30,
    waiting: 35,
    retrying: 40,
    degraded: 45,
    skipped: 50,
    completed: 60,
    cancelled: 70,
    failed: 80,
  };
  return order[String(lifecycle)] ?? 0;
}

function mergeEvents(existing: ActivityEvent, incoming: ActivityEvent): ActivityEvent {
  const preferIncoming =
    lifecycleRank(incoming.lifecycle) >= lifecycleRank(existing.lifecycle) &&
    (incoming.sequence >= existing.sequence || TERMINAL.has(String(incoming.lifecycle)));
  const lifecycle = preferIncoming ? incoming.lifecycle : existing.lifecycle;
  return {
    ...existing,
    ...incoming,
    eventId: existing.eventId,
    operationId: incoming.operationId || existing.operationId,
    parentEventId: incoming.parentEventId ?? existing.parentEventId,
    sequence: Math.max(existing.sequence, incoming.sequence),
    lifecycle,
    title: preferIncoming ? incoming.title : existing.title,
    summary: incoming.summary ?? existing.summary,
    startedAt: existing.startedAt ?? incoming.startedAt,
    updatedAt: incoming.updatedAt ?? existing.updatedAt,
    finishedAt: incoming.finishedAt ?? existing.finishedAt,
    progress: incoming.progress ?? existing.progress,
    resultCount: incoming.resultCount ?? existing.resultCount,
    error: incoming.error ?? existing.error,
    evidenceRefs: Array.from(
      new Set([...(existing.evidenceRefs ?? []), ...(incoming.evidenceRefs ?? [])]),
    ),
    artifactRefs: Array.from(
      new Set([...(existing.artifactRefs ?? []), ...(incoming.artifactRefs ?? [])]),
    ),
    sourceRefs: Array.from(
      new Set([...(existing.sourceRefs ?? []), ...(incoming.sourceRefs ?? [])]),
    ),
    modelRef: incoming.modelRef ?? existing.modelRef,
    agentRef: incoming.agentRef ?? existing.agentRef,
    workerRef: incoming.workerRef ?? existing.workerRef,
    capabilityRef: incoming.capabilityRef ?? existing.capabilityRef,
    config: incoming.config ?? existing.config,
    payload: { ...(existing.payload ?? {}), ...(incoming.payload ?? {}) },
    children: undefined,
  };
}

/** Client-side projector — mirrors backend ActivityProjector semantics. */
export class ActivityClientProjector {
  private byId = new Map<string, ActivityEvent>();
  stale = false;
  disconnected = false;
  operationId = "";
  private maxEvents: number;

  constructor(opts?: { maxEvents?: number }) {
    this.maxEvents = opts?.maxEvents ?? 2000;
  }

  ingest(raw: unknown): ActivityEvent | null {
    const parsed = parseActivityEvent(raw);
    if (!parsed) return null;
    if (!this.operationId) this.operationId = parsed.operationId;
    const existing = this.byId.get(parsed.eventId);
    if (existing) {
      const merged = mergeEvents(existing, parsed);
      this.byId.set(parsed.eventId, merged);
      return merged;
    }
    this.byId.set(parsed.eventId, parsed);
    this.trim();
    return parsed;
  }

  ingestMany(raws: unknown[]): void {
    for (const raw of raws) this.ingest(raw);
  }

  ingestProjection(projection: ActivityProjection | null | undefined): void {
    if (!projection) return;
    if (projection.operationId) this.operationId = projection.operationId;
    this.stale = Boolean(projection.stale);
    this.disconnected = Boolean(projection.disconnected);
    this.ingestMany(projection.events ?? []);
    this.ingestMany(projection.tree ?? []);
  }

  markDisconnected(): void {
    this.disconnected = true;
    this.stale = true;
  }

  markStale(): void {
    this.stale = true;
  }

  reset(): void {
    this.byId.clear();
    this.stale = false;
    this.disconnected = false;
    this.operationId = "";
  }

  project(): ActivityProjection {
    const events = Array.from(this.byId.values()).sort((a, b) => {
      if (a.sequence !== b.sequence) return a.sequence - b.sequence;
      return String(a.updatedAt ?? a.startedAt ?? "").localeCompare(
        String(b.updatedAt ?? b.startedAt ?? ""),
      );
    });
    const byParent = new Map<string | null, ActivityEvent[]>();
    for (const event of events) {
      const key = event.parentEventId ?? null;
      const list = byParent.get(key) ?? [];
      list.push(event);
      byParent.set(key, list);
    }
    const build = (parentId: string | null): ActivityEvent[] => {
      const kids = byParent.get(parentId) ?? [];
      return kids.map((event) => ({
        ...event,
        children: build(event.eventId),
      }));
    };
    const highestSequence = events.reduce((m, e) => Math.max(m, e.sequence), 0);
    return {
      operationId: this.operationId,
      highestSequence,
      stale: this.stale,
      disconnected: this.disconnected,
      tree: build(null),
      events,
      truth: {
        projection_not_authority: true,
        stale_not_completed: true,
      },
    };
  }

  private trim(): void {
    while (this.byId.size > this.maxEvents) {
      let dropId: string | null = null;
      for (const [id, ev] of this.byId) {
        if (!TERMINAL.has(String(ev.lifecycle)) && !ev.error) {
          const cat = String(ev.category);
          if (cat === "DECISION" || cat === "ARTIFACT" || cat === "VERIFICATION" || cat === "RISK") {
            continue;
          }
          dropId = id;
          break;
        }
      }
      if (!dropId) {
        dropId = this.byId.keys().next().value ?? null;
      }
      if (!dropId) break;
      this.byId.delete(dropId);
    }
  }
}

export function formatActivityDurationMs(
  startedAt?: string | null,
  finishedAt?: string | null,
  updatedAt?: string | null,
): number | null {
  if (!startedAt) return null;
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return null;
  const endRaw = finishedAt || updatedAt;
  if (!endRaw) return null;
  const end = Date.parse(endRaw);
  if (!Number.isFinite(end) || end < start) return null;
  return end - start;
}

export function formatDurationLabel(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  if (ms >= 1000) {
    const s = ms / 1000;
    return `${s >= 10 ? Math.round(s) : s.toFixed(1).replace(/\.0$/, "")}s`;
  }
  return `${Math.round(ms)}ms`;
}

export function lifecycleStatusLabel(lifecycle: ActivityLifecycle): string {
  switch (lifecycle) {
    case "queued":
      return "Pending";
    case "starting":
      return "Starting";
    case "running":
      return "Running";
    case "waiting":
      return "Waiting";
    case "retrying":
      return "Retrying";
    case "completed":
      return "Complete";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    case "degraded":
      return "Degraded";
    case "skipped":
      return "Skipped";
    default:
      return "Unknown";
  }
}

export function compactHeadline(projection: ActivityProjection | null): string {
  if (!projection) return "Activity unavailable";
  if (projection.disconnected) return "Activity stream disconnected";
  if (projection.stale) return "Activity state may be stale";
  const running = projection.events.find((e) => e.lifecycle === "running" || e.lifecycle === "starting");
  if (running) return running.title;
  const failed = [...projection.events].reverse().find((e) => e.lifecycle === "failed");
  if (failed) return failed.title;
  const completed = [...projection.events].reverse().find((e) => e.lifecycle === "completed");
  if (completed) return completed.title;
  if (projection.events.length === 0) return "No activity reported";
  return projection.events[projection.events.length - 1]?.title ?? "Activity";
}

/** Never invent measured counts — only format when backend provided resultCount. */
export function formatResultCount(count: number | null | undefined, noun = "item"): string | null {
  if (count == null || !Number.isFinite(count)) return null;
  const n = Math.trunc(count);
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

export function formatMeasuredProgress(progress: ActivityEvent["progress"]): string | null {
  if (!progress || progress.kind !== "measured") return null;
  if (
    progress.numerator != null &&
    progress.denominator != null &&
    Number.isFinite(progress.numerator) &&
    Number.isFinite(progress.denominator) &&
    progress.denominator > 0
  ) {
    const pct = Math.round((Number(progress.numerator) / Number(progress.denominator)) * 100);
    const unit = progress.unit ? ` ${progress.unit}` : "";
    return `${progress.numerator} / ${progress.denominator}${unit} (${pct}%)`;
  }
  if (progress.value != null && Number.isFinite(progress.value)) {
    const pct = Math.round(Number(progress.value) * (Number(progress.value) <= 1 ? 100 : 1));
    return `${pct}%`;
  }
  return null;
}
