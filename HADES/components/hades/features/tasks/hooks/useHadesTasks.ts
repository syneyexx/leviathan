"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type HadesTask, type TaskEvent, type WorkSummary } from "@/lib/hades-api";

const TASKS_KEY = "hades:tasks";

export function useHadesTasks() {
  const query = useHadesQuery(
    TASKS_KEY,
    async () => {
      const tasks = await hadesApi.tasks();
      return Array.isArray(tasks) ? tasks : [];
    },
    { staleTime: 4_000, refetchInterval: 8_000 },
  );

  const tasks = query.data ?? [];

  const byStatus = useMemo(() => {
    const buckets: Record<string, HadesTask[]> = {
      pending: [],
      running: [],
      paused: [],
      completed: [],
      failed: [],
      cancelled: [],
      other: [],
    };
    for (const task of tasks) {
      const status = String(task.status || "other").toLowerCase();
      if (status in buckets) buckets[status].push(task);
      else buckets.other.push(task);
    }
    return buckets;
  }, [tasks]);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(TASKS_KEY);
    return query.refetch();
  }, [query]);

  const create = useCallback(
    async (values: {
      title: string;
      prompt: string;
      agent: string;
      priority: HadesTask["priority"];
      model_id?: string;
      auto_start: boolean;
      schedule?: Record<string, unknown>;
    }) => {
      const task = await hadesApi.createTask(values);
      await refresh();
      return task;
    },
    [refresh],
  );

  const run = useCallback(
    async (id: string) => {
      const task = await hadesApi.runTask(id);
      await refresh();
      return task;
    },
    [refresh],
  );

  const cancel = useCallback(
    async (id: string) => {
      const task = await hadesApi.cancelTask(id);
      await refresh();
      return task;
    },
    [refresh],
  );

  const retry = useCallback(
    async (id: string) => {
      const task = await hadesApi.retryTask(id);
      await refresh();
      return task;
    },
    [refresh],
  );

  const control = useCallback(
    async (
      id: string,
      body: {
        action: "pause" | "resume" | "redirect" | "retry_step" | "status";
        plan_version?: number;
        instruction?: string;
        step_id?: string;
      },
    ) => {
      const result = await hadesApi.controlTask(id, body);
      await refresh();
      return result;
    },
    [refresh],
  );

  const loadEvents = useCallback(async (id: string): Promise<TaskEvent[]> => hadesApi.taskEvents(id), []);
  const loadWork = useCallback(async (id: string): Promise<WorkSummary> => hadesApi.taskWork(id), []);

  return {
    tasks,
    byStatus,
    loading: query.status === "loading" && !query.data,
    error: query.error,
    refresh,
    create,
    run,
    cancel,
    retry,
    control,
    loadEvents,
    loadWork,
  };
}
