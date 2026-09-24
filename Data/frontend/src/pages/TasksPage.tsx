import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  AgentDefinition,
  TaskAgentActivity,
  TaskBoardColumn,
  TaskEvent,
  TaskRecord,
  TaskSummary,
  TaskTimelineItem,
  TaskWeekdayCompletions,
  TaskWorkloadEntry,
} from "../types/api";
import "../styles/tasks-reference.css";
import { TaskAutoPlanDialog } from "./tasks/TaskAutoPlanDialog";
import { TaskBoard } from "./tasks/TaskBoard";
import { type TaskCardAction } from "./tasks/TaskCard";
import { TaskCreateDialog } from "./tasks/TaskCreateDialog";
import { TaskDetails } from "./tasks/TaskDetails";
import { TaskBottomPanels } from "./tasks/TaskBottomPanels";
import { IconBolt, IconMore, IconPlus, IconSearch, IconSparkle, KpiIcon } from "./tasks/TaskIcons";
import { TaskQuickCapture } from "./tasks/TaskQuickCapture";
import {
  clientTimezone,
  errMsg,
  mapTaskListFilters,
} from "./tasks/taskUtils";

const POLL_MS = 5500;

type KpiDef = {
  id: string;
  label: string;
  value: string;
  icon: "layers" | "progress" | "warning" | "check" | "clock" | "robot";
  tone: "cyan" | "blue" | "red" | "green" | "orange";
  delta?: string;
};

/**
 * Taken — Mission Control workspace for tasks, agents, and execution.
 * Production data via /api/tasks*; visual identity from tasks-reference.css.
 */
export function TasksPage() {
  const toast = useAppToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const tz = useMemo(() => clientTimezone(), []);

  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [summary, setSummary] = useState<TaskSummary | null>(null);
  const [activity, setActivity] = useState<TaskEvent[]>([]);
  const [timeline, setTimeline] = useState<TaskTimelineItem[]>([]);
  const [workload, setWorkload] = useState<TaskWorkloadEntry[]>([]);
  const [weekday, setWeekday] = useState<TaskWeekdayCompletions | null>(null);
  const [agentActivity, setAgentActivity] = useState<TaskAgentActivity[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("all-priorities");
  const [status, setStatus] = useState("all-statuses");
  const [assignee, setAssignee] = useState("all-assignees");
  const [datePreset, setDatePreset] = useState("week");
  const [timelineView, setTimelineView] = useState<"today" | "week" | "calendar">("today");

  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("task"));
  const [createOpen, setCreateOpen] = useState(false);
  const [createColumn, setCreateColumn] = useState<string>("backlog");
  const [quickOpen, setQuickOpen] = useState(false);
  const [autoOpen, setAutoOpen] = useState(false);

  const loadGen = useRef(0);
  const filtersRef = useRef({ search, priority, status, assignee, datePreset, timelineView });
  filtersRef.current = { search, priority, status, assignee, datePreset, timelineView };
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const notifyError = useCallback(
    (message: string) => {
      toast(message);
    },
    [toast],
  );

  const notifySuccess = useCallback(
    (message: string) => {
      toast(message);
    },
    [toast],
  );

  const loadAll = useCallback(async (opts?: { silent?: boolean }) => {
    const gen = ++loadGen.current;
    const f = filtersRef.current;
    if (!opts?.silent) setLoading(true);
    try {
      const listFilters = mapTaskListFilters({
        search: f.search,
        priority: f.priority,
        status: f.status,
        assignee: f.assignee,
        datePreset: f.datePreset,
        timezone: tz,
      });
      const timelineApiView = f.timelineView === "calendar" ? "calendar" : f.timelineView;

      const [taskRes, sumRes, actRes, tlRes, wlRes, wdRes, agActRes, agentRes] = await Promise.all([
        api.listTasks({ ...listFilters, limit: 500 }),
        api.taskSummary(tz),
        api.taskActivity({ limit: 50 }),
        api.taskTimeline({ view: timelineApiView, timezone: tz }),
        api.taskWorkload(),
        api.taskWeekdayCompletions(tz),
        api.taskAgentActivity(20),
        api.listAgents({ includeArchived: false }),
      ]);

      if (gen !== loadGen.current) return;

      setTasks(taskRes.tasks ?? []);
      setSummary(sumRes.summary);
      setActivity(actRes.activity ?? []);
      setTimeline(tlRes.timeline ?? []);
      setWorkload(wlRes.workload ?? []);
      setWeekday(wdRes);
      setAgentActivity(agActRes.agents ?? []);
      setAgents((agentRes.agents ?? []).filter((a) => !a.archived && a.enabled));
      setError(null);

      const sel = selectedIdRef.current;
      if (sel && !(taskRes.tasks ?? []).some((t) => t.taskId === sel)) {
        // Keep selection if deep-linked but filtered out — try fetch single
        try {
          const one = await api.getTask(sel);
          if (gen !== loadGen.current) return;
          if (one.task) {
            setTasks((prev) => (prev.some((t) => t.taskId === sel) ? prev : [one.task, ...prev]));
          }
        } catch {
          /* selection may be archived / missing — leave as-is */
        }
      }
    } catch (err) {
      if (gen !== loadGen.current) return;
      const msg = errMsg(err, "Failed to load tasks");
      setError(msg);
      if (!opts?.silent) toast(msg);
    } finally {
      if (gen === loadGen.current) setLoading(false);
    }
  }, [tz, toast]);

  useEffect(() => {
    void loadAll();
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void loadAll({ silent: true });
    }, POLL_MS);
    return () => {
      window.clearInterval(id);
      loadGen.current += 1;
    };
  }, [loadAll]);

  // Debounce filter-driven reload (keeps form state; cancels stale via loadGen)
  useEffect(() => {
    const id = window.setTimeout(() => {
      void loadAll({ silent: true });
    }, 250);
    return () => window.clearTimeout(id);
  }, [search, priority, status, assignee, datePreset, timelineView, loadAll]);

  useEffect(() => {
    const fromUrl = searchParams.get("task");
    if (fromUrl && fromUrl !== selectedId) setSelectedId(fromUrl);
  }, [searchParams, selectedId]);

  const selectTask = useCallback(
    (taskId: string | null) => {
      setSelectedId(taskId);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (taskId) next.set("task", taskId);
          else next.delete("task");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const selected = useMemo(
    () => (selectedId ? tasks.find((t) => t.taskId === selectedId) ?? null : null),
    [tasks, selectedId],
  );

  const kpis: KpiDef[] = useMemo(() => {
    const s = summary;
    return [
      {
        id: "active",
        label: "Active Tasks",
        value: s ? String(s.active) : "—",
        icon: "layers",
        tone: "cyan",
      },
      {
        id: "progress",
        label: "In Progress",
        value: s ? String(s.inProgress) : "—",
        icon: "progress",
        tone: "blue",
      },
      {
        id: "blocked",
        label: "Blocked",
        value: s ? String(s.blocked) : "—",
        icon: "warning",
        tone: "red",
      },
      {
        id: "completed",
        label: "Completed Today",
        value: s ? String(s.completedToday) : "—",
        icon: "check",
        tone: "green",
        delta: s?.completedTodayDelta ?? undefined,
      },
      {
        id: "overdue",
        label: "Overdue",
        value: s ? String(s.overdue) : "—",
        icon: "clock",
        tone: "orange",
      },
      {
        id: "agents",
        label: "AI Agents Assigned",
        value: s ? String(s.agentsAssigned) : "—",
        icon: "robot",
        tone: "cyan",
      },
    ];
  }, [summary]);

  const runAction = useCallback(
    async (label: string, fn: () => Promise<unknown>) => {
      setActionBusy(true);
      try {
        await fn();
        toast(`${label} ok`);
        await loadAll({ silent: true });
      } catch (err) {
        toast(errMsg(err, `${label} failed`));
      } finally {
        setActionBusy(false);
      }
    },
    [loadAll, toast],
  );

  const onCardAction = useCallback(
    (action: TaskCardAction, task: TaskRecord, boardColumn?: TaskBoardColumn) => {
      if (action === "open") {
        selectTask(task.taskId);
        return;
      }
      void runAction(action, async () => {
        if (action === "move" && boardColumn) {
          await api.updateTask(task.taskId, { boardColumn });
        } else if (action === "start") {
          await api.startTask(task.taskId);
        } else if (action === "cancel") {
          await api.cancelTask(task.taskId);
        } else if (action === "retry") {
          await api.retryTask(task.taskId);
        } else if (action === "duplicate") {
          const res = await api.duplicateTask(task.taskId);
          selectTask(res.task.taskId);
        } else if (action === "archive") {
          await api.archiveTask(task.taskId);
          if (selectedIdRef.current === task.taskId) selectTask(null);
        } else if (action === "complete") {
          await api.updateTask(task.taskId, { boardColumn: "done", progress: 1 });
        }
      });
    },
    [runAction, selectTask],
  );

  return (
    <AppShell activeMode="explore" searchPlaceholder="Zoek taken, jobs, approvals...">
      <main className="lv-main lv-tasks-page">
        <header className="lv-tasks-hero">
          <div className="lv-tasks-hero-left">
            <div className="lv-tasks-hero-title-row">
              <h1 className="lv-tasks-hero-title">TAKEN</h1>
              <p className="lv-tasks-hero-subtitle">Mission Control for Tasks, Agents, and Execution</p>
            </div>
            <p className="lv-tasks-hero-quote">“Ideas mean nothing. Execution is everything.” — LEVIATHAN</p>
          </div>
          <div className="lv-tasks-hero-right">
            Discipline turns
            <br />
            intention into freedom.
            <br />— Leviathan
          </div>
        </header>

        <section className="lv-tasks-kpis" aria-label="Task KPIs">
          {kpis.map((kpi) => (
            <article key={kpi.id} className="lv-tasks-kpi">
              <div className={`lv-tasks-kpi-icon lv-tasks-kpi-icon--${kpi.tone}`}>
                <KpiIcon type={kpi.icon} />
              </div>
              <div className="lv-tasks-kpi-body">
                <span className="lv-tasks-kpi-label">{kpi.label}</span>
                <div className="lv-tasks-kpi-value-row">
                  <span className="lv-tasks-kpi-value">{kpi.value}</span>
                  {kpi.delta ? <span className="lv-tasks-kpi-delta">{kpi.delta}</span> : null}
                </div>
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tasks-toolbar" aria-label="Task filters">
          <div className="lv-tasks-toolbar-left">
            <label className="lv-tasks-search">
              <IconSearch />
              <input
                type="search"
                placeholder="Search tasks..."
                aria-label="Search tasks"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <select
              className="lv-tasks-select"
              value={priority}
              aria-label="Priority filter"
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="all-priorities">All Priorities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <select
              className="lv-tasks-select"
              value={status}
              aria-label="Status filter"
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="all-statuses">All Statuses</option>
              <option value="backlog">Backlog</option>
              <option value="in_progress">In Progress</option>
              <option value="review">Review</option>
              <option value="done">Done</option>
            </select>
            <select
              className="lv-tasks-select"
              value={assignee}
              aria-label="Assignee filter"
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="all-assignees">All Assignees</option>
              {agents.map((a) => (
                <option key={a.agentId} value={a.agentId}>
                  {a.name}
                </option>
              ))}
            </select>
            <select
              className="lv-tasks-select lv-tasks-select--date"
              value={datePreset}
              aria-label="Date range"
              onChange={(e) => setDatePreset(e.target.value)}
            >
              <option value="week">Today - This Week</option>
              <option value="today">Today</option>
              <option value="month">This Month</option>
            </select>
          </div>
          <div className="lv-tasks-toolbar-right">
            <button
              type="button"
              className="lv-tasks-btn lv-tasks-btn--gold"
              onClick={() => {
                setCreateColumn("backlog");
                setCreateOpen(true);
              }}
            >
              <IconPlus />
              New Task
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" onClick={() => setQuickOpen(true)}>
              <IconBolt />
              Quick Capture
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" onClick={() => setAutoOpen(true)}>
              <IconSparkle />
              Auto-Plan
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--ghost" aria-label="More actions" disabled>
              <IconMore />
            </button>
          </div>
        </section>

        {error ? (
          <div className="lv-tasks-banner lv-tasks-banner--error" role="alert">
            <span>{error}</span>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" onClick={() => void loadAll()}>
              Retry
            </button>
          </div>
        ) : null}

        {loading && tasks.length === 0 ? (
          <div className="lv-tasks-banner lv-tasks-banner--loading">Loading tasks…</div>
        ) : null}

        {!loading && !error && tasks.length === 0 ? (
          <div className="lv-tasks-banner lv-tasks-banner--empty">Geen taken</div>
        ) : null}

        <section className="lv-tasks-workspace" aria-label="Task workspace">
          <TaskBoard
            tasks={tasks}
            columnCounts={summary?.columnCounts}
            selectedId={selectedId}
            busy={actionBusy}
            onSelect={selectTask}
            onAction={onCardAction}
            onAddColumn={(col) => {
              setCreateColumn(col);
              setCreateOpen(true);
            }}
          />
          {selected ? (
            <TaskDetails
              task={selected}
              agents={agents}
              allTasks={tasks}
              busy={actionBusy}
              onClose={() => selectTask(null)}
              onRefresh={() => void loadAll({ silent: true })}
              onError={notifyError}
              onSuccess={notifySuccess}
              onAssign={(task, agentId) => {
                const agent = agents.find((a) => a.agentId === agentId);
                void runAction("Assign", () =>
                  api.updateTask(task.taskId, {
                    assigneeType: agent ? "agent" : "none",
                    assigneeId: agent?.agentId ?? null,
                    assigneeName: agent?.name ?? null,
                  }),
                );
              }}
              onStart={(task) => void runAction("Start", () => api.startTask(task.taskId))}
              onCancel={(task) => void runAction("Cancel", () => api.cancelTask(task.taskId))}
              onComplete={(task) =>
                void runAction("Complete", () => api.updateTask(task.taskId, { boardColumn: "done", progress: 1 }))
              }
            />
          ) : null}
        </section>

        <TaskBottomPanels
          timeline={timeline}
          timelineView={timelineView}
          onTimelineView={setTimelineView}
          agentActivity={agentActivity}
          activity={activity}
          weekday={weekday}
          workload={workload}
          onSelectTask={selectTask}
        />
      </main>

      <TaskCreateDialog
        open={createOpen}
        agents={agents}
        defaultBoardColumn={createColumn}
        onClose={() => setCreateOpen(false)}
        onCreated={() => void loadAll({ silent: true })}
        onError={notifyError}
        onSuccess={notifySuccess}
      />
      <TaskQuickCapture
        open={quickOpen}
        agents={agents}
        onClose={() => setQuickOpen(false)}
        onCreated={() => void loadAll({ silent: true })}
        onError={notifyError}
        onSuccess={notifySuccess}
      />
      <TaskAutoPlanDialog
        open={autoOpen}
        onClose={() => setAutoOpen(false)}
        onCommitted={() => void loadAll({ silent: true })}
        onError={notifyError}
        onSuccess={notifySuccess}
      />
    </AppShell>
  );
}
