import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import {
  clampPct,
  deriveTasksPerHour,
  domainBadgeTone,
  extractUptimeLabel,
  formatBytes,
  formatDuration,
  formatPct,
  normalizeLmStudioStatus,
  normalizeSystemStatus,
  researchStatusTone,
  workerStateTone,
  type BadgeTone,
  type StatusTone,
} from "../lib/dashboardNormalize";
import { useSystemTelemetry } from "./useSystemTelemetry";
import type {
  AgentFleetSummary,
  HealthResponse,
  HostOverviewResponse,
  HostSourceIngestionResponse,
  MarketBarsResponse,
  MarketDataSource,
  MarketSimStatusResponse,
  MarketStrategy,
  ModelHardwareInventory,
  ModelProvider,
  ModelsStatus,
  ResearchProject,
  SystemTelemetryResponse,
  TaskEvent,
  TaskSummary,
  WorkerFabricDashboard,
  WorkerFabricJobSummary,
  WorkerFabricWorker,
} from "../types/api";

const WORKERS_INTERVAL_MS = 8_000;
const SLOW_INTERVAL_MS = 15_000;
const BARS_INTERVAL_MS = 30_000;
const TELEMETRY_STALE_MS = 8_000;

export type DashboardGauge = {
  pct: number | null;
  sublabel: string;
  available: boolean;
};

export type DashboardOverview = {
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  systemStatus: { label: string; tone: StatusTone; detail?: string; operational: boolean };
  agents: { active: number | null; total: number | null; delta: number | null; available: boolean };
  jobs: { active: number | null; queued: number | null; available: boolean };
  research: {
    activeCount: number | null;
    available: boolean;
    projects: Array<{
      id: string;
      title: string;
      subtitle: string;
      progress: number | null;
      status: string;
      statusTone: BadgeTone;
    }>;
  };
  trading: {
    activeStrategies: number | null;
    available: boolean;
    paper: boolean;
    instruments: Array<{
      symbol: string;
      price: number | null;
      changePct: number | null;
      side?: string;
      spark: number[];
      unavailable?: boolean;
    }>;
  };
  healthGauges: {
    cpu: DashboardGauge;
    ram: DashboardGauge;
    gpu: DashboardGauge;
    disk: DashboardGauge;
  };
  workers: Array<{
    id: string;
    name: string;
    domain: string;
    target: string;
    progress: number | null;
    progressLabel: string;
    tone: BadgeTone;
  }>;
  workersAvailable: boolean;
  queue: Array<{
    id: string;
    title: string;
    domain: string;
    tone: BadgeTone;
    progress: number | null;
    duration: string;
    to?: string;
  }>;
  activities: Array<{
    id: string;
    time: string;
    description: string;
    domain: string;
    tone: BadgeTone;
  }>;
  ingestion: {
    title: string;
    progress: number | null;
    detail: string;
    available: boolean;
  };
  gpuPanel: {
    devices: Array<{
      index: number;
      name: string;
      util: number | null;
      vramUsedBytes: number | null;
      vramTotalBytes: number | null;
      tempC: number | null;
      role?: string;
    }>;
    selectedIndex: number;
    setSelectedIndex: (index: number) => void;
  };
  performance: {
    tasksPerHour: number | null;
    avgProcessingMin: number | null;
    uptimeLabel: string | null;
    trends: {
      tasksPerHourDerived: boolean;
      avgProcessingAvailable: boolean;
      uptimeAvailable: boolean;
    };
  };
  sidebarStatus: Array<{
    id: string;
    label: string;
    value: string;
    tone: StatusTone;
  }>;
  telemetryStale: boolean;
  errors: Partial<Record<string, string>>;
};

type SettledErrors = Partial<Record<string, string>>;

function reasonMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function pickActiveWorkers(workers: WorkerFabricWorker[], max = 5): WorkerFabricWorker[] {
  const busyFirst = [...workers].sort((a, b) => {
    const score = (w: WorkerFabricWorker) => {
      const s = String(w.state || "").toLowerCase();
      if (s === "busy" || s === "running") return 0;
      if (s === "ready" || s === "idle") return 1;
      if (s === "degraded") return 2;
      return 3;
    };
    return score(a) - score(b);
  });
  return busyFirst.slice(0, max);
}

function workerDomain(w: WorkerFabricWorker): string {
  return (
    w.current_job?.domain ||
    w.pool_id ||
    w.supported_job_kinds?.[0] ||
    "system"
  );
}

function workerProgress(w: WorkerFabricWorker): {
  progress: number | null;
  progressLabel: string;
} {
  const pct = clampPct(w.progress_percent ?? w.current_job?.progress_percent ?? null);
  if (pct != null) {
    return { progress: pct, progressLabel: formatPct(pct, true) };
  }
  // Do not misuse cpu_percent as job progress.
  if (w.cpu_percent != null && Number.isFinite(w.cpu_percent)) {
    return { progress: null, progressLabel: `CPU ${formatPct(w.cpu_percent, true)}` };
  }
  return { progress: null, progressLabel: "UNMEASURED" };
}

function queueFromWorkers(dash: WorkerFabricDashboard | null, max = 5) {
  if (!dash) return [];
  const active: WorkerFabricJobSummary[] = [];
  for (const w of dash.workers) {
    if (w.current_job) active.push(w.current_job);
  }
  const queued = dash.queued_jobs ?? [];
  const merged = [...active, ...queued];
  const seen = new Set<string>();
  const out: DashboardOverview["queue"] = [];
  for (const job of merged) {
    const id = job.job_id || `${job.capability_id || "job"}-${out.length}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const domain = job.domain || job.worker_pool || "system";
    const progress = clampPct(job.progress_percent ?? job.progress ?? null);
    out.push({
      id,
      title: job.human_title || job.capability_id || id,
      domain,
      tone: domainBadgeTone(domain),
      progress,
      duration: job.elapsed_display || formatDuration(job.elapsed_seconds),
      to: "/tasks",
    });
    if (out.length >= max) break;
  }
  return out;
}

function researchActive(status: string): boolean {
  const s = status.toUpperCase();
  return ["RUNNING", "ACTIVE", "IN_PROGRESS", "PLANNING", "QUEUED", "PENDING"].includes(s);
}

function mapResearchProjects(projects: ResearchProject[]): DashboardOverview["research"]["projects"] {
  return projects.slice(0, 4).map((p) => ({
    id: p.project_id,
    title: p.title || p.topic || p.project_id,
    subtitle: p.phase || p.topic || p.objective || "—",
    progress: clampPct(p.progress_pct ?? null),
    status: p.status || "UNKNOWN",
    statusTone: researchStatusTone(p.status || "UNKNOWN"),
  }));
}

function formatActivityTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const d = new Date(t);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function activityDomain(ev: TaskEvent): string {
  const payload = ev.payload || {};
  const fromPayload =
    (typeof payload.domain === "string" && payload.domain) ||
    (typeof payload.kind === "string" && payload.kind) ||
    "";
  return fromPayload || ev.sourceType || ev.eventType || "system";
}

function buildGauge(
  pct: number | null | undefined,
  available: boolean,
  sublabelWhenAvailable: string,
): DashboardGauge {
  if (!available) {
    return { pct: null, sublabel: "N/A", available: false };
  }
  const clamped = clampPct(pct);
  return {
    pct: clamped,
    sublabel: clamped == null ? "UNMEASURED" : sublabelWhenAvailable,
    available: true,
  };
}

function diskSublabel(telemetry: SystemTelemetryResponse | null): string {
  const disk = telemetry?.disk;
  if (!disk?.available) return "N/A";
  const used = formatBytes(disk.usedBytes ?? null);
  const total = formatBytes(disk.totalBytes ?? null);
  if (used !== "—" && total !== "—") return `${used} / ${total}`;
  const free = formatBytes(disk.freeBytes ?? null);
  if (free !== "—") return `${free} free`;
  return "Disk";
}

function memorySublabel(telemetry: SystemTelemetryResponse | null): string {
  const mem = telemetry?.memory;
  if (!mem?.available) return "N/A";
  const used = formatBytes(mem.usedBytes);
  const total = formatBytes(mem.totalBytes);
  if (used !== "—" && total !== "—") return `${used} / ${total}`;
  return "RAM";
}

function resolveAgents(
  fleet: AgentFleetSummary | null,
  health: HealthResponse | null,
): DashboardOverview["agents"] {
  if (!fleet && health?.agents?.enabled === false) {
    return { active: 0, total: 0, delta: null, available: true };
  }
  if (!fleet) {
    return { active: null, total: null, delta: null, available: false };
  }
  const active =
    typeof fleet.active === "number"
      ? fleet.active
      : typeof fleet.busy === "number"
        ? fleet.busy
        : null;
  const total =
    typeof fleet.total === "number"
      ? fleet.total
      : typeof fleet.agentCount === "number"
        ? fleet.agentCount
        : typeof fleet.agents === "number"
          ? fleet.agents
          : null;
  return { active, total, delta: null, available: true };
}

function sparkFromBars(bars: MarketBarsResponse | null): {
  spark: number[];
  price: number | null;
  changePct: number | null;
  unavailable: boolean;
} {
  if (!bars || !bars.bars?.length) {
    const quotePrice = bars?.quote?.price ?? bars?.ohlc?.close ?? null;
    if (quotePrice != null && Number.isFinite(quotePrice)) {
      return { spark: [], price: quotePrice, changePct: null, unavailable: false };
    }
    return { spark: [], price: null, changePct: null, unavailable: true };
  }
  const closes = bars.bars
    .map((b) => b.close)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const spark = closes.slice(-24);
  const price =
    bars.quote?.price ??
    bars.ohlc?.close ??
    (closes.length ? closes[closes.length - 1] : null);
  let changePct: number | null = null;
  if (closes.length >= 2 && closes[0] !== 0) {
    changePct = ((closes[closes.length - 1] - closes[0]) / Math.abs(closes[0])) * 100;
  }
  return {
    spark,
    price: price != null && Number.isFinite(price) ? price : null,
    changePct,
    unavailable: price == null,
  };
}

function hardwareRoleForDevice(
  hardware: ModelHardwareInventory | null,
  index: number,
  name: string,
): string | undefined {
  if (!hardware?.devices?.length) return undefined;
  const match =
    hardware.devices.find((d) => d.ordinal === index) ||
    hardware.devices.find((d) => d.name && name && d.name === name);
  if (!match) return undefined;
  // Only surface known placement roles — never invent Aux/Display.
  const meta = match as { role?: string };
  const role = typeof meta.role === "string" ? meta.role.trim() : "";
  if (!role) return undefined;
  return role;
}

function tempFromHardware(
  hardware: ModelHardwareInventory | null,
  index: number,
  name: string,
): number | null {
  if (!hardware?.devices?.length) return null;
  const match =
    hardware.devices.find((d) => d.ordinal === index) ||
    hardware.devices.find((d) => d.name && name && d.name === name);
  const t = match?.temperatureC;
  return t != null && Number.isFinite(t) ? t : null;
}

export function useDashboardOverview(opts?: { enabled?: boolean }): DashboardOverview {
  const enabled = opts?.enabled ?? true;

  const {
    sample: telemetry,
    error: telemetryError,
    refresh: refreshTelemetry,
  } = useSystemTelemetry({ enabled, intervalMs: 2000 });

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [fleet, setFleet] = useState<AgentFleetSummary | null>(null);
  const [workersDash, setWorkersDash] = useState<WorkerFabricDashboard | null>(null);
  const [researchProjects, setResearchProjects] = useState<ResearchProject[] | null>(null);
  const [marketStatus, setMarketStatus] = useState<MarketSimStatusResponse | null>(null);
  const [marketSources, setMarketSources] = useState<MarketDataSource[] | null>(null);
  const [strategies, setStrategies] = useState<MarketStrategy[] | null>(null);
  const [ingestion, setIngestion] = useState<HostSourceIngestionResponse | null>(null);
  const [hostOverview, setHostOverview] = useState<HostOverviewResponse | null>(null);
  const [modelsStatus, setModelsStatus] = useState<ModelsStatus | null>(null);
  const [providers, setProviders] = useState<ModelProvider[] | null>(null);
  const [hardware, setHardware] = useState<ModelHardwareInventory | null>(null);
  const [taskSummary, setTaskSummary] = useState<TaskSummary | null>(null);
  const [activities, setActivities] = useState<TaskEvent[] | null>(null);
  const [barsBySymbol, setBarsBySymbol] = useState<Record<string, MarketBarsResponse | null>>({});
  const [errors, setErrors] = useState<SettledErrors>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedGpuIndex, setSelectedGpuIndex] = useState(0);
  const [initialLoaded, setInitialLoaded] = useState(false);

  const mounted = useRef(true);
  const midInFlight = useRef(false);
  const slowInFlight = useRef(false);
  const barsInFlight = useRef(false);
  const generation = useRef(0);
  const readySymbolsRef = useRef<MarketDataSource[]>([]);

  const mergeErrors = useCallback((patch: SettledErrors) => {
    setErrors((prev) => {
      const next = { ...prev };
      for (const [key, value] of Object.entries(patch)) {
        if (value == null) delete next[key];
        else next[key] = value;
      }
      return next;
    });
  }, []);

  const pullMid = useCallback(async () => {
    if (midInFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    midInFlight.current = true;
    const gen = generation.current;
    try {
      const [healthRes, fleetRes, workersRes] = await Promise.allSettled([
        api.health(),
        api.getAgentFleetSummary(),
        api.getWorkersDashboard(),
      ]);
      if (!mounted.current || gen !== generation.current) return;

      const errPatch: SettledErrors = {};

      if (healthRes.status === "fulfilled") {
        setHealth(healthRes.value);
        errPatch.health = undefined;
      } else {
        errPatch.health = reasonMessage(healthRes.reason, "Health unavailable");
      }

      if (fleetRes.status === "fulfilled") {
        setFleet(fleetRes.value.summary);
        errPatch.agents = undefined;
      } else {
        errPatch.agents = reasonMessage(fleetRes.reason, "Agents unavailable");
      }

      if (workersRes.status === "fulfilled") {
        setWorkersDash(workersRes.value);
        errPatch.workers = undefined;
      } else {
        errPatch.workers = reasonMessage(workersRes.reason, "Workers unavailable");
      }

      mergeErrors(errPatch);
    } finally {
      midInFlight.current = false;
    }
  }, [mergeErrors]);

  const pullSlow = useCallback(async () => {
    if (slowInFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    slowInFlight.current = true;
    const gen = generation.current;
    try {
      const results = await Promise.allSettled([
        api.listResearchProjects(20),
        api.marketSimStatus(),
        api.listMarketData(20),
        api.listMarketStrategies(100),
        api.hostSourceIngestion(20),
        api.hostOverview(),
        api.modelsStatus(),
        api.listModelProviders(),
        api.modelsHardware(),
        api.taskSummary(),
        api.taskActivity({ limit: 8 }),
      ]);
      if (!mounted.current || gen !== generation.current) return;

      const [
        researchRes,
        marketRes,
        sourcesRes,
        strategiesRes,
        ingestionRes,
        hostRes,
        modelsRes,
        providersRes,
        hardwareRes,
        taskSummaryRes,
        activityRes,
      ] = results;

      const errPatch: SettledErrors = {};

      if (researchRes.status === "fulfilled") {
        setResearchProjects(researchRes.value.projects ?? []);
        errPatch.research = undefined;
      } else {
        errPatch.research = reasonMessage(researchRes.reason, "Research unavailable");
      }

      if (marketRes.status === "fulfilled") {
        setMarketStatus(marketRes.value);
        errPatch.market = undefined;
      } else {
        errPatch.market = reasonMessage(marketRes.reason, "Market status unavailable");
      }

      if (sourcesRes.status === "fulfilled") {
        const sources = sourcesRes.value.sources ?? [];
        setMarketSources(sources);
        readySymbolsRef.current = sources.filter((s) => String(s.status).toUpperCase() === "READY");
        errPatch.marketData = undefined;
      } else {
        errPatch.marketData = reasonMessage(sourcesRes.reason, "Market data unavailable");
      }

      if (strategiesRes.status === "fulfilled") {
        setStrategies(strategiesRes.value.strategies ?? []);
        errPatch.strategies = undefined;
      } else {
        errPatch.strategies = reasonMessage(strategiesRes.reason, "Strategies unavailable");
      }

      if (ingestionRes.status === "fulfilled") {
        setIngestion(ingestionRes.value);
        errPatch.ingestion = undefined;
      } else {
        errPatch.ingestion = reasonMessage(ingestionRes.reason, "Ingestion unavailable");
      }

      if (hostRes.status === "fulfilled") {
        setHostOverview(hostRes.value);
        errPatch.host = undefined;
      } else {
        errPatch.host = reasonMessage(hostRes.reason, "Host overview unavailable");
      }

      if (modelsRes.status === "fulfilled") {
        setModelsStatus(modelsRes.value.status);
        errPatch.models = undefined;
      } else {
        errPatch.models = reasonMessage(modelsRes.reason, "Models status unavailable");
      }

      if (providersRes.status === "fulfilled") {
        setProviders(providersRes.value.providers ?? []);
        errPatch.providers = undefined;
      } else {
        errPatch.providers = reasonMessage(providersRes.reason, "Providers unavailable");
      }

      if (hardwareRes.status === "fulfilled") {
        setHardware(hardwareRes.value.hardware);
        errPatch.hardware = undefined;
      } else {
        errPatch.hardware = reasonMessage(hardwareRes.reason, "Hardware unavailable");
      }

      if (taskSummaryRes.status === "fulfilled") {
        setTaskSummary(taskSummaryRes.value.summary);
        errPatch.taskSummary = undefined;
      } else {
        errPatch.taskSummary = reasonMessage(taskSummaryRes.reason, "Task summary unavailable");
      }

      if (activityRes.status === "fulfilled") {
        setActivities(activityRes.value.activity ?? []);
        errPatch.activity = undefined;
      } else {
        errPatch.activity = reasonMessage(activityRes.reason, "Activity unavailable");
      }

      mergeErrors(errPatch);
    } finally {
      slowInFlight.current = false;
      if (mounted.current) {
        setLoading(false);
        setInitialLoaded(true);
      }
    }
  }, [mergeErrors]);

  const pullBars = useCallback(async () => {
    if (barsInFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    const ready = readySymbolsRef.current.slice(0, 4);
    if (!ready.length) return;
    barsInFlight.current = true;
    const gen = generation.current;
    try {
      const settled = await Promise.allSettled(
        ready.map((src) =>
          api.fetchMarketBars({
            symbol: src.symbol,
            timeframe: src.timeframe || "1h",
            limit: 32,
          }),
        ),
      );
      if (!mounted.current || gen !== generation.current) return;
      const next: Record<string, MarketBarsResponse | null> = {};
      settled.forEach((res, i) => {
        const symbol = ready[i]?.symbol;
        if (!symbol) return;
        next[symbol] = res.status === "fulfilled" ? res.value : null;
      });
      setBarsBySymbol((prev) => ({ ...prev, ...next }));
    } finally {
      barsInFlight.current = false;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!mounted.current) return;
    setRefreshing(true);
    generation.current += 1;
    try {
      await Promise.all([
        refreshTelemetry(),
        pullMid(),
        pullSlow().then(() => pullBars()),
      ]);
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }, [pullBars, pullMid, pullSlow, refreshTelemetry]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return;

    void pullMid();
    void pullSlow().then(() => {
      void pullBars();
    });

    const midId = window.setInterval(() => {
      void pullMid();
    }, WORKERS_INTERVAL_MS);
    const slowId = window.setInterval(() => {
      void pullSlow();
    }, SLOW_INTERVAL_MS);
    const barsId = window.setInterval(() => {
      void pullBars();
    }, BARS_INTERVAL_MS);

    const onVis = () => {
      if (document.visibilityState === "visible") {
        void pullMid();
        void pullSlow();
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      mounted.current = false;
      window.clearInterval(midId);
      window.clearInterval(slowId);
      window.clearInterval(barsId);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [enabled, pullBars, pullMid, pullSlow]);

  useEffect(() => {
    if (telemetryError) {
      mergeErrors({ telemetry: telemetryError });
    } else {
      mergeErrors({ telemetry: undefined });
    }
  }, [telemetryError, mergeErrors]);

  const systemStatus = useMemo(() => {
    const base = normalizeSystemStatus(health, errors.health ?? (health == null && initialLoaded));
    return {
      ...base,
      detail: errors.health,
    };
  }, [health, errors.health, initialLoaded]);

  const agents = useMemo(() => resolveAgents(fleet, health), [fleet, health]);

  const jobs = useMemo((): DashboardOverview["jobs"] => {
    const queued =
      workersDash?.summary.queue_depth ??
      health?.jobs?.queued ??
      null;
    const active =
      workersDash?.summary.busy_workers ??
      (workersDash ? workersDash.workers.filter((w) => /busy|running/i.test(w.state)).length : null);
    const available = workersDash != null || health?.jobs != null;
    return {
      active: available ? active : null,
      queued: available ? queued : null,
      available,
    };
  }, [workersDash, health]);

  const research = useMemo((): DashboardOverview["research"] => {
    if (researchProjects == null) {
      return { activeCount: null, available: false, projects: [] };
    }
    const projects = mapResearchProjects(researchProjects);
    const activeCount = researchProjects.filter((p) => researchActive(p.status)).length;
    return { activeCount, available: true, projects };
  }, [researchProjects]);

  const trading = useMemo((): DashboardOverview["trading"] => {
    const ready = (marketSources ?? []).filter((s) => String(s.status).toUpperCase() === "READY");
    const instruments = ready.slice(0, 4).map((src) => {
      const hasFetched = Object.prototype.hasOwnProperty.call(barsBySymbol, src.symbol);
      const bars = hasFetched ? barsBySymbol[src.symbol] ?? null : null;
      const sparkInfo = sparkFromBars(bars);
      return {
        symbol: src.symbol,
        price: hasFetched ? sparkInfo.price : null,
        changePct: hasFetched ? sparkInfo.changePct : null,
        spark: hasFetched ? sparkInfo.spark : [],
        unavailable: hasFetched ? sparkInfo.unavailable : false,
      };
    });
    const activeStrategies =
      strategies == null
        ? null
        : strategies.filter((s) => String(s.status).toUpperCase() === "ACTIVE").length;
    const available = marketStatus != null || marketSources != null;
    return {
      activeStrategies,
      available,
      paper: true,
      instruments,
    };
  }, [marketSources, barsBySymbol, strategies, marketStatus]);

  const healthGauges = useMemo((): DashboardOverview["healthGauges"] => {
    const cpuAvail = telemetry?.cpu.available === true;
    const ramAvail = telemetry?.memory.available === true;
    const gpuAvail = telemetry?.gpu.available === true && telemetry.dashboard.gpuPct != null;
    const diskAvail = telemetry?.disk?.available === true;
    return {
      cpu: buildGauge(telemetry?.dashboard.cpuPct, cpuAvail, "CPU"),
      ram: buildGauge(telemetry?.dashboard.ramPct, ramAvail, memorySublabel(telemetry)),
      gpu: buildGauge(
        telemetry?.dashboard.gpuPct,
        gpuAvail || telemetry?.gpu.available === true,
        telemetry?.gpu.available ? "GPU" : "N/A",
      ),
      disk: buildGauge(
        telemetry?.dashboard.diskPct ?? telemetry?.disk?.utilizationPct,
        diskAvail,
        diskSublabel(telemetry),
      ),
    };
  }, [telemetry]);

  const workers = useMemo((): DashboardOverview["workers"] => {
    if (!workersDash) return [];
    return pickActiveWorkers(workersDash.workers, 5).map((w) => {
      const { progress, progressLabel } = workerProgress(w);
      const domain = workerDomain(w);
      const resources = (w.resource_class ?? []).map((r) => String(r).toLowerCase());
      let target = "—";
      if (resources.some((r) => r.includes("gpu"))) target = "GPU";
      else if (resources.some((r) => r.includes("cpu"))) target = "CPU";
      else if (w.current_work) target = w.current_work;
      return {
        id: w.worker_id,
        name: w.display_name || w.worker_id,
        domain,
        target,
        progress,
        progressLabel,
        tone: workerStateTone(w.state),
      };
    });
  }, [workersDash]);

  const queue = useMemo(() => queueFromWorkers(workersDash, 5), [workersDash]);

  const activityRows = useMemo((): DashboardOverview["activities"] => {
    if (!activities) return [];
    return activities.slice(0, 8).map((ev) => {
      const domain = activityDomain(ev);
      const title = ev.taskTitle || ev.eventType || "Activity";
      return {
        id: ev.eventId,
        time: formatActivityTime(ev.createdAt),
        description: title,
        domain,
        tone: domainBadgeTone(domain),
      };
    });
  }, [activities]);

  const ingestionView = useMemo((): DashboardOverview["ingestion"] => {
    if (!ingestion) {
      return {
        title: "Source ingestion",
        progress: null,
        detail: errors.ingestion ? "UNAVAILABLE" : "UNMEASURED",
        available: false,
      };
    }
    const c = ingestion.counts;
    const activeJob = (ingestion.jobs ?? []).find((j) => j.phase || j.progressPct != null);
    const detail = `${c.processing} processing · ${c.queued} queued · ${c.failed} failed`;
    return {
      title: activeJob?.source || "Source ingestion",
      progress: clampPct(ingestion.overallProgressPct),
      detail,
      available: true,
    };
  }, [ingestion, errors.ingestion]);

  const gpuDevices = useMemo(() => {
    const devices = telemetry?.gpu.devices ?? [];
    return devices.map((d) => {
      const temp =
        d.temperatureC != null && Number.isFinite(d.temperatureC)
          ? d.temperatureC
          : tempFromHardware(hardware, d.index, d.name);
      return {
        index: d.index,
        name: d.name || `GPU ${d.index}`,
        util: clampPct(d.utilizationPct),
        vramUsedBytes: d.vramUsedBytes ?? null,
        vramTotalBytes: d.vramTotalBytes ?? null,
        tempC: temp,
        role: hardwareRoleForDevice(hardware, d.index, d.name),
      };
    });
  }, [telemetry, hardware]);

  useEffect(() => {
    if (!gpuDevices.length) {
      if (selectedGpuIndex !== 0) setSelectedGpuIndex(0);
      return;
    }
    if (selectedGpuIndex < 0 || selectedGpuIndex >= gpuDevices.length) {
      setSelectedGpuIndex(0);
    }
  }, [gpuDevices, selectedGpuIndex]);

  const performance = useMemo((): DashboardOverview["performance"] => {
    const tasksPerHour = deriveTasksPerHour(taskSummary?.completedToday ?? null);
    const uptimeLabel = extractUptimeLabel(hostOverview?.runtime ?? null);
    return {
      tasksPerHour,
      avgProcessingMin: null, // no honest avg on taskSummary; leave UNMEASURED
      uptimeLabel,
      trends: {
        tasksPerHourDerived: tasksPerHour != null,
        avgProcessingAvailable: false,
        uptimeAvailable: uptimeLabel != null,
      },
    };
  }, [taskSummary, hostOverview]);

  const sidebarStatus = useMemo((): DashboardOverview["sidebarStatus"] => {
    const lm = normalizeLmStudioStatus(health, modelsStatus, providers);
    const rows: DashboardOverview["sidebarStatus"] = [
      {
        id: "lm-studio",
        label: "LM Studio",
        value: lm.value,
        tone: lm.tone,
      },
    ];

    const devices = gpuDevices.slice(0, 2);
    if (devices.length === 0) {
      rows.push({
        id: "gpu-none",
        label: "GPU",
        value: telemetry?.gpu.available === false ? "Unavailable" : "UNMEASURED",
        tone: "muted",
      });
    } else {
      for (const d of devices) {
        const shortName = d.name.replace(/^NVIDIA\s+/i, "");
        rows.push({
          id: `gpu-${d.index}`,
          label: `GPU ${d.index} - ${shortName}`,
          value: d.util != null ? "Ready" : "UNMEASURED",
          tone: d.util == null ? "muted" : "success",
        });
      }
    }

    const mem = telemetry?.memory;
    rows.push({
      id: "ram",
      label: "RAM",
      value:
        mem?.available && mem.usedBytes != null && mem.totalBytes != null
          ? `${formatBytes(mem.usedBytes)} / ${formatBytes(mem.totalBytes)}`
          : "UNMEASURED",
      tone: mem?.available ? "info" : "muted",
    });

    const gpus = telemetry?.gpu.devices ?? [];
    if (gpus.length && telemetry?.gpu.available) {
      let used = 0;
      let total = 0;
      let measured = true;
      for (const g of gpus) {
        if (g.vramUsedBytes == null || g.vramTotalBytes == null) {
          measured = false;
          break;
        }
        used += g.vramUsedBytes;
        total += g.vramTotalBytes;
      }
      rows.push({
        id: "vram-total",
        label: "VRAM Totaal",
        value: measured ? `${formatBytes(used)} / ${formatBytes(total)}` : "UNMEASURED",
        tone: measured ? "info" : "muted",
      });
    } else {
      rows.push({
        id: "vram-total",
        label: "VRAM Totaal",
        value: "UNMEASURED",
        tone: "muted",
      });
    }

    return rows;
  }, [health, modelsStatus, providers, gpuDevices, telemetry]);

  const telemetryStale = useMemo(() => {
    if (telemetryError) return true;
    if (!telemetry) return initialLoaded;
    if (telemetry.ageMs != null && telemetry.ageMs > TELEMETRY_STALE_MS) return true;
    return false;
  }, [telemetry, telemetryError, initialLoaded]);

  return {
    loading: loading && !initialLoaded,
    refreshing,
    refresh,
    systemStatus,
    agents,
    jobs,
    research,
    trading,
    healthGauges,
    workers,
    workersAvailable: workersDash != null,
    queue,
    activities: activityRows,
    ingestion: ingestionView,
    gpuPanel: {
      devices: gpuDevices,
      selectedIndex: selectedGpuIndex,
      setSelectedIndex: setSelectedGpuIndex,
    },
    performance,
    sidebarStatus,
    telemetryStale,
    errors,
  };
}
