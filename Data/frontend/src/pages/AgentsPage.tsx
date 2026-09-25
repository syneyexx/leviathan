import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useSystemTelemetry } from "../hooks/useSystemTelemetry";
import { AppShell } from "../layouts/AppShell";
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
  KnowledgeDocument,
  ModelDescriptor,
  SystemArchitectureEntry,
  WorkersListResponse,
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
  errMsg,
  emptyEditorDraft,
  filterDashboardAgents,
  isArchitectureEntry,
  isSystemProtected,
  validateEditorDraft,
  type AgentEditorDraft,
  type DashboardFilters,
  type MissionTab,
} from "./agents/helpers";
import { Modal } from "./agents/agentsUi";
import { AgentsHero } from "./agents/AgentsHero";
import { AgentsKpiStrip } from "./agents/AgentsKpiStrip";
import { AgentsToolbar } from "./agents/AgentsToolbar";
import { AgentArchitecturePanel } from "./agents/AgentArchitecturePanel";
import { ActiveAgentsPanel } from "./agents/ActiveAgentsPanel";
import { SelectedAgentPanel } from "./agents/SelectedAgentPanel";
import { WorkerPoolsPanel } from "./agents/WorkerPoolsPanel";
import { OrchestrationFlowPanel } from "./agents/OrchestrationFlowPanel";
import { MissionDetailModal, MissionQueuePanel } from "./agents/MissionQueuePanel";
import { AgentPerformancePanel } from "./agents/AgentPerformancePanel";
import { TeamDistributionPanel } from "./agents/TeamDistributionPanel";
import { FailureRetryPanel } from "./agents/FailureRetryPanel";
import { LeviathanCoreModal } from "./agents/LeviathanCoreModal";
import { SpawnWorkerModal } from "./agents/SpawnWorkerModal";
import { LaunchMissionModal } from "./agents/LaunchMissionModal";
import { AgentEditorModal } from "./agents/AgentEditorModal";
import { SignalsPanel } from "./agents/SignalsPanel";
import { TradeOrchestraSection } from "./agents/TradeOrchestraSection";

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

export function AgentsPage() {
  const toast = useAppToast();
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const [filters, setFilters] = useState<DashboardFilters>(emptyDashboardFilters());
  const [showAll, setShowAll] = useState(false);
  const [missionTab, setMissionTab] = useState<MissionTab>("All Tasks");
  const [windowHours, setWindowHours] = useState(24);
  const [failureWindowHours, setFailureWindowHours] = useState(168);

  const [selectedAgentId, setSelectedAgentId] = useState("");
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

  const selectedAgentIdRef = useRef(selectedAgentId);
  const windowsRef = useRef({ windowHours, failureWindowHours });
  const loadGen = useRef(0);
  const inflight = useRef(false);
  const pending = useRef(false);
  const rerunRef = useRef<() => void>(() => {});

  useEffect(() => {
    selectedAgentIdRef.current = selectedAgentId;
  }, [selectedAgentId]);

  const loadAll = useCallback(async () => {
    if (inflight.current) {
      pending.current = true;
      return;
    }
    inflight.current = true;
    pending.current = false;
    const gen = ++loadGen.current;
    const win = windowsRef.current;
    try {
      const [roster, missionRes, eventRes, caps, modelRes, knowledgeRes, datasetRes, learningRes, dash, workersRes] =
        await Promise.all([
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

  const architecture = (focused: boolean) => (
    <AgentArchitecturePanel
      agents={archFleet}
      systemEntries={systemEntries}
      pools={pools}
      workersAvailable={Boolean(workersSummary?.available)}
      infra={infra}
      selectedId={selectedAgentId}
      live={live}
      focused={focused}
      onSelect={setSelectedAgentId}
      onOpenCore={() => setCoreOpen(true)}
      onOpenPool={(pid) => setSpawnPoolId(pid)}
      onClose={focused ? () => setArchView(false) : undefined}
    />
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Agents Mode"
      searchPlaceholder="Search agents, tasks, tools, models..."
      systemItems={[
        summary?.agentsEnabled ? "AGENTS ENABLED" : "AGENTS FEATURE OFF",
        `${summary?.agentCount ?? liveFleet.length} AGENTS`,
        `${summary?.orchestratorCount ?? 0} ORCH`,
        `${summary?.activeMissions ?? 0} ACTIVE`,
      ]}
      layout="wide"
      pageClass="lv-app--agents"
    >
      <div className="lv-ag-shell">
        <main className="lv-main lv-ag-main">
          <AgentsHero />

          {summary && !summary.agentsEnabled ? (
            <div className="lv-ag-banner is-warn" role="status">
              Agents feature flag is OFF (`LEVIATHAN_FEATURE_AGENTS`). Definitions remain manageable;
              mission execution is unavailable.
            </div>
          ) : null}
          {loadError ? (
            <div className="lv-ag-banner is-error" role="alert">
              {loadError}
              <button type="button" className="lv-ag-btn-ghost is-xs" onClick={() => void loadAll()}>
                Retry
              </button>
            </div>
          ) : dashboardError ? (
            <div className="lv-ag-banner is-warn" role="status">
              Dashboard: {dashboardError}. Fleet data is still live; aggregate KPIs show “—”.
            </div>
          ) : null}

          <AgentsKpiStrip dashboard={dashboard} nowMs={nowMs} stale={!live} />

          <AgentsToolbar
            busy={busy}
            filters={filters}
            options={filterOptions}
            architectureView={archView}
            onFilters={setFilters}
            onNewAgent={openCreate}
            onSpawnWorker={() => setSpawnPoolId(pools[0]?.poolId ?? "")}
            onStartAll={() => void onStartAll()}
            onPauseAll={() => void onPauseAll()}
            onToggleArchitecture={() => setArchView((v) => !v)}
            onReconcile={() => void onReconcile()}
            onRefresh={() => void loadAll()}
            onTradeOrchestra={() => setTradeOpen(true)}
          />

          <div className="lv-ag-grid">
            <div className="lv-ag-area-arch">{architecture(false)}</div>
            <div className="lv-ag-area-agents">
              <ActiveAgentsPanel
                agents={tableAgents}
                missions={missions}
                selectedId={selectedAgentId}
                totalCount={showAll ? rosterUniverse.length : liveFleet.length}
                query={filters.query || ""}
                showAll={showAll}
                onQuery={(q) => setFilters({ ...filters, query: q })}
                onToggleAll={() => setShowAll((v) => !v)}
                onSelect={setSelectedAgentId}
              />
            </div>
            <div className="lv-ag-area-sel">
              <SelectedAgentPanel
                agent={selectedAgent}
                agents={liveFleet}
                missions={missions}
                events={events}
                capabilities={capabilities}
                knowledgeDocs={knowledgeDocs}
                datasets={datasets}
                datasetLearning={datasetLearning}
                workers={workersList?.workers ?? null}
                telemetry={telemetry}
                agentsEnabled={summary?.agentsEnabled}
                busy={busy}
                selectedMissionId={selectedMissionId}
                onEdit={openEdit}
                onClone={() => void onClone()}
                onToggle={() => void onToggleSelected()}
                onArchive={() => void onArchive()}
                onLaunch={() => setLaunchOpen(true)}
                onCancelMission={(id) => void onCancelMission(id)}
                onSelectAgent={setSelectedAgentId}
                onSelectMission={selectMission}
                onDatasetCancel={onDatasetCancel}
                onDatasetRetry={onDatasetRetry}
                onDatasetReindex={onDatasetReindex}
              />
            </div>
            <div className="lv-ag-area-pools">
              <WorkerPoolsPanel
                workers={workersSummary}
                busy={busy}
                onScale={(pid, n) => void onScale(pid, n)}
                onManage={(pid) => setSpawnPoolId(pid ?? pools[0]?.poolId ?? "")}
              />
            </div>
            <div className="lv-ag-area-flow">
              <OrchestrationFlowPanel dashboard={dashboard} live={live} />
            </div>
            <div className="lv-ag-area-lower">
              <MissionQueuePanel
                missions={missions}
                agentById={agentById}
                tab={missionTab}
                selectedMissionId={selectedMissionId}
                busy={busy}
                canLaunch={anyLaunchable}
                onTab={setMissionTab}
                onSelectMission={selectMission}
                onCancel={(id) => void onCancelMission(id)}
                onNew={() => setLaunchOpen(true)}
              />
              <section className="lv-ag-panel lv-ag-signals-wrap">
                <SignalsPanel
                  compact
                  selectedAgentId={selectedAgentId || null}
                  selectedMissionId={selectedMissionId || null}
                  agentNameById={agentNameById}
                />
              </section>
              <div className="lv-ag-stack">
                <AgentPerformancePanel dashboard={dashboard} windowHours={windowHours} onWindow={setWindowHours} />
                <TeamDistributionPanel dashboard={dashboard} />
              </div>
            </div>
            <div className="lv-ag-area-fail">
              <FailureRetryPanel
                dashboard={dashboard}
                windowHours={failureWindowHours}
                onWindow={setFailureWindowHours}
              />
            </div>
          </div>
        </main>

        {archView ? (
          <div className="lv-ag-overlay" role="dialog" aria-modal="true" aria-label="Architecture view" onClick={() => setArchView(false)}>
            <div className="lv-ag-overlay-inner" onClick={(e) => e.stopPropagation()}>
              {architecture(true)}
            </div>
          </div>
        ) : null}

        {coreOpen ? (
          <LeviathanCoreModal
            systemEntries={systemEntries}
            agents={agents}
            summary={summary}
            dashboard={dashboard}
            failureWindowHours={failureWindowHours}
            modelsCount={models.length}
            capabilitiesCount={capabilities.length}
            onSelectEntry={(id) => {
              setSelectedAgentId(id);
              setShowAll(true);
              setCoreOpen(false);
            }}
            onClose={() => setCoreOpen(false)}
          />
        ) : null}

        {spawnPoolId !== null ? (
          <SpawnWorkerModal
            pools={pools}
            initialPoolId={spawnPoolId || undefined}
            supervisorHealth={workersSummary?.supervisorHealth ?? null}
            busy={busy}
            onScale={(pid, n) => void onScale(pid, n)}
            onClose={() => setSpawnPoolId(null)}
          />
        ) : null}

        {launchOpen ? (
          <LaunchMissionModal
            agents={liveFleet}
            initialAgentId={selectedLaunchable ? selectedAgentId : ""}
            agentsEnabled={summary?.agentsEnabled}
            busy={busy}
            onLaunch={(id, payload) => void onLaunch(id, payload)}
            onClose={() => setLaunchOpen(false)}
          />
        ) : null}

        {displayedMissionDetail ? (
          <MissionDetailModal
            detail={displayedMissionDetail}
            missions={missions}
            agentById={agentById}
            busy={busy}
            onSelectMission={selectMission}
            onCancel={(id) => void onCancelMission(id)}
            onClose={() => setMissionDetailOpen(false)}
          />
        ) : null}

        {editorOpen ? (
          <AgentEditorModal
            mode={editorMode}
            draft={draft}
            setDraft={setDraft}
            agents={agents}
            models={models}
            capabilities={capabilities}
            knowledgeDocs={knowledgeDocs}
            editingId={editorMode === "edit" ? selectedAgentId : undefined}
            busy={busy}
            onSave={() => void onSaveEditor()}
            onClose={() => setEditorOpen(false)}
          />
        ) : null}

        {tradeOpen ? (
          <Modal wide title="Trade Orchestra / Trading Agents (paper)" onClose={() => setTradeOpen(false)}>
            <TradeOrchestraSection
              onSelectAgent={(id) => {
                setSelectedAgentId(id);
                setTradeOpen(false);
              }}
              onChanged={() => void loadAll()}
            />
          </Modal>
        ) : null}
      </div>
    </AppShell>
  );
}

