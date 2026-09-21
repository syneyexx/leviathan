"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentsConsoleResponse,
  HadesAgent,
  NativeRuntimeStatus,
  SystemHealth,
  hadesApi,
} from "@/lib/hades-api";
import { hadesTrainingApi } from "@/lib/hades-training-api";
import {
  MetricRange,
  MetricSample,
  buildDonutSlices,
  factNumber,
  factString,
  pushSample,
  samplesForRange,
} from "./dashboard-live-utils";

const METRICS_POLL_MS = 2000;
const HEALTH_POLL_MS = 8000;
const AGENTS_POLL_MS = 4000;
const HARDWARE_POLL_MS = 3000;

export type DashboardLiveState = {
  health: SystemHealth | null;
  native: NativeRuntimeStatus | null;
  agents: HadesAgent[];
  agentsSummary: AgentsConsoleResponse["summary"] | null;
  activity: AgentsConsoleResponse["activity"];
  metricsAvailable: boolean;
  hostname: string | null;
  osLabel: string | null;
  cpuPercent: number | null;
  ramUsedBytes: number | null;
  ramTotalBytes: number | null;
  ramPercent: number | null;
  gpuPercent: number | null;
  vramUsedBytes: number | null;
  vramTotalBytes: number | null;
  vramPercent: number | null;
  gpuName: string | null;
  uptimeMs: number | null;
  history: MetricSample[];
  range: MetricRange;
  setRange: (range: MetricRange) => void;
  rangeHistory: MetricSample[];
  donut: ReturnType<typeof buildDonutSlices>;
  loading: boolean;
  lastError: string | null;
  refresh: () => void;
};

function readGpuFromHardware(hw: Awaited<ReturnType<typeof hadesTrainingApi.hardware>> | null) {
  const gpu = (hw?.gpu || {}) as Record<string, unknown>;
  const total = factNumber(gpu.total_vram_bytes);
  const free = factNumber(gpu.free_vram_bytes);
  const used = total != null && free != null ? Math.max(0, total - free) : null;
  const util = factNumber(gpu.gpu_utilization_percent);
  const vramUtil = factNumber(gpu.vram_utilization_percent);
  const percent =
    vramUtil != null
      ? vramUtil
      : total && used != null
        ? (used / total) * 100
        : null;
  return {
    gpuPercent: util,
    vramUsedBytes: used,
    vramTotalBytes: total,
    vramPercent: percent,
    gpuName: factString(gpu.name),
  };
}

export function useDashboardLive(): DashboardLiveState {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [native, setNative] = useState<NativeRuntimeStatus | null>(null);
  const [agents, setAgents] = useState<HadesAgent[]>([]);
  const [agentsSummary, setAgentsSummary] = useState<AgentsConsoleResponse["summary"] | null>(null);
  const [activity, setActivity] = useState<AgentsConsoleResponse["activity"]>([]);
  const [metricsAvailable, setMetricsAvailable] = useState(false);
  const [hostname, setHostname] = useState<string | null>(null);
  const [osLabel, setOsLabel] = useState<string | null>(null);
  const [cpuPercent, setCpuPercent] = useState<number | null>(null);
  const [ramUsedBytes, setRamUsedBytes] = useState<number | null>(null);
  const [ramTotalBytes, setRamTotalBytes] = useState<number | null>(null);
  const [ramPercent, setRamPercent] = useState<number | null>(null);
  const [gpuPercent, setGpuPercent] = useState<number | null>(null);
  const [vramUsedBytes, setVramUsedBytes] = useState<number | null>(null);
  const [vramTotalBytes, setVramTotalBytes] = useState<number | null>(null);
  const [vramPercent, setVramPercent] = useState<number | null>(null);
  const [gpuName, setGpuName] = useState<string | null>(null);
  const [uptimeMs, setUptimeMs] = useState<number | null>(null);
  const [history, setHistory] = useState<MetricSample[]>([]);
  const [range, setRange] = useState<MetricRange>("1h");
  const [loading, setLoading] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);
  const gpuRef = useRef({ gpuPercent: null as number | null, vramPercent: null as number | null });

  const applyMetrics = useCallback((metrics: Record<string, unknown> | null | undefined, available: boolean) => {
    setMetricsAvailable(available || Boolean(metrics));
    if (!metrics) return;
    const cpu = typeof metrics.cpu_percent === "number" ? metrics.cpu_percent : null;
    const memory = (metrics.memory || null) as Record<string, unknown> | null;
    const total = typeof memory?.total_bytes === "number" ? memory.total_bytes : null;
    const used = typeof memory?.used_bytes === "number" ? memory.used_bytes : null;
    const availableBytes = typeof memory?.available_bytes === "number" ? memory.available_bytes : null;
    const usedBytes = used ?? (total != null && availableBytes != null ? total - availableBytes : null);
    const ramPct = total && usedBytes != null ? (usedBytes / total) * 100 : null;
    setCpuPercent(cpu);
    setRamTotalBytes(total);
    setRamUsedBytes(usedBytes);
    setRamPercent(ramPct);
    if (typeof metrics.uptime_ms === "number") setUptimeMs(metrics.uptime_ms);
    if (typeof metrics.hostname === "string") setHostname(metrics.hostname);
    if (typeof metrics.os === "string") setOsLabel(metrics.os);

    const sample: MetricSample = {
      t: Date.now(),
      cpu,
      ram: ramPct,
      gpu: gpuRef.current.gpuPercent,
      vram: gpuRef.current.vramPercent,
    };
    setHistory((prev) => pushSample(prev, sample));
  }, []);

  const loadMetrics = useCallback(async () => {
    try {
      const [nativeStatus, metricsPayload] = await Promise.all([
        hadesApi.nativeStatus().catch(() => null),
        hadesApi.nativeMetrics().catch(() => null),
      ]);
      if (nativeStatus) {
        setNative(nativeStatus);
        if (typeof nativeStatus.uptime_ms === "number") setUptimeMs(nativeStatus.uptime_ms);
      }
      applyMetrics(metricsPayload?.metrics || null, Boolean(metricsPayload?.available || metricsPayload?.metrics));
      setLastError(null);
    } catch (reason) {
      setLastError(reason instanceof Error ? reason.message : "Metrics onbereikbaar");
    }
  }, [applyMetrics]);

  const loadHealth = useCallback(async () => {
    try {
      const next = await hadesApi.health();
      setHealth(next);
      setLastError(null);
    } catch (reason) {
      setHealth(null);
      setLastError(reason instanceof Error ? reason.message : "Health onbereikbaar");
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const next = await hadesApi.agents();
      setAgents(next.items || []);
      setAgentsSummary(next.summary || null);
      setActivity(next.activity || []);
    } catch {
      // Keep last good agents snapshot.
    }
  }, []);

  const loadHardware = useCallback(async () => {
    try {
      const hw = await hadesTrainingApi.hardware();
      const gpu = readGpuFromHardware(hw);
      gpuRef.current = { gpuPercent: gpu.gpuPercent, vramPercent: gpu.vramPercent };
      setGpuPercent(gpu.gpuPercent);
      setVramUsedBytes(gpu.vramUsedBytes);
      setVramTotalBytes(gpu.vramTotalBytes);
      setVramPercent(gpu.vramPercent);
      setGpuName(gpu.gpuName);
      const host = (hw.host || {}) as Record<string, unknown>;
      const platform = factString(host.platform_system);
      if (platform && !osLabel) setOsLabel(platform);
    } catch {
      // GPU optional when nvidia-smi / training path unavailable.
    }
  }, [osLabel]);

  const refresh = useCallback(() => {
    void Promise.all([loadMetrics(), loadHealth(), loadAgents(), loadHardware()]).finally(() => setLoading(false));
  }, [loadAgents, loadHardware, loadHealth, loadMetrics]);

  useEffect(() => {
    refresh();
    const metricsId = window.setInterval(() => void loadMetrics(), METRICS_POLL_MS);
    const healthId = window.setInterval(() => void loadHealth(), HEALTH_POLL_MS);
    const agentsId = window.setInterval(() => void loadAgents(), AGENTS_POLL_MS);
    const hardwareId = window.setInterval(() => void loadHardware(), HARDWARE_POLL_MS);
    return () => {
      window.clearInterval(metricsId);
      window.clearInterval(healthId);
      window.clearInterval(agentsId);
      window.clearInterval(hardwareId);
    };
  }, [loadAgents, loadHardware, loadHealth, loadMetrics, refresh]);

  const rangeHistory = samplesForRange(history, range);

  const donutCounts: Record<string, number> = {};
  for (const agent of agents) {
    const key = (agent.type || agent.role || "Overig").trim() || "Overig";
    donutCounts[key] = (donutCounts[key] || 0) + 1;
  }

  return {
    health,
    native,
    agents,
    agentsSummary,
    activity,
    metricsAvailable,
    hostname,
    osLabel,
    cpuPercent,
    ramUsedBytes,
    ramTotalBytes,
    ramPercent,
    gpuPercent,
    vramUsedBytes,
    vramTotalBytes,
    vramPercent,
    gpuName,
    uptimeMs,
    history,
    range,
    setRange,
    rangeHistory,
    donut: buildDonutSlices(donutCounts),
    loading,
    lastError,
    refresh,
  };
}
