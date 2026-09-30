import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useSystemTelemetry } from "./useSystemTelemetry";
import type {
  AgentDefinition,
  TaskAgentActivity,
  TaskEvent,
  TaskRecord,
  TaskSummary,
} from "../types/api";
import {
  clientTimezone,
  errMsg,
  mapTaskListFilters,
} from "../pages/tasks/taskUtils";

const POLL_MS = 5500;
const SEARCH_DEBOUNCE_MS = 250;

export type TasksWorkspace = ReturnType<typeof useTasksWorkspace>;

/**
 * Taken / Tasks workspace — projects TaskService state into the V2 Taken page.
 * No parallel task store; polling reuses existing /api/tasks* contracts.
 */
export function useTasksWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tz = useMemo(() => clientTimezone(), []);
  const selectedId = searchParams.get("task");

  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [summary, setSummary] = useState<TaskSummary | null>(null);
  const [activity, setActivity] = useState<TaskEvent[]>([]);
  const [agentActivity, setAgentActivity] = useState<TaskAgentActivity[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("all");
  const [status, setStatus] = useState("all");
  const [type, setType] = useState("all");
  const [assignee, setAssignee] = useState("all");

  const loadGen = useRef(0);
  const inFlight = useRef(false);
  const telemetry = useSystemTelemetry({ enabled: true, intervalMs: 4000 });

  useEffect(() => {
    const id = window.setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [searchInput]);

  const selectTask = useCallback(
    (taskId: string | null) => {
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

  const loadAll = useCallback(
    async (opts?: { silent?: boolean; selectedTaskId?: string | null }) => {
      if (inFlight.current && opts?.silent) return;
      const gen = ++loadGen.current;
      inFlight.current = true;
      if (!opts?.silent) {
        if (tasks.length === 0) setLoading(true);
        else setRefreshing(true);
      }
      try {
        const listFilters = mapTaskListFilters({
          search,
          priority,
          status,
          type,
          assignee,
          timezone: tz,
        });
        const sel = opts?.selectedTaskId ?? selectedId;

        const [taskRes, sumRes, actRes, agActRes, agentRes] = await Promise.all([
          api.listTasks({ ...listFilters, limit: 200, offset: 0 }),
          api.taskSummary(tz),
          api.taskActivity({ limit: 40 }),
          api.taskAgentActivity(20),
          api.listAgents({ includeArchived: false }),
        ]);

        if (gen !== loadGen.current) return;

        let nextTasks = taskRes.tasks ?? [];
        if (sel && !nextTasks.some((t) => t.taskId === sel)) {
          try {
            const one = await api.getTask(sel);
            if (gen !== loadGen.current) return;
            if (one.task) nextTasks = [one.task, ...nextTasks];
          } catch {
            /* selection may be archived / missing */
          }
        }

        setTasks(nextTasks);
        setSummary(sumRes.summary);
        setActivity(actRes.activity ?? []);
        setAgentActivity(agActRes.agents ?? []);
        setAgents((agentRes.agents ?? []).filter((a) => !a.archived && a.enabled));
        setLoadError(null);
        setStale(false);
      } catch (err) {
        if (gen !== loadGen.current) return;
        const msg = errMsg(err, "Taken laden mislukt");
        if (opts?.silent && tasks.length > 0) {
          setStale(true);
        } else {
          setLoadError(msg);
        }
      } finally {
        if (gen === loadGen.current) {
          setLoading(false);
          setRefreshing(false);
          inFlight.current = false;
        }
      }
    },
    [search, priority, status, type, assignee, tz, selectedId, tasks.length],
  );

  useEffect(() => {
    const id = window.setTimeout(() => {
      void loadAll({ silent: false, selectedTaskId: selectedId });
    }, 0);
    const poll = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void loadAll({ silent: true, selectedTaskId: selectedId });
    }, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") {
        void loadAll({ silent: true, selectedTaskId: selectedId });
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearTimeout(id);
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", onVis);
      loadGen.current += 1;
    };
  }, [loadAll, selectedId]);

  const selected = useMemo(
    () => (selectedId ? tasks.find((t) => t.taskId === selectedId) ?? null : null),
    [tasks, selectedId],
  );

  const refresh = useCallback(() => {
    void loadAll({ silent: false, selectedTaskId: selectedId });
  }, [loadAll, selectedId]);

  const runAction = useCallback(
    async (label: string, fn: () => Promise<unknown>) => {
      if (actionBusy) return;
      setActionBusy(true);
      try {
        await fn();
        await loadAll({ silent: true, selectedTaskId: selectedId });
        return { ok: true as const, label };
      } catch (err) {
        return { ok: false as const, label, error: errMsg(err, `${label} mislukt`) };
      } finally {
        setActionBusy(false);
      }
    },
    [actionBusy, loadAll, selectedId],
  );

  const cancelTask = useCallback(
    (task: TaskRecord) => runAction("Stoppen", () => api.cancelTask(task.taskId)),
    [runAction],
  );

  const retryTask = useCallback(
    (task: TaskRecord) => runAction("Opnieuw", () => api.retryTask(task.taskId)),
    [runAction],
  );

  const duplicateTask = useCallback(
    async (task: TaskRecord) => {
      const result = await runAction("Dupliceren", async () => {
        const res = await api.duplicateTask(task.taskId);
        selectTask(res.task.taskId);
        return res;
      });
      return result;
    },
    [runAction, selectTask],
  );

  const changePriority = useCallback(
    (task: TaskRecord, priorityValue: string) =>
      runAction("Prioriteit", () => api.updateTask(task.taskId, { priority: priorityValue })),
    [runAction],
  );

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const sample = telemetry.sample;
    const cpu = sample?.dashboard.cpuPct;
    const ram = sample?.dashboard.ramPct;
    const gpu = sample?.dashboard.gpuPct;
    const disk = sample?.dashboard.diskPct;
    const row = (
      id: string,
      label: string,
      value: number | null | undefined,
      available: boolean | undefined,
    ): SidebarStatusRow => {
      if (!sample) return { id, label, value: "…", tone: "muted" };
      if (available === false || value == null) {
        return { id, label, value: "UNAVAILABLE", tone: "muted" };
      }
      return {
        id,
        label,
        value: `${Math.round(value)}%`,
        tone: value > 85 ? "warning" : "success",
      };
    };
    return [
      row("cpu", "CPU", cpu, sample?.cpu?.available),
      row("ram", "RAM", ram, sample?.memory?.available),
      row("gpu", "GPU", gpu, sample?.gpu?.available),
      row("disk", "Disk", disk, sample?.disk?.available),
    ];
  }, [telemetry.sample]);

  const typeOptions = useMemo(() => {
    const counts = summary?.typeCounts ?? {};
    return Object.keys(counts).sort();
  }, [summary]);

  return {
    tasks,
    summary,
    activity,
    agentActivity,
    agents,
    selected,
    selectedId,
    loading,
    refreshing,
    loadError,
    stale,
    actionBusy,
    createOpen,
    setCreateOpen,
    searchInput,
    setSearchInput,
    priority,
    setPriority,
    status,
    setStatus,
    type,
    setType,
    assignee,
    setAssignee,
    typeOptions,
    selectTask,
    refresh,
    cancelTask,
    retryTask,
    duplicateTask,
    changePriority,
    runAction,
    telemetry,
    sidebarStatus,
    online: loadError ? false : true,
    timezone: tz,
    onCreated: () => void loadAll({ silent: true, selectedTaskId: selectedId }),
  };
}
