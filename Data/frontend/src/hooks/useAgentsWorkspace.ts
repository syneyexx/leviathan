/**
 * Agents V2 workspace orchestration.
 * Owns fleet roster, dashboard, missions, workers, selection, and mutations.
 * Production never imports Screen 1 fixture numbers — those live only in
 * `mocks/agentsV2VisualFixture.ts` behind Playwright route mocking.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useSystemTelemetry } from "./useSystemTelemetry";
import { useAppToast } from "../state/useAppToast";
import type {
  AgentDefinition,
  AgentEvent,
  AgentFleetSummary,
  AgentMission,
  AgentMissionLaunchPayload,
  AgentsDashboard,
  CapabilityListItem,
  DatasetLearningStatus,
  DatasetRecord,
  HealthResponse,
  KnowledgeDocument,
  ModelDescriptor,
  SystemArchitectureEntry,
  WorkersListResponse,
  WorkerFabricDashboard,
} from "../types/api";
import {
  canLaunchAgent,
  deriveEnvironmentOptions,
  deriveModelOptions,
  deriveRoleOptions,
  deriveStatusOptions,
  deriveTeamOptions,
  draftFromAgent,
  draftToCreatePayload,
  emptyDashboardFilters,
  emptyEditorDraft,
  errMsg,
  filterDashboardAgents,
  healthLabel,
  isArchitectureEntry,
  isSystemProtected,
  validateEditorDraft,
  type AgentEditorDraft,
  type DashboardFilters,
  type MissionTab,
} from "../pages/agents/helpers";

const POLL_MS = 6000;

function architectureEntryAsAgent(arch: SystemArchitectureEntry): AgentDefinition {
  return {
    agentId: arch.id,
    id: arch.id,
    name: arch.name,
    kind: arch.entityType === "orchestrator" ? "orchestrator" : "specialist",
    description: arch.description || "",
    role: arch.runtimeKind || arch.entityType,
    enabled: arch.enabled !== false,
    archived: false,
    capabilities: arch.capabilities || [],
    knowledgeSources: [],
    memoryPolicy: "default",
    datasetAccess: "none",
    approvalMode: "inherit",
    autonomy: 0,
    maxConcurrency: 0,
    maxRetries: 0,
    tags: [arch.entityType, arch.systemKey],
    version: 1,
    health: (["unknown", "idle", "busy", "disabled", "error", "archived"].includes(arch.status)
      ? arch.status
      : "unknown") as AgentDefinition["health"],
    healthReason:
      typeof arch.metadata?.detail === "string"
        ? arch.metadata.detail
        : arch.status === "unknown"
          ? "status unknown"
          : null,
    createdAt: "",
    updatedAt: "",
    origin: "system",
    entityType: arch.entityType === "orchestrator" ? "orchestrator" : "architecture",
    systemKey: arch.systemKey,
    mutable: false,
    executable: arch.executable === true,
    metadata: {
      ...(arch.metadata || {}),
      sourceModule: arch.sourceModule,
      relationships: arch.relationships,
      runtimeKind: arch.runtimeKind,
    },
  };
}

export type AgentsKpiCell = {
  value: string;
  sublabel: string;
  available: boolean;
  loading: boolean;
  delta?: string;
  title?: string;
};

export type AgentsWorkspace = ReturnType<typeof useAgentsWorkspace>;

export function useAgentsWorkspace() {
  const toast = useAppToast();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agent");
  const { sample: telemetry } = useSystemTelemetry({ enabled: true, intervalMs: 4000 });

  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [systemEntries, setSystemEntries] = useState<SystemArchitectureEntry[]>([]);
  const [summary, setSummary] = useState<AgentFleetSummary | null>(null);
  const [missions, setMissions] = useState<AgentMission[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDocument[]>([]);
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [datasetLearning, setDatasetLearning] = useState<DatasetLearningStatus | null>(null);
  const [dashboard, setDashboard] = useState<AgentsDashboard | null>(null);
  const [workersList, setWorkersList] = useState<WorkersListResponse | null>(null);
  const [fabricDashboard, setFabricDashboard] = useState<WorkerFabricDashboard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const [filters, setFilters] = useState<DashboardFilters>(emptyDashboardFilters());
  const [showAll, setShowAll] = useState(false);
  const [missionTab, setMissionTab] = useState<MissionTab>("All Tasks");
  const [windowHours, setWindowHours] = useState(24);
  const [failureWindowHours, setFailureWindowHours] = useState(168);

  const [selectedAgentId, setSelectedAgentId] = useState(requestedAgentId || "");
  const [selectedMissionId, setSelectedMissionId] = useState("");
  const [missionDetailOpen, setMissionDetailOpen] = useState(false);
  const [missionDetail, setMissionDetail] = useState<{
    mission: AgentMission;
    children: AgentMission[];
    events: AgentEvent[];
  } | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<"create" | "edit">("create");
  const [draft, setDraft] = useState<AgentEditorDraft>(emptyEditorDraft());
  const [launchOpen, setLaunchOpen] = useState(false);
  const [spawnPoolId, setSpawnPoolId] = useState<string | null>(null);
  const [coreOpen, setCoreOpen] = useState(false);
  const [archView, setArchView] = useState(false);
  const [tradeOpen, setTradeOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [directoryFocusToken, setDirectoryFocusToken] = useState(0);

  const selectedAgentIdRef = useRef(selectedAgentId);
  const windowsRef = useRef({ windowHours, failureWindowHours });
  const loadGen = useRef(0);
  const inflight = useRef(false);
  const pending = useRef(false);
  const rerunRef = useRef<() => void>(() => {});
  const directorySearchRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (requestedAgentId) setSelectedAgentId(requestedAgentId);
  }, [requestedAgentId]);

  useEffect(() => {
    selectedAgentIdRef.current = selectedAgentId;
  }, [selectedAgentId]);

  const loadAll = useCallback(async (opts?: { manual?: boolean }) => {
    if (inflight.current) {
      pending.current = true;
      return;
    }
    inflight.current = true;
    pending.current = false;
    if (opts?.manual) setRefreshing(true);
    const gen = ++loadGen.current;
    const win = windowsRef.current;
    try {
      const [
        roster,
        missionRes,
        eventRes,
        caps,
        modelRes,
        knowledgeRes,
        datasetRes,
        learningRes,
        dash,
        workersRes,
        fabricRes,
        healthRes,
      ] = await Promise.all([
        api.listAgentRoster({ includeArchived: true, includeArchitecture: true }),
        api.listAgentMissions({ limit: 200 }),
        api.listAgentEvents({ limit: 120 }),
        api.listCapabilities({ limit: 500 }).catch(() => ({ capabilities: [] as CapabilityListItem[] })),
        api.listModels().catch(() => ({ models: [] as ModelDescriptor[] })),
        api.listKnowledgeDocuments().catch(() => ({ documents: [] as KnowledgeDocument[] })),
        api.listDatasets(100).catch(() => ({ datasets: [] as DatasetRecord[] })),
        api.getDatasetLearningStatus().catch(() => null),
        api
          .getAgentsDashboard({ windowHours: win.windowHours, failureWindowHours: win.failureWindowHours })
          .then((d) => ({ ok: true as const, d }))
          .catch((err: unknown) => ({ ok: false as const, err })),
        api.listWorkers().catch(() => null),
        api.getWorkersDashboard().catch(() => null),
        api.health().catch(() => null),
      ]);
      if (gen !== loadGen.current) return;
      setAgents(roster.agents);
      setSystemEntries(roster.system || []);
      setSummary(roster.summary);
      setMissions(missionRes.missions);
      setEvents(eventRes.events);
      setCapabilities(caps.capabilities ?? []);
      setModels(modelRes.models ?? []);
      setKnowledgeDocs(knowledgeRes.documents ?? []);
      setDatasets(datasetRes.datasets ?? []);
      setDatasetLearning(learningRes);
      setWorkersList(workersRes);
      setFabricDashboard(fabricRes);
      setHealth(healthRes);
      if (dash.ok) {
        setDashboard(dash.d);
        setDashboardError(null);
      } else {
        setDashboardError(errMsg(dash.err, "Dashboard read-model unavailable"));
      }
      setLoadError(null);
      setLive(dash.ok);
      if (!selectedAgentIdRef.current && roster.agents.length > 0) {
        const preferred =
          roster.agents.find((a) => !a.archived && a.kind === "coding") ??
          roster.agents.find((a) => !a.archived && a.enabled) ??
          roster.agents.find((a) => !a.archived) ??
          roster.agents[0];
        setSelectedAgentId(preferred.agentId);
      }
    } catch (err) {
      if (gen !== loadGen.current) return;
      setLoadError(errMsg(err, "Failed to load agent fleet"));
      setLive(false);
    } finally {
      inflight.current = false;
      setLoading(false);
      setRefreshing(false);
      if (pending.current) {
        pending.current = false;
        rerunRef.current();
      }
    }
  }, []);

  useEffect(() => {
    rerunRef.current = () => void loadAll();
  }, [loadAll]);

  useEffect(() => {
    void loadAll();
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void loadAll();
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadAll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [loadAll]);

  useEffect(() => {
    const prev = windowsRef.current;
    if (prev.windowHours === windowHours && prev.failureWindowHours === failureWindowHours) return;
    windowsRef.current = { windowHours, failureWindowHours };
    void loadAll();
  }, [windowHours, failureWindowHours, loadAll]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== "hidden") setNowMs(Date.now());
    }, 5000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!selectedMissionId || !missionDetailOpen) return;
    let cancelled = false;
    void (async () => {
      try {
        const detail = await api.getAgentMission(selectedMissionId);
        if (!cancelled) setMissionDetail(detail);
      } catch (err) {
        if (!cancelled) {
          toast(errMsg(err, "Failed to load mission detail"));
          setMissionDetail(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedMissionId, missionDetailOpen, toast, missions]);

  const architectureAsAgents = useMemo(() => systemEntries.map(architectureEntryAsAgent), [systemEntries]);
  const liveFleet = useMemo(() => agents.filter((a) => !a.archived), [agents]);
  const rosterUniverse = useMemo(() => [...agents, ...architectureAsAgents], [agents, architectureAsAgents]);
  const agentById = useMemo(
    () => Object.fromEntries(rosterUniverse.map((a) => [a.agentId, a])),
    [rosterUniverse],
  );
  const selectedAgent = agentById[selectedAgentId];

  const filterOptions = useMemo(() => {
    const base = showAll ? rosterUniverse : liveFleet;
    return {
      teams: deriveTeamOptions(base),
      statuses: deriveStatusOptions(base),
      roles: deriveRoleOptions(base),
      models: deriveModelOptions(base),
      environments: deriveEnvironmentOptions(base),
    };
  }, [showAll, rosterUniverse, liveFleet]);

  const tableAgents = useMemo(
    () => filterDashboardAgents(showAll ? rosterUniverse : liveFleet, filters),
    [showAll, rosterUniverse, liveFleet, filters],
  );
  const archFleet = useMemo(() => filterDashboardAgents(liveFleet, filters), [liveFleet, filters]);

  const displayedMissionDetail =
    missionDetailOpen && selectedMissionId && missionDetail?.mission.missionId === selectedMissionId
      ? missionDetail
      : null;

  async function withBusy(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok);
      await loadAll();
    } catch (err) {
      toast(errMsg(err, "Action failed"));
    } finally {
      setBusy(false);
    }
  }

  function openCreate() {
    setEditorMode("create");
    setDraft(emptyEditorDraft({ kind: "research", role: "Specialist" }));
    setEditorOpen(true);
  }

  function openEdit() {
    if (!selectedAgent) return;
    if (isArchitectureEntry(selectedAgent)) {
      toast("Architecture components are read-only");
      return;
    }
    setEditorMode("edit");
    setDraft(draftFromAgent(selectedAgent));
    setEditorOpen(true);
  }

  async function onSaveEditor() {
    const validation = validateEditorDraft(draft, {
      editingId: editorMode === "edit" ? selectedAgentId : undefined,
    });
    if (validation) {
      toast(validation);
      return;
    }
    await withBusy(async () => {
      const payload = draftToCreatePayload(draft);
      if (editorMode === "create") {
        const created = await api.createAgent(payload as Parameters<typeof api.createAgent>[0]);
        setSelectedAgentId(created.agent.agentId);
      } else {
        await api.updateAgent(selectedAgentId, payload as Parameters<typeof api.updateAgent>[1]);
      }
      setEditorOpen(false);
    }, editorMode === "create" ? "Agent created" : "Agent saved");
  }

  async function onLaunch(agentId: string, payload: AgentMissionLaunchPayload) {
    const gate = canLaunchAgent(agentById[agentId], summary?.agentsEnabled);
    if (!gate.ok) {
      toast(gate.reason || "Cannot launch");
      return;
    }
    await withBusy(async () => {
      const mission = await api.launchAgentMission(agentId, payload);
      setSelectedAgentId(agentId);
      setSelectedMissionId(mission.mission.missionId);
      setLaunchOpen(false);
    }, payload.dryRun ? "Dry-run plan complete" : "Mission launched");
  }

  async function onCancelMission(missionId: string) {
    await withBusy(async () => {
      await api.cancelAgentMission(missionId);
    }, "Cancel requested");
  }

  async function onToggleSelected() {
    if (!selectedAgent || isArchitectureEntry(selectedAgent)) return;
    const wasEnabled = selectedAgent.enabled;
    await withBusy(async () => {
      if (wasEnabled) await api.disableAgent(selectedAgentId);
      else await api.enableAgent(selectedAgentId);
    }, wasEnabled ? "Agent disabled" : "Agent enabled");
  }

  async function onClone() {
    if (!selectedAgent) return;
    if (isArchitectureEntry(selectedAgent)) {
      toast("Architecture components cannot be cloned into the fleet");
      return;
    }
    await withBusy(async () => {
      const cloned = await api.cloneAgent(selectedAgentId);
      setSelectedAgentId(cloned.agent.agentId);
    }, "Agent cloned");
  }

  async function onArchive() {
    if (!selectedAgent) return;
    if (isSystemProtected(selectedAgent) || isArchitectureEntry(selectedAgent)) {
      toast("SYSTEM components cannot be archived");
      return;
    }
    if (
      !window.confirm(
        `Archive “${selectedAgent.name}”? Referenced orchestrator members will be rejected by the backend.`,
      )
    ) {
      return;
    }
    await withBusy(async () => {
      await api.archiveAgent(selectedAgentId);
    }, "Agent archived");
  }

  async function onReconcile() {
    await withBusy(async () => {
      const res = await api.reconcileAgents();
      toast(`Reconciled ${res.count} mission(s)`);
    });
  }

  async function onStartAll() {
    await withBusy(async () => {
      const res = await api.fleetStartAll();
      toast(`Enabled ${res.changed.length} agent(s) · ${res.skipped.length} skipped`);
    });
  }

  async function onPauseAll() {
    if (!window.confirm("Disable all USER fleet agents? SYSTEM agents are not affected.")) return;
    await withBusy(async () => {
      const res = await api.fleetPauseAll();
      toast(`Disabled ${res.changed.length} agent(s) · ${res.skipped.length} skipped`);
    });
  }

  async function onScale(poolId: string, desired: number) {
    await withBusy(async () => {
      const res = await api.scaleWorkerPool(poolId, desired);
      toast(`${poolId}: desired ${res.override.desiredCount} — supervisor applies on next tick`);
      setSpawnPoolId(null);
    });
  }

  function onDatasetCancel(jobId: string) {
    void withBusy(async () => {
      await api.cancelDatasetJob(jobId);
    }, "Dataset job cancel requested");
  }

  function onDatasetRetry(jobId: string) {
    void withBusy(async () => {
      await api.retryDatasetJob(jobId, true);
    }, "Dataset job re-queued (resume)");
  }

  function onDatasetReindex(datasetId: string) {
    void withBusy(async () => {
      await api.learnDataset(datasetId, { rebuild: true });
    }, "Re-index queued");
  }

  function selectMission(id: string) {
    setSelectedMissionId(id);
    setMissionDetailOpen(true);
  }

  function focusDirectory() {
    setDirectoryFocusToken((n) => n + 1);
    window.requestAnimationFrame(() => {
      directorySearchRef.current?.focus();
      directorySearchRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  const selectedLaunchable = canLaunchAgent(selectedAgent, summary?.agentsEnabled).ok;
  const anyLaunchable = liveFleet.some((a) => canLaunchAgent(a, summary?.agentsEnabled).ok);
  const workersSummary = dashboard?.workers ?? null;
  const pools = workersSummary?.pools ?? [];
  const agentNameById = useMemo(
    () => Object.fromEntries(Object.entries(agentById).map(([id, a]) => [id, a.name])),
    [agentById],
  );
  const infra = {
    capabilities: capabilities.length,
    models: models.length,
    memoryLinked: dashboard?.fleet.memoryLinked ?? null,
    knowledgeDocs: knowledgeDocs.length,
    supervisorHealth: workersSummary?.available ? workersSummary.supervisorHealth : null,
    architecture: systemEntries.length,
  };

  /** Active agents: enabled non-archived fleet with busy/online/idle health — not workers. */
  const kpis = useMemo(() => {
    const loadingKpi = loading && !dashboard && !summary;
    const busyCount = summary?.busy ?? summary?.active ?? summary?.health?.busy ?? null;
    const idleCount = summary?.idle ?? summary?.health?.idle ?? null;
    const enabledCount = summary
      ? liveFleet.filter((a) => a.enabled && healthLabel(a) !== "Offline" && healthLabel(a) !== "Archived").length
      : null;
    const activeAgents =
      busyCount != null && idleCount != null && enabledCount != null
        ? Math.max(0, (busyCount as number) + (idleCount as number))
        : enabledCount;

    const missionActive = dashboard?.missions.active ?? summary?.activeMissions ?? null;
    const missionCompleted = dashboard?.missions.completedInWindow ?? null;
    const successRate = dashboard?.performance.successRate ?? null;

    // Tool-call telemetry is not exposed as a fleet KPI today — never invent 8.4K.
    const toolCalls: AgentsKpiCell = {
      value: "UNMEASURED",
      sublabel: "geen betrouwbare tool-call teller",
      available: false,
      loading: loadingKpi,
      title: "Capability/tool execution counts are not aggregated on the Agents dashboard yet",
    };

    return {
      activeAgents: {
        value: activeAgents == null ? "—" : String(activeAgents),
        sublabel:
          summary == null
            ? "laden…"
            : `${activeAgents ?? "—"} van ${summary.agentCount} totaal`,
        available: activeAgents != null,
        loading: loadingKpi,
        title: "Enabled non-archived fleet agents with known healthy execution state (busy+idle)",
      } satisfies AgentsKpiCell,
      idleAgents: {
        value: idleCount == null ? "—" : String(idleCount),
        sublabel: idleCount == null ? (summary ? "onbekend" : "laden…") : "beschikbaar",
        available: idleCount != null,
        loading: loadingKpi,
        title: "Fleet health === idle only — unknown is not idle",
      } satisfies AgentsKpiCell,
      missions: {
        value: missionActive == null && missionCompleted == null ? "—" : String(
          (dashboard?.missions.queued ?? 0) +
            (dashboard?.missions.starting ?? 0) +
            (dashboard?.missions.running ?? 0) +
            (dashboard?.missions.cancelling ?? 0) +
            (missionCompleted ?? 0),
        ),
        sublabel:
          dashboard == null
            ? summary
              ? `${summary.activeMissions} actief`
              : "laden…"
            : `${dashboard.missions.active} actief / ${missionCompleted ?? "—"} voltooid (${dashboard.windowHours}u)`,
        available: dashboard != null || summary != null,
        loading: loadingKpi,
        title: "Real AgentMission statuses from dashboard/fleet",
      } satisfies AgentsKpiCell,
      toolCalls,
      successRate: {
        value:
          successRate == null
            ? dashboard
              ? "UNMEASURED"
              : "—"
            : `${(successRate * 100).toFixed(1)}%`,
        sublabel:
          dashboard == null
            ? "laden…"
            : successRate == null
              ? `geen terminal missies · ${dashboard.windowHours}u`
              : `n=${dashboard.performance.eligibleTerminal} · ${dashboard.windowHours}u`,
        available: successRate != null,
        loading: loadingKpi,
        title: "completed / (completed + failed); queued/running excluded",
      } satisfies AgentsKpiCell,
    };
  }, [dashboard, summary, liveFleet, loading]);

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const llm = health?.llm;
    const lmValue =
      llm?.available === true ? "Running" : llm?.available === false ? "Offline" : health ? "UNMEASURED" : "…";
    const lmTone = llm?.available === true ? "success" : llm?.available === false ? "danger" : "muted";
    const cpu = telemetry?.cpu?.available ? telemetry.cpu.utilizationPct : null;
    const ramUsed = telemetry?.memory?.available ? telemetry.memory.usedBytes : null;
    const ramTotal = telemetry?.memory?.available ? telemetry.memory.totalBytes : null;
    const gpuDevices = telemetry?.gpu?.available ? telemetry.gpu.devices : [];
    const rows: SidebarStatusRow[] = [
      { id: "lm-studio", label: "LM Studio", value: lmValue, tone: lmTone },
    ];
    if (gpuDevices.length) {
      gpuDevices.slice(0, 2).forEach((d, i) => {
        rows.push({
          id: `gpu-${i}`,
          label: `GPU ${i} (${d.name || "GPU"})`,
          value: d.utilizationPct != null ? "Ready" : "UNMEASURED",
          tone: d.utilizationPct != null ? "success" : "muted",
        });
      });
    } else {
      rows.push({ id: "gpu", label: "GPU", value: telemetry ? "UNAVAILABLE" : "…", tone: "muted" });
    }
    rows.push({
      id: "ram",
      label: "RAM",
      value:
        ramUsed != null && ramTotal != null
          ? `${(ramUsed / 1024 ** 3).toFixed(1)} / ${(ramTotal / 1024 ** 3).toFixed(0)} GB`
          : telemetry
            ? "UNMEASURED"
            : "…",
      tone: "muted",
    });
    const vramUsed = gpuDevices.reduce((s, d) => s + (d.vramUsedBytes ?? 0), 0);
    const vramTotal = gpuDevices.reduce((s, d) => s + (d.vramTotalBytes ?? 0), 0);
    rows.push({
      id: "vram",
      label: "VRAM Total",
      value:
        gpuDevices.length && vramTotal > 0
          ? `${(vramUsed / 1024 ** 3).toFixed(1)} / ${(vramTotal / 1024 ** 3).toFixed(0)} GB`
          : telemetry
            ? "UNMEASURED"
            : "…",
      tone: "muted",
    });
    return rows;
  }, [health, telemetry]);

  const activitySeries = useMemo(() => {
    const buckets = Array.from({ length: 12 }, () => 0);
    const now = nowMs;
    const hourMs = 3_600_000;
    for (const ev of events) {
      const t = Date.parse(ev.createdAt || "");
      if (!Number.isFinite(t)) continue;
      const ageH = Math.floor((now - t) / hourMs);
      if (ageH < 0 || ageH >= 12) continue;
      buckets[11 - ageH] += 1;
    }
    return buckets;
  }, [events, nowMs]);

  return {
    agents,
    systemEntries,
    summary,
    missions,
    events,
    capabilities,
    models,
    knowledgeDocs,
    datasets,
    datasetLearning,
    dashboard,
    workersList,
    fabricDashboard,
    loadError,
    dashboardError,
    live,
    busy,
    loading,
    refreshing,
    nowMs,
    telemetry,
    filters,
    setFilters,
    showAll,
    setShowAll,
    missionTab,
    setMissionTab,
    windowHours,
    setWindowHours,
    failureWindowHours,
    setFailureWindowHours,
    selectedAgentId,
    setSelectedAgentId,
    selectedMissionId,
    setSelectedMissionId,
    missionDetailOpen,
    setMissionDetailOpen,
    displayedMissionDetail,
    editorOpen,
    setEditorOpen,
    editorMode,
    draft,
    setDraft,
    launchOpen,
    setLaunchOpen,
    spawnPoolId,
    setSpawnPoolId,
    coreOpen,
    setCoreOpen,
    archView,
    setArchView,
    tradeOpen,
    setTradeOpen,
    advancedOpen,
    setAdvancedOpen,
    directoryFocusToken,
    directorySearchRef,
    focusDirectory,
    liveFleet,
    rosterUniverse,
    architectureAsAgents,
    agentById,
    selectedAgent,
    filterOptions,
    tableAgents,
    archFleet,
    selectedLaunchable,
    anyLaunchable,
    workersSummary,
    pools,
    agentNameById,
    infra,
    kpis,
    sidebarStatus,
    activitySeries,
    loadAll,
    openCreate,
    openEdit,
    onSaveEditor,
    onLaunch,
    onCancelMission,
    onToggleSelected,
    onClone,
    onArchive,
    onReconcile,
    onStartAll,
    onPauseAll,
    onScale,
    onDatasetCancel,
    onDatasetRetry,
    onDatasetReindex,
    selectMission,
  };
}
