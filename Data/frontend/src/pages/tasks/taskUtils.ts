import { ApiError } from "../../api/client";
import type { TaskBoardColumn, TaskPriorityValue, TaskRecord } from "../../types/api";

export const COLUMN_ORDER: TaskBoardColumn[] = ["backlog", "in_progress", "review", "done"];

export const COLUMN_META: Record<
  TaskBoardColumn,
  { title: string; tone: string; icon: "clipboard" | "layers" | "shield" | "check" }
> = {
  backlog: { title: "Backlog", tone: "muted", icon: "clipboard" },
  in_progress: { title: "In Progress", tone: "cyan", icon: "layers" },
  review: { title: "Review", tone: "gold", icon: "shield" },
  done: { title: "Done", tone: "green", icon: "check" },
};

export type OperationalStatus = "running" | "waiting" | "completed" | "failed" | "cancelled";

export function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function clientTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDue(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  return d.toLocaleDateString("nl-NL", { month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  return d.toLocaleString("nl-NL", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatTime(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(
  startIso: string | null | undefined,
  endIso?: string | null | undefined,
): string {
  const start = parseIso(startIso);
  if (!start) return "—";
  const end = parseIso(endIso) ?? new Date();
  const ms = Math.max(0, end.getTime() - start.getTime());
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  if (hours < 48) return rem ? `${hours}u ${rem}m` : `${hours}u`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

export function formatRelative(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "";
  const diffMs = Date.now() - d.getTime();
  const abs = Math.abs(diffMs);
  const mins = Math.round(abs / 60_000);
  if (mins < 1) return "zojuist";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}u`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}

export function priorityLabel(priority: string | null | undefined): string {
  const p = (priority || "medium").toLowerCase();
  if (p === "high") return "Hoog";
  if (p === "low") return "Laag";
  return "Normaal";
}

export function priorityClass(priority: string | null | undefined): string {
  const p = (priority || "medium").toLowerCase();
  if (p === "high") return "lv-v2-tasks-badge--priority-high";
  if (p === "low") return "lv-v2-tasks-badge--priority-low";
  return "lv-v2-tasks-badge--priority-normal";
}

export function boardColumnLabel(column: string | null | undefined): string {
  const key = normalizeBoardColumn(column);
  return COLUMN_META[key]?.title ?? "Backlog";
}

export function normalizeBoardColumn(column: string | null | undefined): TaskBoardColumn {
  const c = (column || "backlog").toLowerCase().replace(/-/g, "_");
  if (c === "in_progress" || c === "inprogress") return "in_progress";
  if (c === "review") return "review";
  if (c === "done") return "done";
  return "backlog";
}

export function initials(name: string | null | undefined): string {
  const raw = (name || "?").trim();
  if (!raw) return "?";
  const parts = raw.split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

export function avatarTone(name: string | null | undefined): string {
  const n = (name || "").toLowerCase();
  if (n.includes("research")) return "lv-v2-tasks-avatar--green";
  if (n.includes("coding")) return "lv-v2-tasks-avatar--cyan";
  if (n.includes("trading") || n.includes("trader")) return "lv-v2-tasks-avatar--gold";
  if (n.includes("data")) return "lv-v2-tasks-avatar--blue";
  if (n.includes("training")) return "lv-v2-tasks-avatar--purple";
  if (n.includes("system")) return "lv-v2-tasks-avatar--red";
  return "";
}

/**
 * Measured progress percent, or null when unknown.
 * `0` means measured zero — never treat unknown as zero.
 */
export function displayProgressPct(
  task: Pick<TaskRecord, "displayProgress" | "progress" | "executionProgress" | "progressKnown">,
): number | null {
  if (task.progressKnown === false) return null;
  const raw = task.displayProgress ?? task.executionProgress ?? task.progress;
  if (raw == null || Number.isNaN(Number(raw))) {
    if (task.progressKnown === true) return 0;
    return null;
  }
  const n = Number(raw);
  if (n > 1) return Math.max(0, Math.min(100, Math.round(n)));
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

export function dueHint(iso: string | null | undefined): string | null {
  const d = parseIso(iso);
  if (!d) return null;
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000);
  if (days < 0) return `(${Math.abs(days)}d te laat)`;
  if (days === 0) return "(vandaag)";
  if (days === 1) return "(1 dag)";
  if (days <= 7) return `(${days} dagen)`;
  return null;
}

const RUNNING_STATES = new Set([
  "queued",
  "starting",
  "running",
  "cancelling",
  "created",
  "retry_wait",
  "cancel_requested",
  "pausing",
  "paused",
]);

const FAILED_STATES = new Set(["failed", "cancelled", "interrupted"]);

export function isExecutionRunning(task: TaskRecord): boolean {
  if (task.executionBinding === "manual") return false;
  const state = (task.executionState || "").toLowerCase();
  return RUNNING_STATES.has(state);
}

export function isExecutionFailed(task: TaskRecord): boolean {
  const state = (task.executionState || "").toLowerCase();
  return FAILED_STATES.has(state) || Boolean(task.executionError && !isExecutionRunning(task));
}

export function canStartTask(task: TaskRecord): boolean {
  if (task.archivedAt) return false;
  if (normalizeBoardColumn(task.boardColumn) === "done") return false;
  if (isExecutionRunning(task)) return false;
  return true;
}

export function canCancelTask(task: TaskRecord): boolean {
  if (task.controls?.canCancel != null) return Boolean(task.controls.canCancel);
  if (task.archivedAt) return false;
  if (task.executionBinding === "manual") return false;
  return isExecutionRunning(task);
}

export function canRetryTask(task: TaskRecord): boolean {
  if (task.controls?.canRetry != null) return Boolean(task.controls.canRetry);
  if (task.archivedAt) return false;
  if (task.executionBinding === "manual") return false;
  return isExecutionFailed(task);
}

export function canCompleteTask(task: TaskRecord): boolean {
  if (task.archivedAt) return false;
  return normalizeBoardColumn(task.boardColumn) !== "done";
}

export function canPauseTask(task: TaskRecord): boolean {
  return Boolean(task.controls?.canPause);
}

export function operationalStatus(task: TaskRecord): OperationalStatus {
  const raw = (task.operationalStatus || "").toLowerCase();
  if (raw === "running" || raw === "waiting" || raw === "completed" || raw === "failed" || raw === "cancelled") {
    return raw;
  }
  if (normalizeBoardColumn(task.boardColumn) === "done" || task.completedAt) return "completed";
  if (isExecutionFailed(task)) return "failed";
  if (normalizeBoardColumn(task.boardColumn) === "in_progress" || isExecutionRunning(task)) return "running";
  return "waiting";
}

export function statusLabel(status: OperationalStatus | string): string {
  const s = (status || "").toLowerCase();
  if (s === "running") return "Actief";
  if (s === "completed") return "Voltooid";
  if (s === "waiting") return "Wachtend";
  if (s === "failed") return "Mislukt";
  if (s === "cancelled") return "Geannuleerd";
  return status || "—";
}

export function statusTone(status: OperationalStatus | string): "success" | "info" | "warning" | "danger" | "muted" {
  const s = (status || "").toLowerCase();
  if (s === "running") return "success";
  if (s === "completed") return "info";
  if (s === "waiting") return "warning";
  if (s === "failed" || s === "cancelled") return "danger";
  return "muted";
}

export function taskTypeLabel(type: string | null | undefined): string {
  const t = (type || "general").toLowerCase();
  const map: Record<string, string> = {
    research: "Research",
    trading: "Trading",
    data: "Data",
    training: "Training",
    analysis: "Analysis",
    system: "System",
    browser: "Browser",
    tool: "Tool",
    development: "Development",
    evaluation: "Evaluation",
    knowledge: "Knowledge",
    general: "Algemeen",
    job: "Tool",
    agent: "System",
    workflow: "System",
    schedule: "System",
    cognition: "Knowledge",
    manual: "Algemeen",
  };
  return map[t] ?? (type ? type.charAt(0).toUpperCase() + type.slice(1) : "Algemeen");
}

export function taskTypeTone(
  type: string | null | undefined,
): "research" | "trading" | "training" | "data" | "system" | "success" | "warning" | "danger" | "info" | "muted" {
  const t = (type || "general").toLowerCase();
  if (t === "research" || t === "knowledge") return "research";
  if (t === "trading") return "trading";
  if (t === "training" || t === "development") return "training";
  if (t === "data" || t === "analysis" || t === "evaluation") return "data";
  if (t === "system" || t === "tool" || t === "browser" || t === "job" || t === "agent") return "system";
  return "muted";
}

export function displayTaskId(task: Pick<TaskRecord, "taskId" | "displayId">): string {
  return `#${task.displayId || task.taskId.replace(/-/g, "").slice(-4).toUpperCase()}`;
}

export function startedAt(task: TaskRecord): string | null {
  return task.executionStartedAt || task.plannedStartAt || task.createdAt || null;
}

export function finishedAt(task: TaskRecord): string | null {
  return task.executionFinishedAt || task.completedAt || null;
}

/** Map toolbar UI filter values → API listTasks params. */
export function mapTaskListFilters(ui: {
  search: string;
  priority: string;
  status: string;
  type: string;
  assignee: string;
  datePreset?: string;
  timezone?: string;
}): {
  search?: string;
  priority?: string;
  boardColumn?: string;
  operationalStatus?: string;
  taskType?: string;
  assignee?: string;
  datePreset?: string;
  timezone?: string;
} {
  const out: {
    search?: string;
    priority?: string;
    boardColumn?: string;
    operationalStatus?: string;
    taskType?: string;
    assignee?: string;
    datePreset?: string;
    timezone?: string;
  } = {};
  const search = ui.search.trim();
  if (search) out.search = search;
  if (ui.priority && ui.priority !== "all-priorities" && ui.priority !== "all") {
    out.priority = ui.priority.toLowerCase() as TaskPriorityValue;
  }
  if (ui.status && ui.status !== "all-statuses" && ui.status !== "all") {
    const mapped = ui.status.replace(/-/g, "_").toLowerCase();
    if (["running", "waiting", "completed", "failed", "cancelled"].includes(mapped)) {
      out.operationalStatus = mapped;
    } else {
      out.boardColumn = mapped === "inprogress" ? "in_progress" : mapped;
    }
  }
  if (ui.type && ui.type !== "all-types" && ui.type !== "all") {
    out.taskType = ui.type.toLowerCase();
  }
  if (ui.assignee && ui.assignee !== "all-assignees" && ui.assignee !== "all-agents" && ui.assignee !== "all") {
    out.assignee = ui.assignee;
  }
  if (ui.datePreset && ui.datePreset !== "all") {
    out.datePreset = ui.datePreset;
  }
  if (ui.timezone) out.timezone = ui.timezone;
  return out;
}

export function eventTone(eventType: string): string {
  const t = eventType.toLowerCase();
  if (t.includes("fail") || t.includes("block") || t.includes("cancel")) return "red";
  if (t.includes("complete") || t.includes("note")) return "green";
  if (t.includes("start") || t.includes("assign")) return "blue";
  if (t.includes("move") || t.includes("update")) return "purple";
  if (t.includes("creat") || t.includes("auto")) return "cyan";
  return "gold";
}

export function workloadTone(index: number): string {
  const tones = ["blue", "purple", "green", "cyan", "gold", "orange"];
  return tones[index % tones.length] ?? "blue";
}

export function timelineTone(column: string | null | undefined, blocked?: boolean): string {
  if (blocked) return "red";
  const c = normalizeBoardColumn(column);
  if (c === "done") return "green";
  if (c === "review") return "gold";
  if (c === "in_progress") return "cyan";
  return "blue";
}

export function formatEventLabel(eventType: string): string {
  const t = (eventType || "").replace(/^task\./, "").toLowerCase();
  const map: Record<string, string> = {
    created: "aangemaakt",
    updated: "bijgewerkt",
    started: "gestart",
    completed: "voltooid",
    cancelled: "geannuleerd",
    failed: "mislukt",
    retried: "opnieuw gestart",
    archived: "gearchiveerd",
    assigned: "toegewezen",
    moved: "verplaatst",
    blocked: "geblokkeerd",
    unblocked: "gedeblokkeerd",
  };
  if (map[t]) return map[t];
  return eventType
    .replace(/^task\./, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatActivityLine(event: {
  eventType: string;
  taskId: string;
  taskTitle?: string | null;
  displayId?: string;
}): string {
  const id = event.displayId ? `#${event.displayId}` : event.taskId ? `#${event.taskId.replace(/-/g, "").slice(-4).toUpperCase()}` : "";
  const label = formatEventLabel(event.eventType);
  const title = event.taskTitle ? ` — ${event.taskTitle}` : "";
  return `Taak ${id} ${label}${title}`.trim();
}
