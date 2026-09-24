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
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "";
  const diffMs = Date.now() - d.getTime();
  const abs = Math.abs(diffMs);
  const mins = Math.round(abs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}

export function priorityLabel(priority: string | null | undefined): string {
  const p = (priority || "medium").toLowerCase();
  if (p === "high") return "High";
  if (p === "low") return "Low";
  return "Medium";
}

export function priorityClass(priority: string | null | undefined): string {
  const p = (priority || "medium").toLowerCase();
  if (p === "high") return "lv-tasks-badge--high";
  if (p === "low") return "lv-tasks-badge--low";
  return "lv-tasks-badge--medium";
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
  if (n.includes("research")) return "lv-tasks-avatar--green";
  if (n.includes("coding")) return "lv-tasks-avatar--cyan";
  if (n.includes("trading")) return "lv-tasks-avatar--gold";
  if (n.includes("finance")) return "lv-tasks-avatar--orange";
  if (n.includes("emma")) return "lv-tasks-avatar--purple";
  if (n.includes("sarah")) return "lv-tasks-avatar--red";
  if (n.includes("planning")) return "lv-tasks-avatar--purple";
  if (n.includes("alex")) return "lv-tasks-avatar--blue";
  return "";
}

/** Convert 0–1 displayProgress (or legacy 0–100) to integer percent. */
export function displayProgressPct(task: Pick<TaskRecord, "displayProgress" | "progress" | "executionProgress">): number {
  const raw = task.displayProgress ?? task.executionProgress ?? task.progress;
  if (raw == null || Number.isNaN(Number(raw))) return 0;
  const n = Number(raw);
  if (n > 1) return Math.max(0, Math.min(100, Math.round(n)));
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

export function dueHint(iso: string | null | undefined): string | null {
  const d = parseIso(iso);
  if (!d) return null;
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000);
  if (days < 0) return `(${Math.abs(days)}d overdue)`;
  if (days === 0) return "(today)";
  if (days === 1) return "(1 day left)";
  if (days <= 7) return `(${days} days left)`;
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
  if (task.archivedAt) return false;
  if (task.executionBinding === "manual") return false;
  return isExecutionRunning(task);
}

export function canRetryTask(task: TaskRecord): boolean {
  if (task.archivedAt) return false;
  if (task.executionBinding === "manual") return false;
  return isExecutionFailed(task);
}

export function canCompleteTask(task: TaskRecord): boolean {
  if (task.archivedAt) return false;
  return normalizeBoardColumn(task.boardColumn) !== "done";
}

/** Map toolbar UI filter values → API listTasks params. */
export function mapTaskListFilters(ui: {
  search: string;
  priority: string;
  status: string;
  assignee: string;
  datePreset: string;
  timezone?: string;
}): {
  search?: string;
  priority?: string;
  boardColumn?: string;
  assignee?: string;
  datePreset?: string;
  timezone?: string;
} {
  const out: {
    search?: string;
    priority?: string;
    boardColumn?: string;
    assignee?: string;
    datePreset?: string;
    timezone?: string;
  } = {};
  const search = ui.search.trim();
  if (search) out.search = search;
  if (ui.priority && ui.priority !== "all-priorities") {
    out.priority = ui.priority.toLowerCase() as TaskPriorityValue;
  }
  if (ui.status && ui.status !== "all-statuses") {
    const mapped = ui.status.replace(/-/g, "_");
    out.boardColumn = mapped === "inprogress" ? "in_progress" : mapped;
  }
  if (ui.assignee && ui.assignee !== "all-assignees") {
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
  return eventType
    .replace(/^task\./, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}
