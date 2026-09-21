"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi } from "@/lib/hades-api";
import { useDashboardLive } from "@/components/hades/finalbeta/hooks/use-dashboard-live";

const KEY = "hades:llm-stats";

export function useHadesLlmStats() {
  const dash = useDashboardLive();
  const query = useHadesQuery(
    KEY,
    async () => {
      const [models, gateway, agents, tasks] = await Promise.all([
        hadesApi.models().catch(() => null),
        hadesApi.modelGateway().catch(() => null),
        hadesApi.agents().catch(() => null),
        hadesApi.tasks().catch(() => null),
      ]);
      return { models, gateway, agents, tasks };
    },
    { staleTime: 5_000, refetchInterval: 12_000 },
  );

  const refresh = useCallback(async () => {
    invalidateHadesQuery(KEY);
    dash.refresh();
    return query.refetch();
  }, [query, dash]);

  const modelRows = useMemo(() => {
    const items = query.data?.models?.models || [];
    const active = query.data?.models?.active_model_id;
    return items.map((m) => ({
      id: m.id,
      name: m.id,
      status: m.id === active ? "Actief" : "Beschikbaar",
      requests: "—",
      latency:
        typeof query.data?.models?.latency_ms === "number"
          ? `${Math.round(query.data.models.latency_ms)} ms`
          : "—",
      success: null as number | null,
    }));
  }, [query.data]);

  const agentRows = useMemo(() => {
    const items = query.data?.agents?.agents || [];
    return items.map((a) => ({
      id: a.id,
      name: a.name || a.id,
      status: a.enabled ? (a.status || "idle") : "disabled",
      health: a.health || "—",
      enabled: Boolean(a.enabled),
    }));
  }, [query.data]);

  const taskSlices = useMemo(() => {
    const tasks = query.data?.tasks?.tasks || [];
    const counts = { open: 0, running: 0, done: 0, failed: 0 };
    for (const t of tasks) {
      const s = String(t.status || "").toLowerCase();
      if (s === "running" || s === "queued") counts.running += 1;
      else if (s === "completed") counts.done += 1;
      else if (s === "failed" || s === "cancelled") counts.failed += 1;
      else counts.open += 1;
    }
    return [
      { label: "Open", count: counts.open, color: "#1aa4ff" },
      { label: "Running", count: counts.running, color: "#f0b429" },
      { label: "Done", count: counts.done, color: "#20e38d" },
      { label: "Failed", count: counts.failed, color: "#e85b5b" },
    ];
  }, [query.data]);

  const gateway = query.data?.gateway?.gateway;
  const kpis = useMemo(
    () => [
      {
        id: "models",
        label: "Modellen",
        value: String(query.data?.models?.models?.length ?? dash.health?.models ?? "—"),
        tone: "cyan",
        icon: "database",
      },
      {
        id: "lm",
        label: "LM Studio",
        value: dash.health?.lm_studio === "connected" ? "Online" : "Offline",
        tone: dash.health?.lm_studio === "connected" ? "green" : "gold",
        icon: "bolt",
      },
      {
        id: "agents",
        label: "Agents",
        value: String(query.data?.agents?.agents?.length ?? dash.agents.length),
        tone: "blue",
        icon: "users",
      },
      {
        id: "active",
        label: "Actieve calls",
        value: String(gateway?.active_count ?? "—"),
        tone: "purple",
        icon: "activity",
      },
      {
        id: "queue",
        label: "Queue depth",
        value: String(gateway?.queue_depth ?? "—"),
        tone: "gold",
        icon: "list",
      },
      {
        id: "cpu",
        label: "CPU",
        value: typeof dash.cpuPercent === "number" ? `${Math.round(dash.cpuPercent)}%` : "—",
        tone: "cyan",
        icon: "bolt",
        progress: dash.cpuPercent ?? undefined,
      },
    ],
    [query.data, dash, gateway],
  );

  const history = dash.rangeHistory.length ? dash.rangeHistory : dash.history;
  const perfSeries = {
    cpu: history.map((s) => s.cpu),
    ram: history.map((s) => s.ram),
    gpu: history.map((s) => s.gpu),
    vram: history.map((s) => s.vram),
  };

  return {
    kpis,
    modelRows,
    agentRows,
    taskSlices,
    perfSeries,
    gateway,
    health: dash.health,
    loading: (query.status === "loading" && !query.data) || dash.loading,
    error: query.error?.message || dash.lastError,
    refresh,
    activeModel: query.data?.models?.active_model_id || dash.health?.active_model || null,
  };
}
