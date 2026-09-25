import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { mediaControlCrops } from "../assets/mediaControlAssets";
import { api, ApiError } from "../api/client";
import { useSystemTelemetry } from "../hooks/useSystemTelemetry";
import { AppShell } from "../layouts/AppShell";
import { formatElapsed, isActiveJobStatus } from "../lib/jobStatus";
import { useAppToast } from "../state/useAppToast";
import type {
  AgentDefinition,
  AgentEvent,
  AgentFleetSummary,
  AgentMission,
  CapabilityListItem,
  DatasetLearningStatus,
  DatasetRecord,
  KnowledgeDocument,
  ModelDescriptor,
  SystemArchitectureEntry,
} from "../types/api";
import {
  AGENT_KINDS,
  APPROVAL_MODES,
  DATASET_ACCESS_POLICIES,
  MEMORY_POLICIES,
  ORCH_FAILURE_STRATEGIES,
  ORCH_STRATEGIES,
  activeMissionsForAgent,
  agentEntityType,
  agentIconKind,
  agentOrigin,
  assignedCapabilityCards,
  canLaunchAgent,
  childMissionsOf,
  deriveRoleOptions,
  deriveStatusOptions,
  draftFromAgent,
  draftToCreatePayload,
  emptyEditorDraft,
  filterEvents,
  filterMissions,
  filterRoster,
  healthLabel,
  isArchitectureEntry,
  isSystemProtected,
  layoutNetworkNodes,
  missionTabCount,
  networkEdgesFromAgents,
  statusTone,
  validateEditorDraft,
  type AgentEditorDraft,
  type LogFilter,
  type MissionTab,
} from "./agents/helpers";
import { SignalsPanel } from "./agents/SignalsPanel";
import { TradeOrchestraSection } from "./agents/TradeOrchestraSection";

const MISSION_TABS: MissionTab[] = [
  "All Tasks",
  "Running",
  "Queued",
  "Completed",
  "Failed",
  "Cancelled",
  "Interrupted",
];
const LOG_FILTERS: LogFilter[] = ["All", "System", "Agents", "Tasks", "Warnings", "Errors"];
const CAPABILITY_TABS = ["Capabilities", "Tools & Integrations", "Datasets", "Knowledge Sources"] as const;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function AgentIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "research":
      return (<><circle cx="11" cy="11" r="6" /><path d="M16 16l3.5 3.5" /></>);
    case "coding":
      return <path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12" />;
    case "trading":
      return <path d="M4 16l5-6 3 3 5-7" />;
    case "memory":
      return (<><ellipse cx="12" cy="8" rx="6" ry="3" /><path d="M6 8v6c0 1.7 2.7 3 6 3s6-1.3 6-3V8" /></>);
    case "media":
      return (<><rect x="4" y="6" width="16" height="12" rx="2" /><path d="M10 10l5 3-5 3z" /></>);
    case "critic":
      return (<><path d="M12 4l7 4v6c0 4-3 6-7 8-4-2-7-4-7-8V8l7-4z" /><path d="M9 12l2 2 4-4" /></>);
    case "planner":
      return (<><rect x="5" y="4" width="14" height="16" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>);
    default:
      return (<><circle cx="12" cy="12" r="7" /><path d="M12 8v4l3 2" /></>);
  }
}

function CapIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "search":
      return (<><circle cx="11" cy="11" r="6" /><path d="M16 16l3.5 3.5" /></>);
    case "code":
      return <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />;
    case "folder":
      return (<><path d="M4 9h16v9H4z" /><path d="M4 9l1.6-2.8h5L12 9" /></>);
    case "brain":
      return <path d="M9 8a3 3 0 015 0 3 3 0 012.5 2.8A3 3 0 0115 16H9a3 3 0 01-1.5-5.2A3 3 0 019 8z" />;
    default:
      return <path d="M5 7h14v8H9l-4 3V7z" />;
  }
}

function SectionTitle({ n, title }: { n: number; title: string }) {
  return (
    <header className="lv-ag-section-head">
      <span className="lv-ag-section-num">{n}.</span>
      <h2>{title}</h2>
    </header>
  );
}

function AgentNetwork({
  agents,
  edges,
  selectedId,
  onSelect,
}: {
  agents: AgentDefinition[];
  edges: Array<{ from: string; to: string; active: boolean }>;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const nodes = useMemo(() => layoutNetworkNodes(agents, edges), [agents, edges]);
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const height = Math.max(230, ...nodes.map((n) => n.y + 40), 230);

  if (nodes.length === 0) {
    return <p className="lv-ag-empty">No agents to visualize.</p>;
  }

  return (
    <div className="lv-ag-network-scroll">
      <svg
        className="lv-ag-network"
        viewBox={`0 0 520 ${height}`}
        role="img"
        aria-label="Agent network"
      >
        {edges.map((link) => {
          const from = byId[link.from];
          const to = byId[link.to];
          if (!from || !to) return null;
          return (
            <line
              key={`${link.from}-${link.to}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              className={`lv-ag-link is-${link.active ? "active" : "idle"}`}
            />
          );
        })}
        {nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${node.x}, ${node.y})`}
            className={`lv-ag-node-hit${selectedId === node.id ? " is-selected" : ""}`}
            onClick={() => onSelect(node.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onSelect(node.id);
            }}
          >
            <circle r={node.hub ? 28 : 22} className={`lv-ag-node${node.hub ? " is-hub" : ""}${selectedId === node.id ? " is-selected" : ""}`} />
            <text textAnchor="middle" dy="4" className="lv-ag-node-label">
              {node.label.length > 14 ? `${node.label.slice(0, 12)}…` : node.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="lv-ag-field">
      <span>{label}</span>
      {children}
      {hint ? <small className="lv-ag-field-hint">{hint}</small> : null}
    </label>
  );
}

function AgentEditorForm({
  draft,
  setDraft,
  agents,
  models,
  capabilities,
  knowledgeDocs,
  editingId,
}: {
  draft: AgentEditorDraft;
  setDraft: (next: AgentEditorDraft) => void;
  agents: AgentDefinition[];
  models: ModelDescriptor[];
  capabilities: CapabilityListItem[];
  knowledgeDocs: KnowledgeDocument[];
  editingId?: string;
}) {
  const memberCandidates = agents.filter(
    (a) => !a.archived && a.agentId !== editingId,
  );

  function toggleCap(id: string) {
    const has = draft.capabilities.includes(id);
    setDraft({
      ...draft,
      capabilities: has
        ? draft.capabilities.filter((c) => c !== id)
        : [...draft.capabilities, id],
    });
  }

  function toggleMember(id: string) {
    const has = draft.memberAgentIds.includes(id);
    setDraft({
      ...draft,
      memberAgentIds: has
        ? draft.memberAgentIds.filter((m) => m !== id)
        : [...draft.memberAgentIds, id],
    });
  }

  function toggleKnowledge(id: string) {
    const has = draft.knowledgeSources.includes(id);
    setDraft({
      ...draft,
      knowledgeSources: has
        ? draft.knowledgeSources.filter((k) => k !== id)
        : [...draft.knowledgeSources, id],
    });
  }

  return (
    <div className="lv-ag-editor-grid">
      <Field label="Name">
        <input
          type="text"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          required
        />
      </Field>
      <Field label="Kind">
        <select
          value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
          disabled={Boolean(editingId)}
        >
          {AGENT_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Role">
        <input
          type="text"
          value={draft.role}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
          placeholder="e.g. Research / Analysis"
        />
      </Field>
      <Field label="Enabled">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
        />
      </Field>
      <Field label="Description" hint="Shown in roster and inspector">
        <textarea
          rows={2}
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        />
      </Field>
      <Field
        label="Model"
        hint="Canonical modelRef from registry — empty means inherit/default runtime semantics"
      >
        <select
          value={draft.modelRef}
          onChange={(e) => setDraft({ ...draft, modelRef: e.target.value })}
        >
          <option value="">(inherit / unset)</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.displayName || m.id}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="System policy"
        hint="Stored on definition; execution still goes through ExecutionGateway"
      >
        <textarea
          rows={2}
          value={draft.systemPolicy}
          onChange={(e) => setDraft({ ...draft, systemPolicy: e.target.value })}
        />
      </Field>
      <Field label="Approval mode">
        <select
          value={draft.approvalMode}
          onChange={(e) => setDraft({ ...draft, approvalMode: e.target.value })}
        >
          {APPROVAL_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label={`Autonomy (${draft.autonomy})`}
        hint="Config metadata 0–100 — not a guarantee of independent tool execution"
      >
        <input
          type="range"
          min={0}
          max={100}
          value={draft.autonomy}
          onChange={(e) => setDraft({ ...draft, autonomy: Number(e.target.value) })}
        />
      </Field>
      <Field label="Max concurrency">
        <input
          type="number"
          min={1}
          max={32}
          value={draft.maxConcurrency}
          onChange={(e) => setDraft({ ...draft, maxConcurrency: Number(e.target.value) })}
        />
      </Field>
      <Field label="Timeout (s)">
        <input
          type="number"
          min={1}
          placeholder="optional"
          value={draft.timeoutS}
          onChange={(e) => setDraft({ ...draft, timeoutS: e.target.value })}
        />
      </Field>
      <Field label="Max retries">
        <input
          type="number"
          min={0}
          max={10}
          value={draft.maxRetries}
          onChange={(e) => setDraft({ ...draft, maxRetries: Number(e.target.value) })}
        />
      </Field>
      <Field label="Token budget">
        <input
          type="number"
          min={1}
          placeholder="optional"
          value={draft.tokenBudget}
          onChange={(e) => setDraft({ ...draft, tokenBudget: e.target.value })}
        />
      </Field>
      <Field label="Memory policy">
        <select
          value={draft.memoryPolicy}
          onChange={(e) => setDraft({ ...draft, memoryPolicy: e.target.value })}
        >
          {MEMORY_POLICIES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Dataset access"
        hint="Policy field on the agent definition — not a per-dataset assignment list"
      >
        <select
          value={draft.datasetAccess}
          onChange={(e) => setDraft({ ...draft, datasetAccess: e.target.value })}
        >
          {DATASET_ACCESS_POLICIES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Tags (comma-separated)">
        <input
          type="text"
          value={draft.tags}
          onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
        />
      </Field>

      <div className="lv-ag-editor-block">
        <h3>Capabilities</h3>
        <p className="lv-ag-field-hint">
          Assigned capability IDs only. Saving persists via PATCH/create — runtime still
          executes through the shared ExecutionGateway.
        </p>
        <div className="lv-ag-check-grid">
          {capabilities.length === 0 ? (
            <p className="lv-ag-empty">Capability registry unavailable or empty.</p>
          ) : (
            capabilities.map((c) => {
              const id = typeof c.id === "string" ? c.id : "";
              if (!id) return null;
              const label = typeof c.name === "string" && c.name ? c.name : id;
              return (
                <label key={id} className="lv-ag-check">
                  <input
                    type="checkbox"
                    checked={draft.capabilities.includes(id)}
                    onChange={() => toggleCap(id)}
                  />
                  <span>{label}</span>
                </label>
              );
            })
          )}
        </div>
      </div>

      <div className="lv-ag-editor-block">
        <h3>Knowledge sources</h3>
        <div className="lv-ag-check-grid">
          {knowledgeDocs.length === 0 ? (
            <p className="lv-ag-empty">No knowledge documents loaded.</p>
          ) : (
            knowledgeDocs.map((doc) => (
              <label key={doc.id} className="lv-ag-check">
                <input
                  type="checkbox"
                  checked={draft.knowledgeSources.includes(doc.id)}
                  onChange={() => toggleKnowledge(doc.id)}
                />
                <span>{doc.title || doc.id}</span>
              </label>
            ))
          )}
        </div>
      </div>

      {draft.kind === "orchestrator" ? (
        <div className="lv-ag-editor-block lv-ag-editor-orch">
          <h3>Orchestrator configuration</h3>
          <div className="lv-ag-editor-grid is-dense">
            <Field label="Strategy">
              <select
                value={draft.strategy}
                onChange={(e) => setDraft({ ...draft, strategy: e.target.value })}
              >
                {ORCH_STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Failure strategy"
              hint="fail_fast stops on first child failure; continue runs remaining members"
            >
              <select
                value={draft.failureStrategy}
                onChange={(e) => setDraft({ ...draft, failureStrategy: e.target.value })}
              >
                {ORCH_FAILURE_STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Max delegation depth">
              <input
                type="number"
                min={1}
                max={16}
                value={draft.maxDelegationDepth}
                onChange={(e) =>
                  setDraft({ ...draft, maxDelegationDepth: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="Parallelism limit">
              <input
                type="number"
                min={1}
                max={32}
                value={draft.parallelismLimit}
                onChange={(e) =>
                  setDraft({ ...draft, parallelismLimit: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="Approval escalation">
              <select
                value={draft.approvalEscalation}
                onChange={(e) => setDraft({ ...draft, approvalEscalation: e.target.value })}
              >
                {APPROVAL_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Verification required">
              <input
                type="checkbox"
                checked={draft.verificationRequired}
                onChange={(e) =>
                  setDraft({ ...draft, verificationRequired: e.target.checked })
                }
              />
            </Field>
            <Field label="Aggregation agent">
              <select
                value={draft.aggregationAgentId}
                onChange={(e) => setDraft({ ...draft, aggregationAgentId: e.target.value })}
              >
                <option value="">(none)</option>
                {memberCandidates.map((a) => (
                  <option key={a.agentId} value={a.agentId}>
                    {a.name} ({a.kind})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Default model fallback">
              <select
                value={draft.defaultModelFallback}
                onChange={(e) =>
                  setDraft({ ...draft, defaultModelFallback: e.target.value })
                }
              >
                <option value="">(none)</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.displayName || m.id}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <h4>Members</h4>
          <div className="lv-ag-check-grid">
            {memberCandidates.length === 0 ? (
              <p className="lv-ag-empty">No eligible member agents.</p>
            ) : (
              memberCandidates.map((a) => (
                <label key={a.agentId} className="lv-ag-check">
                  <input
                    type="checkbox"
                    checked={draft.memberAgentIds.includes(a.agentId)}
                    onChange={() => toggleMember(a.agentId)}
                  />
                  <span>
                    {a.name}{" "}
                    <em>
                      ({a.kind}
                      {a.kind === "orchestrator" ? " · nested" : ""}
                      {!a.enabled ? " · disabled" : ""})
                    </em>
                  </span>
                </label>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function AgentsPage() {
  const toast = useAppToast();
  const { sample: telemetry, error: telemetryError } = useSystemTelemetry({
    enabled: true,
    intervalMs: 4000,
  });

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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [eventsLive, setEventsLive] = useState(true);

  const [roleFilter, setRoleFilter] = useState("All Roles");
  const [statusFilter, setStatusFilter] = useState("All Status");
  const [kindFilter, setKindFilter] = useState("All Kinds");
  const [originFilter, setOriginFilter] = useState("ALL");
  const [entityTypeFilter, setEntityTypeFilter] = useState("ALL TYPES");
  const [showArchived, setShowArchived] = useState(false);
  const [missionTab, setMissionTab] = useState<MissionTab>("All Tasks");
  const [commTab, setCommTab] = useState("Agent Network");
  const [logFilter, setLogFilter] = useState<LogFilter>("All");
  const [capTab, setCapTab] = useState<(typeof CAPABILITY_TABS)[number]>("Capabilities");
  const [query, setQuery] = useState("");
  const [logScopeAgent, setLogScopeAgent] = useState(false);
  const [logScopeMission, setLogScopeMission] = useState(false);

  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [selectedMissionId, setSelectedMissionId] = useState<string>("");
  const [missionDetail, setMissionDetail] = useState<{
    mission: AgentMission;
    children: AgentMission[];
    events: AgentEvent[];
  } | null>(null);
  const [taskRequest, setTaskRequest] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [priority, setPriority] = useState<"low" | "med" | "high">("med");
  const [dryRun, setDryRun] = useState(false);
  const [useJobs, setUseJobs] = useState(false);
  const [cancelMissionId, setCancelMissionId] = useState<string>("");

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<"create" | "edit">("create");
  const [draft, setDraft] = useState<AgentEditorDraft>(emptyEditorDraft());
  const [inspectorEdit, setInspectorEdit] = useState(false);

  const selectedAgentIdRef = useRef(selectedAgentId);
  const loadGen = useRef(0);
  const inflight = useRef(false);

  useEffect(() => {
    selectedAgentIdRef.current = selectedAgentId;
  }, [selectedAgentId]);

  const agentById = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.agentId, a])),
    [agents],
  );

  const architectureAsAgents = useMemo((): AgentDefinition[] => {
    return systemEntries.map((arch) => ({
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
      entityType: arch.entityType,
      systemKey: arch.systemKey,
      mutable: false,
      executable: arch.executable === true,
      metadata: {
        ...(arch.metadata || {}),
        sourceModule: arch.sourceModule,
        relationships: arch.relationships,
        runtimeKind: arch.runtimeKind,
      },
    }));
  }, [systemEntries]);

  const rosterUniverse = useMemo(
    () => [...agents, ...architectureAsAgents],
    [agents, architectureAsAgents],
  );

  const selectedAgent =
    agentById[selectedAgentId] ?? architectureAsAgents.find((a) => a.agentId === selectedAgentId);

  const loadAll = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    const gen = ++loadGen.current;
    setLoadError(null);
    try {
      const [roster, missionRes, eventRes, caps, modelRes, knowledgeRes, datasetRes, learningRes] =
        await Promise.all([
          api.listAgentRoster({ includeArchived: true, includeArchitecture: true }),
          api.listAgentMissions({ limit: 200 }),
          api.listAgentEvents({ limit: 120 }),
          api.listCapabilities({ limit: 500 }).catch(() => ({
            capabilities: [] as CapabilityListItem[],
          })),
          api.listModels().catch(() => ({ models: [] as ModelDescriptor[] })),
          api.listKnowledgeDocuments().catch(() => ({
            documents: [] as KnowledgeDocument[],
          })),
          api.listDatasets(100).catch(() => ({ datasets: [] as DatasetRecord[] })),
          api.getDatasetLearningStatus().catch(() => null),
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
      setEventsLive(true);
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
      setEventsLive(false);
    } finally {
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    void loadAll();
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void loadAll();
    }, 6000);
    return () => window.clearInterval(id);
  }, [loadAll]);

  useEffect(() => {
    if (!selectedMissionId) return;
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
  }, [selectedMissionId, toast, missions]);

  const roleOptions = useMemo(() => deriveRoleOptions(rosterUniverse), [rosterUniverse]);
  const statusOptions = useMemo(() => deriveStatusOptions(rosterUniverse), [rosterUniverse]);

  const roster = useMemo(
    () =>
      filterRoster(rosterUniverse, {
        query,
        roleFilter,
        statusFilter,
        kindFilter,
        showArchived,
        originFilter,
        entityTypeFilter,
      }),
    [
      rosterUniverse,
      query,
      roleFilter,
      statusFilter,
      kindFilter,
      showArchived,
      originFilter,
      entityTypeFilter,
    ],
  );

  const filteredMissions = useMemo(
    () => filterMissions(missions, missionTab),
    [missionTab, missions],
  );

  const filteredEvents = useMemo(
    () =>
      filterEvents(events, logFilter, {
        agentId: logScopeAgent ? selectedAgentId || undefined : undefined,
        missionId: logScopeMission ? selectedMissionId || undefined : undefined,
      }),
    [events, logFilter, logScopeAgent, logScopeMission, selectedAgentId, selectedMissionId],
  );

  const networkEdges = useMemo(() => {
    const fleetEdges = networkEdgesFromAgents(agents);
    const archEdges: Array<{ from: string; to: string; active: boolean }> = [];
    for (const entry of systemEntries) {
      for (const rel of entry.relationships || []) {
        archEdges.push({
          from: entry.id,
          to: rel.targetId,
          active: entry.status === "ready" || entry.status === "busy",
        });
      }
    }
    return [...fleetEdges, ...archEdges];
  }, [agents, systemEntries]);

  const networkAgents = useMemo(() => rosterUniverse, [rosterUniverse]);

  const selectedCaps = useMemo(
    () => assignedCapabilityCards(selectedAgent, capabilities),
    [selectedAgent, capabilities],
  );

  const selectedActiveMissions = useMemo(
    () => (selectedAgentId ? activeMissionsForAgent(missions, selectedAgentId) : []),
    [missions, selectedAgentId],
  );

  const effectiveCancelMissionId = useMemo(() => {
    if (selectedActiveMissions.some((m) => m.missionId === cancelMissionId)) {
      return cancelMissionId;
    }
    return selectedActiveMissions[0]?.missionId ?? "";
  }, [selectedActiveMissions, cancelMissionId]);

  const displayedMissionDetail =
    selectedMissionId && missionDetail?.mission.missionId === selectedMissionId
      ? missionDetail
      : null;

  const resourceRows = useMemo(() => {
    const rows: Array<{ label: string; detail: string; pct: number }> = [];
    if (summary) {
      const busyCount = summary.health.busy ?? 0;
      const total = Math.max(1, summary.agentCount);
      rows.push({
        label: "Active Workers",
        detail: `${busyCount} / ${total}`,
        pct: Math.min(100, Math.round((busyCount / total) * 100)),
      });
      rows.push({
        label: "Active Missions",
        detail: String(summary.activeMissions),
        pct: Math.min(100, summary.activeMissions * 10),
      });
      rows.push({
        label: "Orchestrators",
        detail: String(summary.orchestratorCount),
        pct: Math.min(100, summary.orchestratorCount * 20),
      });
    }
    if (telemetry?.cpu?.available && telemetry.cpu.utilizationPct != null) {
      rows.push({
        label: "CPU Usage",
        detail: `${telemetry.cpu.utilizationPct.toFixed(0)}%`,
        pct: Math.round(telemetry.cpu.utilizationPct),
      });
    }
    if (telemetry?.memory?.available && telemetry.memory.utilizationPct != null) {
      const used = telemetry.memory.usedBytes;
      const total = telemetry.memory.totalBytes;
      rows.push({
        label: "Memory Usage",
        detail:
          used != null && total != null
            ? `${(used / 1024 ** 3).toFixed(1)} / ${(total / 1024 ** 3).toFixed(1)} GB`
            : `${telemetry.memory.utilizationPct.toFixed(0)}%`,
        pct: Math.round(telemetry.memory.utilizationPct),
      });
    }
    if (telemetry?.gpu?.available && telemetry.gpu.devices[0]) {
      const gpu = telemetry.gpu.devices[0];
      if (gpu.utilizationPct != null) {
        rows.push({
          label: "GPU Usage",
          detail: `${gpu.name} · ${gpu.utilizationPct.toFixed(0)}%`,
          pct: Math.round(gpu.utilizationPct),
        });
      }
    }
    if (rows.length === 0) {
      rows.push({
        label: "Resources",
        detail: telemetryError ? "Telemetry unavailable" : "Waiting for measurements",
        pct: 0,
      });
    }
    return rows;
  }, [summary, telemetry, telemetryError]);

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
    setDraft(
      emptyEditorDraft({
        kind: "research",
        role: "Specialist",
      }),
    );
    setEditorOpen(true);
  }

  function openEdit(agent: AgentDefinition) {
    if (isArchitectureEntry(agent)) {
      toast("Architecture components are read-only");
      return;
    }
    setEditorMode("edit");
    setDraft(draftFromAgent(agent));
    setInspectorEdit(true);
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
        await api.updateAgent(
          selectedAgentId,
          payload as Parameters<typeof api.updateAgent>[1],
        );
      }
      setEditorOpen(false);
      setInspectorEdit(false);
    }, editorMode === "create" ? "Agent created" : "Agent saved");
  }

  async function onLaunch() {
    const gate = canLaunchAgent(selectedAgent, summary?.agentsEnabled);
    if (!gate.ok) {
      toast(gate.reason || "Cannot launch");
      return;
    }
    if (!taskRequest.trim()) {
      toast("Task request is required");
      return;
    }
    await withBusy(async () => {
      const mission = await api.launchAgentMission(selectedAgentId, {
        request: taskRequest.trim(),
        title: taskTitle.trim() || undefined,
        priority,
        dryRun,
        useJobs,
      });
      setSelectedMissionId(mission.mission.missionId);
    }, dryRun ? "Dry-run plan complete" : "Mission launched");
  }

  async function onStopSelected() {
    const targetId = effectiveCancelMissionId;
    if (!targetId) {
      toast("No active mission selected to cancel");
      return;
    }
    await withBusy(async () => {
      await api.cancelAgentMission(targetId);
    }, "Cancel requested");
  }

  async function onToggleSelected() {
    if (!selectedAgent) return;
    await withBusy(async () => {
      if (selectedAgent.enabled) await api.disableAgent(selectedAgentId);
      else await api.enableAgent(selectedAgentId);
    }, selectedAgent.enabled ? "Agent disabled" : "Agent enabled");
  }

  async function onClone() {
    if (!selectedAgentId || !selectedAgent) return;
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

  const launchGate = canLaunchAgent(selectedAgent, summary?.agentsEnabled);
  const knowledgeById = useMemo(
    () => Object.fromEntries(knowledgeDocs.map((d) => [d.id, d])),
    [knowledgeDocs],
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Agents Mode"
      searchPlaceholder="Search agents, tasks, workflows, or ask Leviathan..."
      systemItems={[
        summary?.agentsEnabled ? "AGENTS ENABLED" : "AGENTS FEATURE OFF",
        `${summary?.agentCount ?? agents.filter((a) => !a.archived).length} AGENTS`,
        `${summary?.orchestratorCount ?? 0} ORCH`,
        `${summary?.activeMissions ?? 0} ACTIVE`,
      ]}
      layout="wide"
      pageClass="lv-app--agents"
    >
      <div className="lv-ag-shell">
      <main className="lv-main lv-ag-main">
        <section className="lv-ag-hero" aria-label="Agents">
          <div className="lv-ag-hero-media">
            <img src={mediaControlCrops.agentsHeroWide} alt="" width={1600} height={320} />
          </div>
          <div className="lv-ag-hero-shade" />
          <div className="lv-ag-hero-content">
            <p className="lv-ag-hero-kicker">ORCHESTRATE. DELEGATE. EXECUTE.</p>
            <h1 className="lv-ag-hero-title">AGENTS</h1>
            <p className="lv-ag-hero-quote">
              “A multiplicity of minds. A singular purpose.” — LEVIATHAN
            </p>
          </div>
          <aside className="lv-ag-hero-rail" aria-hidden="true">
            <span>HIGHER INTELLIGENCE.</span>
            <span>GREATER LEVERAGE.</span>
            <span>A BRIGHTER TOMORROW.</span>
          </aside>
        </section>

        {summary && !summary.agentsEnabled ? (
          <div className="lv-ag-banner is-warn" role="status">
            Agents feature flag is OFF (`LEVIATHAN_FEATURE_AGENTS`). Definitions remain
            manageable; mission execution is unavailable.
          </div>
        ) : null}

        {loadError ? (
          <div className="lv-ag-panel" style={{ marginBottom: 12 }}>
            <p>{loadError}</p>
            <button type="button" className="lv-ag-btn-gold" onClick={() => void loadAll()}>
              Retry
            </button>
          </div>
        ) : null}

        <div className="lv-ag-ops-bar">
          <button type="button" className="lv-ag-btn-teal" disabled={busy} onClick={() => void loadAll()}>
            Refresh
          </button>
          <button type="button" className="lv-ag-btn-gold" disabled={busy} onClick={openCreate}>
            + Create Agent
          </button>
          <button
            type="button"
            className="lv-ag-btn-stop"
            disabled={busy}
            onClick={() => void onReconcile()}
            title="Mark orphaned active missions interrupted"
          >
            Reconcile Fleet
          </button>
        </div>

        <div className="lv-ag-grid-top">
          <section className="lv-ag-panel">
            <SectionTitle n={1} title="AGENT ROSTER / DIRECTORY" />
            <div className="lv-ag-roster-tools">
              <input
                type="search"
                placeholder="Search agents..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search agents"
              />
              <select
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value)}
                aria-label="Filter by kind"
              >
                <option>All Kinds</option>
                {AGENT_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
                <option value="__archived_only__">Archived only</option>
              </select>
              <select
                value={originFilter}
                onChange={(e) => setOriginFilter(e.target.value)}
                aria-label="Filter by origin"
              >
                <option value="ALL">ALL</option>
                <option value="SYSTEM">SYSTEM</option>
                <option value="USER">USER</option>
              </select>
              <select
                value={entityTypeFilter}
                onChange={(e) => setEntityTypeFilter(e.target.value)}
                aria-label="Filter by entity type"
              >
                <option value="ALL TYPES">ALL TYPES</option>
                <option value="AGENTS">AGENTS</option>
                <option value="ORCHESTRATORS">ORCHESTRATORS</option>
                <option value="ARCHITECTURE">ARCHITECTURE</option>
              </select>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                aria-label="Filter by role"
              >
                <option>All Roles</option>
                {roleOptions.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filter by status"
              >
                <option>All Status</option>
                {statusOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <label className="lv-ag-check is-inline">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                <span>Include archived</span>
              </label>
            </div>
            <div className="lv-ag-roster-grid">
              {roster.length === 0 ? (
                <p className="lv-ag-empty">
                  {agents.length === 0
                    ? "No agents yet. Create one to begin."
                    : "No agents match filters."}
                </p>
              ) : (
                roster.map((agent) => {
                  const label = healthLabel(agent);
                  const orch = agent.orchestrator;
                  const origin = agentOrigin(agent);
                  const entity = agentEntityType(agent);
                  return (
                    <article
                      key={agent.agentId}
                      className={`lv-ag-agent-card${selectedAgentId === agent.agentId ? " is-selected" : ""}`}
                      onClick={() => setSelectedAgentId(agent.agentId)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setSelectedAgentId(agent.agentId);
                      }}
                      role="button"
                      tabIndex={0}
                      aria-pressed={selectedAgentId === agent.agentId}
                    >
                      <div className="lv-ag-agent-head">
                        <span className="lv-ag-agent-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24">
                            <AgentIcon kind={agentIconKind(agent)} />
                          </svg>
                        </span>
                        <div>
                          <strong>{agent.name}</strong>
                          <small>{agent.role || agent.kind}</small>
                        </div>
                        <span className={`lv-ag-status is-${statusTone(label)}`}>
                          <i />
                          {label}
                        </span>
                      </div>
                      <div className="lv-ag-origin-row">
                        <span className={`lv-ag-badge is-${origin}`}>{origin.toUpperCase()}</span>
                        <span className={`lv-ag-badge is-type-${entity}`}>{entity.toUpperCase()}</span>
                      </div>
                      <div className="lv-ag-agent-model">
                        {isArchitectureEntry(agent)
                          ? agent.systemKey
                            ? `systemKey: ${agent.systemKey}`
                            : "architecture descriptor"
                          : agent.modelRef || "model: inherit / unset"}
                      </div>
                      <div className="lv-ag-tags">
                        <span>{agent.kind}</span>
                        {entity === "orchestrator" ? (
                          <span className="is-orch">orchestrator</span>
                        ) : null}
                        {agent.systemKey ? <span>key:{agent.systemKey}</span> : null}
                        {!isArchitectureEntry(agent) ? <span>v{agent.version}</span> : null}
                        {orch ? (
                          <span>
                            {orch.memberAgentIds.length} members · {orch.strategy}
                          </span>
                        ) : null}
                        {agent.tags.slice(0, 3).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                      {agent.healthReason ? (
                        <p className="lv-ag-card-reason">{agent.healthReason}</p>
                      ) : null}
                    </article>
                  );
                })
              )}
            </div>
          </section>

          <div className="lv-ag-top-stack">
            <section className="lv-ag-panel">
              <SectionTitle n={2} title="AGENT STATUS" />
              <div className="lv-ag-table-wrap">
                <table className="lv-ag-table">
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Status</th>
                      <th>Model</th>
                      <th>Kind</th>
                      <th>Active</th>
                      <th>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rosterUniverse.filter((a) => showArchived || !a.archived).map((agent) => {
                      const label = healthLabel(agent);
                      const active = isArchitectureEntry(agent)
                        ? 0
                        : activeMissionsForAgent(missions, agent.agentId).length;
                      const origin = agentOrigin(agent);
                      return (
                        <tr
                          key={agent.agentId}
                          className={selectedAgentId === agent.agentId ? "is-selected" : ""}
                          onClick={() => setSelectedAgentId(agent.agentId)}
                        >
                          <td>
                            <span className="lv-ag-table-agent">
                              <span className="lv-ag-agent-icon is-sm" aria-hidden="true">
                                <svg viewBox="0 0 24 24">
                                  <AgentIcon kind={agentIconKind(agent)} />
                                </svg>
                              </span>
                              {agent.name}
                              <span className={`lv-ag-badge is-inline is-${origin}`}>
                                {origin.toUpperCase()}
                              </span>
                            </span>
                          </td>
                          <td>
                            <span className={`lv-ag-status is-${statusTone(label)}`}>
                              <i />
                              {label}
                            </span>
                          </td>
                          <td title={agent.modelRef || undefined}>
                            {isArchitectureEntry(agent) ? "—" : agent.modelRef || "—"}
                          </td>
                          <td>{agentEntityType(agent)}</td>
                          <td>{active}</td>
                          <td>{agent.lastRunAt ? formatElapsed(agent.lastRunAt) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="lv-ag-panel lv-ag-orchestrator">
              <SectionTitle n={3} title="INSPECTOR / CONTROL" />
              {!selectedAgent ? (
                <p className="lv-ag-empty">Select an agent from the roster.</p>
              ) : (
                <>
                  <div className="lv-ag-inspector-id">
                    <div>
                      <strong>{selectedAgent.name}</strong>
                      <span className="lv-ag-tags">
                        <span className={`lv-ag-badge is-${agentOrigin(selectedAgent)}`}>
                          {agentOrigin(selectedAgent).toUpperCase()}
                        </span>
                        <span className={`lv-ag-badge is-type-${agentEntityType(selectedAgent)}`}>
                          {agentEntityType(selectedAgent).toUpperCase()}
                        </span>
                        <span>{selectedAgent.kind}</span>
                        <span>{selectedAgent.role || "no role"}</span>
                        {selectedAgent.systemKey ? <span>key:{selectedAgent.systemKey}</span> : null}
                        {!isArchitectureEntry(selectedAgent) ? (
                          <span>approval: {selectedAgent.approvalMode}</span>
                        ) : null}
                      </span>
                    </div>
                    <div className="lv-ag-orch-actions">
                      {!isArchitectureEntry(selectedAgent) ? (
                        <>
                          <button
                            type="button"
                            className="lv-ag-btn-teal"
                            disabled={busy || selectedAgent.archived}
                            onClick={() => openEdit(selectedAgent)}
                            title={
                              isSystemProtected(selectedAgent)
                                ? "SYSTEM identity fields are protected server-side"
                                : undefined
                            }
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="lv-ag-btn-teal"
                            disabled={busy}
                            onClick={() => void onClone()}
                          >
                            Clone
                          </button>
                          <button
                            type="button"
                            className="lv-ag-btn-teal"
                            disabled={busy || selectedAgent.archived}
                            onClick={() => void onToggleSelected()}
                          >
                            {selectedAgent.enabled ? "Disable" : "Enable"}
                          </button>
                          <button
                            type="button"
                            className="lv-ag-btn-stop"
                            disabled={busy || selectedAgent.archived || isSystemProtected(selectedAgent)}
                            onClick={() => void onArchive()}
                            title={
                              isSystemProtected(selectedAgent)
                                ? "SYSTEM agents cannot be archived"
                                : undefined
                            }
                          >
                            Archive
                          </button>
                        </>
                      ) : (
                        <span className="lv-ag-field-hint">Architecture entries are read-only.</span>
                      )}
                    </div>
                  </div>

                  <div className="lv-ag-inspector-grid">
                    <div>
                      <h4>Identity</h4>
                      <p>{selectedAgent.description || "No description."}</p>
                      <p className="lv-ag-field-hint">
                        ID: {selectedAgent.agentId}
                        {!isArchitectureEntry(selectedAgent) ? ` · v${selectedAgent.version}` : null}
                        {selectedAgent.systemKey ? ` · systemKey=${selectedAgent.systemKey}` : null}
                      </p>
                      {isArchitectureEntry(selectedAgent) &&
                      Array.isArray(selectedAgent.metadata?.relationships) ? (
                        <div style={{ marginTop: "0.5rem" }}>
                          <h4>Relationships</h4>
                          <ul className="lv-ag-kv">
                            {(
                              selectedAgent.metadata?.relationships as Array<{
                                relation: string;
                                targetId: string;
                                targetSystemKey?: string;
                              }>
                            ).map((rel) => (
                              <li key={`${rel.relation}-${rel.targetId}`}>
                                <span>{rel.relation}</span>
                                <em>{rel.targetSystemKey || rel.targetId}</em>
                              </li>
                            ))}
                          </ul>
                          {typeof selectedAgent.metadata?.sourceModule === "string" ? (
                            <p className="lv-ag-field-hint">
                              module: {selectedAgent.metadata.sourceModule}
                            </p>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                    <div>
                      <h4>Runtime</h4>
                      <ul className="lv-ag-kv">
                        <li>
                          <span>Health</span>
                          <em>
                            {healthLabel(selectedAgent)}
                            {selectedAgent.healthReason ? ` — ${selectedAgent.healthReason}` : ""}
                          </em>
                        </li>
                        <li>
                          <span>Concurrency</span>
                          <em>
                            {selectedActiveMissions.length} / {selectedAgent.maxConcurrency}
                          </em>
                        </li>
                        <li>
                          <span>Timeout / retries</span>
                          <em>
                            {selectedAgent.timeoutS ?? "—"}s / {selectedAgent.maxRetries}
                          </em>
                        </li>
                        <li>
                          <span>Token budget</span>
                          <em>{selectedAgent.tokenBudget ?? "unset"}</em>
                        </li>
                        <li>
                          <span>Autonomy</span>
                          <em>{selectedAgent.autonomy} (config)</em>
                        </li>
                      </ul>
                    </div>
                    <div>
                      <h4>Intelligence / Context</h4>
                      <ul className="lv-ag-kv">
                        <li>
                          <span>Model</span>
                          <em>{selectedAgent.modelRef || "inherit / unset"}</em>
                        </li>
                        <li>
                          <span>Capabilities</span>
                          <em>{selectedAgent.capabilities.length}</em>
                        </li>
                        <li>
                          <span>Knowledge</span>
                          <em>{selectedAgent.knowledgeSources.length}</em>
                        </li>
                        <li>
                          <span>Memory / datasets</span>
                          <em>
                            {selectedAgent.memoryPolicy} / {selectedAgent.datasetAccess}
                          </em>
                        </li>
                      </ul>
                    </div>
                    {selectedAgent.kind === "orchestrator" && selectedAgent.orchestrator ? (
                      <div>
                        <h4>Orchestrator</h4>
                        <ul className="lv-ag-kv">
                          <li>
                            <span>Members</span>
                            <em>{selectedAgent.orchestrator.memberAgentIds.length}</em>
                          </li>
                          <li>
                            <span>Strategy</span>
                            <em>{selectedAgent.orchestrator.strategy}</em>
                          </li>
                          <li>
                            <span>Parallelism</span>
                            <em>{selectedAgent.orchestrator.parallelismLimit}</em>
                          </li>
                          <li>
                            <span>Depth / failure</span>
                            <em>
                              {selectedAgent.orchestrator.maxDelegationDepth} /{" "}
                              {selectedAgent.orchestrator.failureStrategy}
                            </em>
                          </li>
                          <li>
                            <span>Verification</span>
                            <em>
                              {selectedAgent.orchestrator.verificationRequired ? "required" : "off"}
                            </em>
                          </li>
                        </ul>
                        <ul className="lv-ag-member-list">
                          {selectedAgent.orchestrator.memberAgentIds.map((mid) => {
                            const m = agentById[mid];
                            return (
                              <li key={mid}>
                                <button
                                  type="button"
                                  className="lv-ag-linkish"
                                  onClick={() => setSelectedAgentId(mid)}
                                >
                                  {m?.name ?? mid.slice(0, 12)}
                                </button>
                                <span>
                                  {m
                                    ? `${m.kind} · ${healthLabel(m)}${!m.enabled ? " · disabled" : ""}`
                                    : "missing"}
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                  </div>

                  <div className="lv-ag-orch-fields">
                    <label>
                      <span>Task title (optional)</span>
                      <input
                        type="text"
                        value={taskTitle}
                        onChange={(e) => setTaskTitle(e.target.value)}
                      />
                    </label>
                    <label>
                      <span>Task request</span>
                      <input
                        type="text"
                        value={taskRequest}
                        onChange={(e) => setTaskRequest(e.target.value)}
                        placeholder="Describe the mission request"
                      />
                    </label>
                    <div className="lv-ag-priority">
                      <span>Priority</span>
                      <div>
                        {(["low", "med", "high"] as const).map((p) => (
                          <button
                            key={p}
                            type="button"
                            className={priority === p ? "is-active" : ""}
                            onClick={() => setPriority(p)}
                          >
                            {p}
                          </button>
                        ))}
                      </div>
                    </div>
                    <label>
                      <span>
                        Dry-run plan only{" "}
                        <input
                          type="checkbox"
                          checked={dryRun}
                          onChange={(e) => setDryRun(e.target.checked)}
                        />
                      </span>
                    </label>
                    <label>
                      <span>
                        useJobs{" "}
                        <input
                          type="checkbox"
                          checked={useJobs}
                          onChange={(e) => setUseJobs(e.target.checked)}
                        />
                      </span>
                    </label>
                    {selectedActiveMissions.length > 0 ? (
                      <label>
                        <span>Cancel target mission</span>
                        <select
                          value={effectiveCancelMissionId}
                          onChange={(e) => setCancelMissionId(e.target.value)}
                        >
                          {selectedActiveMissions.map((m) => (
                            <option key={m.missionId} value={m.missionId}>
                              {m.title.slice(0, 40)} · {m.status} · {m.missionId.slice(0, 10)}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                  </div>
                  <div className="lv-ag-orch-actions">
                    <button
                      type="button"
                      className="lv-ag-btn-gold"
                      disabled={busy || !launchGate.ok}
                      onClick={() => void onLaunch()}
                      title={launchGate.reason}
                    >
                      Launch / Deploy
                    </button>
                    <button
                      type="button"
                      className="lv-ag-btn-stop"
                      disabled={busy || selectedActiveMissions.length === 0}
                      onClick={() => void onStopSelected()}
                    >
                      Cancel Mission
                    </button>
                  </div>
                  {!launchGate.ok ? (
                    <p className="lv-ag-empty">{launchGate.reason}</p>
                  ) : null}
                </>
              )}
            </section>
          </div>
        </div>

        <div className="lv-ag-grid-mid">
          <section className="lv-ag-panel">
            <div className="lv-ag-panel-bar">
              <SectionTitle n={4} title="ACTIVE MISSIONS / TASKS" />
              <button
                type="button"
                className="lv-ag-btn-teal"
                disabled={busy || !launchGate.ok}
                onClick={() => {
                  setMissionTab("All Tasks");
                  void onLaunch();
                }}
              >
                + New Task
              </button>
            </div>
            <div className="lv-ag-tabs lv-ag-tabs-wrap">
              {MISSION_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={missionTab === tab ? "is-active" : ""}
                  onClick={() => setMissionTab(tab)}
                >
                  {tab} ({missionTabCount(missions, tab)})
                </button>
              ))}
            </div>
            <div className="lv-ag-table-wrap">
              <table className="lv-ag-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Task</th>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Progress</th>
                    <th>Elapsed</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredMissions.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="lv-ag-empty">
                        No missions in this filter.
                      </td>
                    </tr>
                  ) : (
                    filteredMissions.map((m) => {
                      const agent = agentById[m.agentId];
                      const pct = Math.round((m.progress || 0) * 100);
                      return (
                        <tr
                          key={m.missionId}
                          className={selectedMissionId === m.missionId ? "is-selected" : ""}
                          onClick={() => setSelectedMissionId(m.missionId)}
                        >
                          <td title={m.missionId}>{m.missionId.slice(0, 12)}</td>
                          <td title={m.title}>
                            {m.title}
                            {m.parentMissionId ? (
                              <small className="lv-ag-parent-tag"> child</small>
                            ) : null}
                          </td>
                          <td>{agent?.name ?? m.agentId.slice(0, 8)}</td>
                          <td>
                            <span
                              className={`lv-ag-pill is-${isActiveJobStatus(m.status) ? "cyan" : "muted"}`}
                            >
                              {m.status}
                            </span>
                          </td>
                          <td>
                            <span className={`lv-ag-prio is-${m.priority}`}>{m.priority}</span>
                          </td>
                          <td>
                            <div className="lv-ag-prog">
                              <div className="lv-ag-prog-track">
                                <span style={{ width: `${pct}%` }} />
                              </div>
                              <em>{pct}%</em>
                            </div>
                          </td>
                          <td>{formatElapsed(m.startedAt || m.createdAt, m.finishedAt)}</td>
                          <td>
                            {isActiveJobStatus(m.status) ? (
                              <button
                                type="button"
                                className="lv-ag-btn-stop"
                                disabled={busy}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void withBusy(async () => {
                                    await api.cancelAgentMission(m.missionId);
                                  }, "Cancelled");
                                }}
                              >
                                Cancel
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {displayedMissionDetail ? (
              <div className="lv-ag-mission-detail">
                <h3>Mission detail</h3>
                <ul className="lv-ag-kv">
                  <li>
                    <span>Title</span>
                    <em>{displayedMissionDetail.mission.title}</em>
                  </li>
                  <li>
                    <span>Status</span>
                    <em>{displayedMissionDetail.mission.status}</em>
                  </li>
                  <li>
                    <span>Trace</span>
                    <em>{displayedMissionDetail.mission.traceId || "—"}</em>
                  </li>
                  <li>
                    <span>Parent</span>
                    <em>{displayedMissionDetail.mission.parentMissionId || "—"}</em>
                  </li>
                  <li>
                    <span>Jobs</span>
                    <em>
                      {displayedMissionDetail.mission.jobIds.length
                        ? displayedMissionDetail.mission.jobIds.join(", ")
                        : "—"}
                    </em>
                  </li>
                  <li>
                    <span>Error</span>
                    <em>{displayedMissionDetail.mission.error || "—"}</em>
                  </li>
                </ul>
                {displayedMissionDetail.children.length > 0 ? (
                  <>
                    <h4>Child missions</h4>
                    <ul className="lv-ag-member-list">
                      {displayedMissionDetail.children.map((c) => (
                        <li key={c.missionId}>
                          <button
                            type="button"
                            className="lv-ag-linkish"
                            onClick={() => setSelectedMissionId(c.missionId)}
                          >
                            {c.title}
                          </button>
                          <span>
                            {agentById[c.agentId]?.name ?? c.agentId.slice(0, 8)} · {c.status} ·{" "}
                            {Math.round((c.progress || 0) * 100)}%
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : childMissionsOf(missions, displayedMissionDetail.mission.missionId).length > 0 ? (
                  <>
                    <h4>Child missions</h4>
                    <ul className="lv-ag-member-list">
                      {childMissionsOf(missions, displayedMissionDetail.mission.missionId).map((c) => (
                        <li key={c.missionId}>
                          <button
                            type="button"
                            className="lv-ag-linkish"
                            onClick={() => setSelectedMissionId(c.missionId)}
                          >
                            {c.title}
                          </button>
                          <span>
                            {agentById[c.agentId]?.name ?? c.agentId.slice(0, 8)} · {c.status}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="lv-ag-empty">No child missions.</p>
                )}
                {displayedMissionDetail.mission.result ? (
                  <details className="lv-ag-raw">
                    <summary>Technical result / plan</summary>
                    <pre>{JSON.stringify(displayedMissionDetail.mission.result, null, 2)}</pre>
                  </details>
                ) : null}
                {displayedMissionDetail.events.length > 0 ? (
                  <ul className="lv-ag-logs">
                    {displayedMissionDetail.events.slice(0, 12).map((e) => (
                      <li key={e.eventId}>
                        <time>{e.createdAt.slice(11, 19)}</time>
                        <span className="lv-ag-log-src">[{e.category}]</span>
                        <span className="lv-ag-log-text">{e.message}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="lv-ag-panel">
            <SectionTitle n={5} title="COMMUNICATION / COORDINATION" />
            <div className="lv-ag-tabs">
              {["Agent Network", "Delegation Chain", "Message Log", "Signals"].map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={commTab === tab ? "is-active" : ""}
                  onClick={() => setCommTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
            {commTab === "Agent Network" ? (
              <>
                <AgentNetwork
                  agents={networkAgents.filter((a) => !a.archived)}
                  edges={networkEdges}
                  selectedId={selectedAgentId}
                  onSelect={setSelectedAgentId}
                />
                <div className="lv-ag-net-legend">
                  <span>
                    <i className="is-active" /> Active Link
                  </span>
                  <span>
                    <i className="is-idle" /> Idle Link
                  </span>
                  <span>
                    {agents.filter((a) => !a.archived && a.kind === "orchestrator").length}{" "}
                    orchestrator(s)
                  </span>
                </div>
              </>
            ) : null}
            {commTab === "Delegation Chain" ? (
              <ul className="lv-ag-logs">
                {missions
                  .filter((m) => m.parentMissionId)
                  .slice(0, 40)
                  .map((m) => (
                    <li key={m.missionId}>
                      <time>{m.createdAt.slice(11, 19)}</time>
                      <span className="lv-ag-log-src">
                        [{agentById[m.agentId]?.name ?? m.agentId.slice(0, 8)}]
                      </span>
                      <button
                        type="button"
                        className="lv-ag-linkish lv-ag-log-text"
                        onClick={() => setSelectedMissionId(m.missionId)}
                      >
                        child of {m.parentMissionId?.slice(0, 12)} · {m.status} · {m.title}
                      </button>
                    </li>
                  ))}
                {missions.every((m) => !m.parentMissionId) ? (
                  <li className="lv-ag-empty">
                    No delegation chains yet — launch an orchestrator mission.
                  </li>
                ) : null}
              </ul>
            ) : null}
            {commTab === "Message Log" ? (
              <ul className="lv-ag-logs">
                {filteredEvents.slice(0, 20).map((e) => (
                  <li key={e.eventId}>
                    <time>{e.createdAt.slice(11, 19)}</time>
                    <span className="lv-ag-log-src">[{e.category}]</span>
                    <span className="lv-ag-log-text">{e.message}</span>
                  </li>
                ))}
                {filteredEvents.length === 0 ? (
                  <li className="lv-ag-empty">No events for current filters.</li>
                ) : null}
              </ul>
            ) : null}
            {commTab === "Signals" ? (
              <SignalsPanel
                selectedAgentId={selectedAgentId}
                selectedMissionId={selectedMissionId}
                agentNameById={Object.fromEntries(
                  Object.entries(agentById).map(([id, a]) => [id, a.name]),
                )}
              />
            ) : null}
          </section>

          <section className="lv-ag-panel">
            <SectionTitle n={6} title="RESOURCES / SYSTEM USAGE" />
            <div className="lv-ag-usage">
              {resourceRows.map((row) => (
                <div key={row.label} className="lv-ag-usage-row">
                  <div className="lv-ag-usage-meta">
                    <span>{row.label}</span>
                    <em>{row.detail}</em>
                  </div>
                  <div className="lv-ag-prog-track is-seg">
                    <span style={{ width: `${row.pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
            {summary ? (
              <p className="lv-ag-field-hint">
                Fleet summary: {summary.agentCount} agents · {summary.recentMissions} recent
                missions · feature {summary.agentsEnabled ? "on" : "off"}
              </p>
            ) : null}
          </section>
        </div>

        <div className="lv-ag-grid-bot">
          <section className="lv-ag-panel">
            <div className="lv-ag-panel-bar">
              <SectionTitle n={7} title="LOGS / EVENT TIMELINE" />
              <span className={`lv-ag-live${eventsLive ? "" : " is-stale"}`}>
                <i /> {eventsLive ? "Live" : "Stale"}
              </span>
            </div>
            <div className="lv-ag-tabs">
              {LOG_FILTERS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={logFilter === tab ? "is-active" : ""}
                  onClick={() => setLogFilter(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="lv-ag-log-scopes">
              <label className="lv-ag-check is-inline">
                <input
                  type="checkbox"
                  checked={logScopeAgent}
                  onChange={(e) => setLogScopeAgent(e.target.checked)}
                />
                <span>Selected agent</span>
              </label>
              <label className="lv-ag-check is-inline">
                <input
                  type="checkbox"
                  checked={logScopeMission}
                  onChange={(e) => setLogScopeMission(e.target.checked)}
                />
                <span>Selected mission</span>
              </label>
            </div>
            <ul className="lv-ag-logs">
              {filteredEvents.length === 0 ? (
                <li className="lv-ag-empty">No events yet.</li>
              ) : (
                filteredEvents.map((log) => (
                  <li key={log.eventId}>
                    <time>{log.createdAt.slice(11, 19)}</time>
                    <span className="lv-ag-log-src">
                      [{agentById[log.agentId ?? ""]?.name ?? log.category}]
                    </span>
                    <span className="lv-ag-log-text">{log.message}</span>
                    <em>{log.level}</em>
                  </li>
                ))
              )}
            </ul>
          </section>

          <section className="lv-ag-panel">
            <div className="lv-ag-panel-bar">
              <SectionTitle n={8} title="KNOWLEDGE / SKILLS / TOOL ACCESS" />
              <button
                type="button"
                className="lv-ag-btn-teal"
                disabled={busy}
                onClick={() => void loadAll()}
              >
                Refresh
              </button>
            </div>
            <div className="lv-ag-tabs">
              {CAPABILITY_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={capTab === tab ? "is-active" : ""}
                  onClick={() => setCapTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="lv-ag-cap-grid">
              {capTab === "Capabilities" ? (
                selectedCaps.length === 0 ? (
                  <p className="lv-ag-empty">
                    No capabilities assigned to selected agent.
                    {capabilities.length > 0
                      ? ` Registry has ${capabilities.length} available capabilities — assign via Edit.`
                      : ""}
                  </p>
                ) : (
                  selectedCaps.map((cap) => (
                    <div key={cap.id} className="lv-ag-cap-card">
                      <span className="lv-ag-agent-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24">
                          <CapIcon kind="search" />
                        </svg>
                      </span>
                      <strong>{cap.title}</strong>
                      <small>{cap.desc}</small>
                    </div>
                  ))
                )
              ) : null}
              {capTab === "Tools & Integrations" ? (
                selectedCaps.length === 0 ? (
                  <p className="lv-ag-empty">
                    No assigned capabilities to map to tools. Integrations derive from
                    assigned capability IDs only.
                  </p>
                ) : (
                  selectedCaps.map((cap) => {
                    const reg = capabilities.find((c) => c.id === cap.id);
                    return (
                      <div key={cap.id} className="lv-ag-cap-card">
                        <span className="lv-ag-agent-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24">
                            <CapIcon kind="code" />
                          </svg>
                        </span>
                        <strong>{cap.title}</strong>
                        <small>
                          {reg?.provider_kind
                            ? `provider: ${String(reg.provider_kind)}`
                            : "No provider metadata — capability ID only"}
                          {reg?.available === false ? " · unavailable" : ""}
                        </small>
                      </div>
                    );
                  })
                )
              ) : null}
              {capTab === "Datasets" ? (
                <div className="lv-ag-policy-block">
                  <p>
                    Dataset access policy:{" "}
                    <strong>{selectedAgent?.datasetAccess ?? "none"}</strong>
                  </p>
                  <p className="lv-ag-field-hint">
                    Dataset Learning mirrors real <code>dataset_jobs</code> — not fictional
                    missions. Active index jobs:{" "}
                    {datasetLearning?.activity.activeCount ?? 0}
                  </p>
                  {(datasetLearning?.activity.active?.length || 0) > 0 ? (
                    <ul className="lv-ag-member-list">
                      {datasetLearning!.activity.active.map((job) => {
                        const act = job.activity;
                        const pct =
                          act?.progress != null
                            ? `${Math.round(Number(act.progress) * 100)}%`
                            : "—";
                        return (
                          <li key={job.jobId}>
                            <span>
                              {act?.datasetName || act?.datasetId || job.datasetId || "dataset"} ·{" "}
                              {act?.phase || job.phase || "—"} · {pct}
                              {act?.processed != null ? ` · rows ${act.processed}` : ""}
                              {act?.chunkCount != null ? ` · chunks ${act.chunkCount}` : ""}
                              {act?.relationsAccepted != null
                                ? ` · rel +${act.relationsAccepted}/−${act.relationsRejected ?? 0}`
                                : ""}
                              {act?.embeddingMode ? ` · ${act.embeddingMode}` : ""}
                              {act?.embeddingsSemantic === false
                                ? " (not semantic)"
                                : ""}
                            </span>
                            <span className="lv-ag-inline-actions">
                              <button
                                type="button"
                                className="lv-ag-btn-stop"
                                disabled={busy}
                                onClick={() => {
                                  void (async () => {
                                    setBusy(true);
                                    try {
                                      await api.cancelDatasetJob(job.jobId);
                                      toast("Dataset job cancel requested");
                                      await loadAll();
                                    } catch (err) {
                                      toast(errMsg(err, "Cancel failed"));
                                    } finally {
                                      setBusy(false);
                                    }
                                  })();
                                }}
                              >
                                Cancel
                              </button>
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="lv-ag-empty">No active dataset index jobs.</p>
                  )}
                  {(datasetLearning?.activity.recent?.length || 0) > 0 ? (
                    <>
                      <p className="lv-ag-field-hint">Recent index jobs</p>
                      <ul className="lv-ag-member-list">
                        {datasetLearning!.activity.recent.slice(0, 8).map((job) => {
                          const act = job.activity;
                          const terminal = ["failed", "cancelled", "interrupted"].includes(
                            String(job.status).toLowerCase(),
                          );
                          return (
                            <li key={`recent-${job.jobId}`}>
                              <span>
                                {act?.datasetName || job.datasetId || "dataset"} · {job.status}
                                {act?.phase ? ` · ${act.phase}` : ""}
                                {act?.error ? ` · ${String(act.error).slice(0, 80)}` : ""}
                              </span>
                              <span className="lv-ag-inline-actions">
                                {terminal ? (
                                  <button
                                    type="button"
                                    className="lv-ag-btn-teal"
                                    disabled={busy}
                                    onClick={() => {
                                      void (async () => {
                                        setBusy(true);
                                        try {
                                          await api.retryDatasetJob(job.jobId, true);
                                          toast("Dataset job re-queued (resume)");
                                          await loadAll();
                                        } catch (err) {
                                          toast(errMsg(err, "Retry failed"));
                                        } finally {
                                          setBusy(false);
                                        }
                                      })();
                                    }}
                                  >
                                    Retry
                                  </button>
                                ) : null}
                                {job.datasetId && job.status === "completed" ? (
                                  <button
                                    type="button"
                                    className="lv-ag-btn-teal"
                                    disabled={busy}
                                    onClick={() => {
                                      if (
                                        !window.confirm(
                                          "Rebuild replaces existing learned results for this dataset. Continue?",
                                        )
                                      ) {
                                        return;
                                      }
                                      void (async () => {
                                        setBusy(true);
                                        try {
                                          await api.learnDataset(String(job.datasetId), {
                                            rebuild: true,
                                          });
                                          toast("Re-index queued");
                                          await loadAll();
                                        } catch (err) {
                                          toast(errMsg(err, "Re-index failed"));
                                        } finally {
                                          setBusy(false);
                                        }
                                      })();
                                    }}
                                  >
                                    Re-index
                                  </button>
                                ) : null}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </>
                  ) : null}
                  <p className="lv-ag-field-hint">
                    Fleet datasets available in the system ({datasets.length}):
                  </p>
                  {datasets.length === 0 ? (
                    <p className="lv-ag-empty">No datasets registered.</p>
                  ) : (
                    <ul className="lv-ag-member-list">
                      {datasets.slice(0, 12).map((d) => (
                        <li key={d.datasetId}>
                          <span>{d.name}</span>
                          <span>
                            {d.status} · {d.sourceType}
                            {d.brainStatus ? ` · brain:${d.brainStatus}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
              {capTab === "Knowledge Sources" ? (
                !selectedAgent || selectedAgent.knowledgeSources.length === 0 ? (
                  <p className="lv-ag-empty">
                    No knowledge sources assigned to selected agent.
                  </p>
                ) : (
                  selectedAgent.knowledgeSources.map((id) => (
                    <div key={id} className="lv-ag-cap-card">
                      <span className="lv-ag-agent-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24">
                          <CapIcon kind="brain" />
                        </svg>
                      </span>
                      <strong>{knowledgeById[id]?.title || id}</strong>
                      <small>{knowledgeById[id]?.source || id}</small>
                    </div>
                  ))
                )
              ) : null}
            </div>
          </section>

          <section className="lv-ag-panel lv-ag-panel-trading">
            <SectionTitle n={9} title="TRADE ORKESTEN / TRADING AGENTS (PAPER)" />
            <TradeOrchestraSection
              onSelectAgent={(id) => setSelectedAgentId(id)}
              onChanged={() => void loadAll()}
            />
          </section>
        </div>
      </main>

      {editorOpen ? (
        <div
          className="lv-ag-modal-backdrop"
          role="presentation"
          onClick={() => {
            setEditorOpen(false);
            setInspectorEdit(false);
          }}
        >
          <div
            className="lv-ag-modal"
            role="dialog"
            aria-modal="true"
            aria-label={editorMode === "create" ? "Create agent" : "Edit agent"}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="lv-ag-modal-head">
              <h2>{editorMode === "create" ? "Create Agent" : `Edit ${draft.name}`}</h2>
              <button
                type="button"
                className="lv-ag-btn-stop"
                onClick={() => {
                  setEditorOpen(false);
                  setInspectorEdit(false);
                }}
              >
                Close
              </button>
            </header>
            <AgentEditorForm
              draft={draft}
              setDraft={setDraft}
              agents={agents}
              models={models}
              capabilities={capabilities}
              knowledgeDocs={knowledgeDocs}
              editingId={editorMode === "edit" ? selectedAgentId : undefined}
            />
            <footer className="lv-ag-modal-foot">
              <button
                type="button"
                className="lv-ag-btn-gold"
                disabled={busy}
                onClick={() => void onSaveEditor()}
              >
                {editorMode === "create" ? "Create" : "Save changes"}
              </button>
              {inspectorEdit ? (
                <span className="lv-ag-field-hint">Persists via PATCH /api/agents/{"{id}"}</span>
              ) : (
                <span className="lv-ag-field-hint">Persists via POST /api/agents</span>
              )}
            </footer>
          </div>
        </div>
      ) : null}
      </div>
    </AppShell>
  );
}
