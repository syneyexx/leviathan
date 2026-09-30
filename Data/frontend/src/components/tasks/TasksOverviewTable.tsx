import { useMemo, useState } from "react";
import { Badge, Button, ProgressBar } from "../ui";
import type { AgentDefinition, TaskRecord } from "../../types/api";
import {
  canCancelTask,
  canRetryTask,
  displayProgressPct,
  displayTaskId,
  finishedAt,
  formatDuration,
  formatTime,
  operationalStatus,
  priorityLabel,
  startedAt,
  statusLabel,
  statusTone,
  taskTypeLabel,
  taskTypeTone,
} from "../../pages/tasks/taskUtils";

export type TasksOverviewFilters = {
  searchInput: string;
  setSearchInput: (v: string) => void;
  status: string;
  setStatus: (v: string) => void;
  type: string;
  setType: (v: string) => void;
  assignee: string;
  setAssignee: (v: string) => void;
  priority: string;
  setPriority: (v: string) => void;
  typeOptions: string[];
  agents: AgentDefinition[];
};

type Props = {
  tasks: TaskRecord[];
  selectedId: string | null;
  filters: TasksOverviewFilters;
  busy?: boolean;
  onSelect: (taskId: string) => void;
  onNewTask: () => void;
  onCancel: (task: TaskRecord) => void;
  onRetry: (task: TaskRecord) => void;
  onDuplicate: (task: TaskRecord) => void;
  onChangePriority: (task: TaskRecord, priority: string) => void;
};

type SortKey = "id" | "name" | "type" | "agent" | "status" | "priority" | "progress" | "started" | "duration";

export function TasksOverviewTable({
  tasks,
  selectedId,
  filters,
  busy,
  onSelect,
  onNewTask,
  onCancel,
  onRetry,
  onDuplicate,
  onChangePriority,
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("started");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [menuId, setMenuId] = useState<string | null>(null);

  const sorted = useMemo(() => {
    const rows = [...tasks];
    const dir = sortDir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const progressA = displayProgressPct(a);
      const progressB = displayProgressPct(b);
      switch (sortKey) {
        case "id":
          return displayTaskId(a).localeCompare(displayTaskId(b)) * dir;
        case "name":
          return a.title.localeCompare(b.title) * dir;
        case "type":
          return taskTypeLabel(a.taskType).localeCompare(taskTypeLabel(b.taskType)) * dir;
        case "agent":
          return (a.assigneeName || "").localeCompare(b.assigneeName || "") * dir;
        case "status":
          return operationalStatus(a).localeCompare(operationalStatus(b)) * dir;
        case "priority": {
          const rank = (p: string) => (p === "high" ? 3 : p === "low" ? 1 : 2);
          return (rank(String(a.priority)) - rank(String(b.priority))) * dir;
        }
        case "progress":
          return ((progressA ?? -1) - (progressB ?? -1)) * dir;
        case "duration": {
          const startA = startedAt(a);
          const startB = startedAt(b);
          const dur = (s: string | null, e: string | null) =>
            s ? (Date.parse(e || new Date().toISOString()) || 0) - (Date.parse(s) || 0) : -1;
          return (dur(startA, finishedAt(a)) - dur(startB, finishedAt(b))) * dir;
        }
        case "started":
        default: {
          const sa = Date.parse(startedAt(a) || "") || 0;
          const sb = Date.parse(startedAt(b) || "") || 0;
          return (sa - sb) * dir;
        }
      }
    });
    return rows;
  }, [tasks, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "id" ? "asc" : "desc");
    }
  }

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ↑" : " ↓";
  }

  return (
    <section className="lv-v2-panel lv-v2-tasks-overview" aria-label="Taken Overzicht">
      <header className="lv-v2-panel__head lv-v2-tasks-overview__head">
        <div className="lv-v2-tasks-overview__title">
          <span className="lv-v2-tasks-overview__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M9 11l3 3L22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          </span>
          <h3 className="lv-v2-panel__title">Taken Overzicht</h3>
        </div>
        <Button variant="primary" size="sm" onClick={onNewTask} disabled={busy}>
          + Nieuwe Taak
        </Button>
      </header>

      <div className="lv-v2-tasks-filters" role="search">
        <label className="lv-v2-tasks-search">
          <span className="lv-v2-sr-only">Zoek taken</span>
          <input
            type="search"
            placeholder="Zoek taken…"
            value={filters.searchInput}
            onChange={(e) => filters.setSearchInput(e.target.value)}
          />
        </label>
        <select
          aria-label="Status"
          value={filters.status}
          onChange={(e) => filters.setStatus(e.target.value)}
        >
          <option value="all">Alle statussen</option>
          <option value="running">Actief</option>
          <option value="waiting">Wachtend</option>
          <option value="completed">Voltooid</option>
          <option value="failed">Mislukt</option>
          <option value="cancelled">Geannuleerd</option>
        </select>
        <select aria-label="Type" value={filters.type} onChange={(e) => filters.setType(e.target.value)}>
          <option value="all">Alle types</option>
          {filters.typeOptions.map((t) => (
            <option key={t} value={t}>
              {taskTypeLabel(t)}
            </option>
          ))}
        </select>
        <select
          aria-label="Agents"
          value={filters.assignee}
          onChange={(e) => filters.setAssignee(e.target.value)}
        >
          <option value="all">Alle agents</option>
          {filters.agents.map((a) => (
            <option key={a.agentId} value={a.agentId}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Prioriteit"
          value={filters.priority}
          onChange={(e) => filters.setPriority(e.target.value)}
        >
          <option value="all">Alle prioriteiten</option>
          <option value="high">Hoog</option>
          <option value="medium">Normaal</option>
          <option value="low">Laag</option>
        </select>
      </div>

      <div className="lv-v2-table-wrap lv-v2-tasks-table-wrap">
        <table className="lv-v2-table lv-v2-tasks-table">
          <thead>
            <tr>
              {(
                [
                  ["id", "ID"],
                  ["name", "Naam"],
                  ["type", "Type"],
                  ["agent", "Agent"],
                  ["status", "Status"],
                  ["priority", "Prioriteit"],
                  ["progress", "Voortgang"],
                  ["started", "Gestart"],
                  ["duration", "Duur"],
                ] as Array<[SortKey, string]>
              ).map(([key, label]) => (
                <th key={key}>
                  <button type="button" className="lv-v2-tasks-sort" onClick={() => toggleSort(key)}>
                    {label}
                    {sortIndicator(key)}
                  </button>
                </th>
              ))}
              <th>
                <span className="lv-v2-sr-only">Acties</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={10} className="lv-v2-tasks-empty-cell">
                  Geen taken gevonden
                </td>
              </tr>
            ) : (
              sorted.map((task) => {
                const status = operationalStatus(task);
                const pct = displayProgressPct(task);
                const start = startedAt(task);
                const end = finishedAt(task);
                const open = menuId === task.taskId;
                return (
                  <tr
                    key={task.taskId}
                    className={selectedId === task.taskId ? "is-selected" : undefined}
                    tabIndex={0}
                    onClick={() => onSelect(task.taskId)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(task.taskId);
                      }
                    }}
                  >
                    <td className="lv-v2-tasks-id">{displayTaskId(task)}</td>
                    <td className="lv-v2-tasks-name">{task.title}</td>
                    <td>
                      <Badge tone={taskTypeTone(task.taskType)}>{taskTypeLabel(task.taskType)}</Badge>
                    </td>
                    <td>{task.assigneeName || "—"}</td>
                    <td>
                      <span className={`lv-v2-tasks-status lv-v2-tasks-status--${statusTone(status)}`}>
                        <i aria-hidden="true" />
                        {statusLabel(status)}
                      </span>
                    </td>
                    <td>
                      <span className={`lv-v2-tasks-priority ${priorityClassName(task.priority)}`}>
                        {priorityLabel(task.priority)}
                      </span>
                    </td>
                    <td className="lv-v2-tasks-progress-cell">
                      <ProgressBar value={pct} label={pct == null ? "Onbekend" : `${pct}%`} />
                      <span className="lv-v2-tasks-progress-label">{pct == null ? "—" : `${pct}%`}</span>
                    </td>
                    <td>{formatTime(start)}</td>
                    <td>{formatDuration(start, status === "running" ? null : end)}</td>
                    <td className="lv-v2-tasks-actions-cell" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="lv-v2-tasks-more"
                        aria-label={`Acties voor ${task.title}`}
                        aria-expanded={open}
                        disabled={busy}
                        onClick={() => setMenuId(open ? null : task.taskId)}
                      >
                        ···
                      </button>
                      {open ? (
                        <div className="lv-v2-tasks-menu" role="menu">
                          {canCancelTask(task) ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                setMenuId(null);
                                onCancel(task);
                              }}
                            >
                              Stoppen
                            </button>
                          ) : null}
                          {canRetryTask(task) ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                setMenuId(null);
                                onRetry(task);
                              }}
                            >
                              Opnieuw proberen
                            </button>
                          ) : null}
                          {task.controls?.canChangePriority !== false ? (
                            <>
                              <button
                                type="button"
                                role="menuitem"
                                onClick={() => {
                                  setMenuId(null);
                                  onChangePriority(task, "high");
                                }}
                              >
                                Prioriteit: Hoog
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                onClick={() => {
                                  setMenuId(null);
                                  onChangePriority(task, "medium");
                                }}
                              >
                                Prioriteit: Normaal
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                onClick={() => {
                                  setMenuId(null);
                                  onChangePriority(task, "low");
                                }}
                              >
                                Prioriteit: Laag
                              </button>
                            </>
                          ) : null}
                          {task.controls?.canDuplicate !== false ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                setMenuId(null);
                                onDuplicate(task);
                              }}
                            >
                              Dupliceer
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function priorityClassName(priority: string | null | undefined): string {
  const p = (priority || "medium").toLowerCase();
  if (p === "high") return "lv-v2-tasks-badge--priority-high";
  if (p === "low") return "lv-v2-tasks-badge--priority-low";
  return "lv-v2-tasks-badge--priority-normal";
}
