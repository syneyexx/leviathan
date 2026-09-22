import { useCallback, useEffect, useMemo, useState } from "react";
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
} from "../types/api";

const MISSION_TABS = ["All Tasks", "Running", "Queued", "Completed"] as const;
const LOG_FILTERS = ["All", "System", "Agents", "Tasks", "Warnings", "Errors"] as const;
const CAPABILITY_TABS = ["Capabilities", "Tools & Integrations", "Datasets", "Knowledge Sources"] as const;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function healthLabel(agent: AgentDefinition): string {
  const h = String(agent.health || "").toLowerCase();
  if (!agent.enabled || h === "disabled") return "Offline";
  if (h === "busy") return "Busy";
  if (h === "idle") return "Idle";
  if (h === "error") return "Offline";
  if (h === "archived") return "Offline";
  return "Online";
}

function statusTone(label: string) {
  if (label === "Online" || label === "Idle") return "ok";
  if (label === "Busy") return "warn";
  if (label === "Idle") return "cyan";
  return "off";
}

function agentIconKind(agent: AgentDefinition): string {
  const kind = String(agent.kind).toLowerCase();
  if (kind === "research") return "research";
  if (kind === "coding") return "coding";
  if (kind === "orchestrator") return "planner";
  if (agent.tags.includes("trading") || agent.name.toLowerCase().includes("trading")) return "trading";
  if (agent.tags.includes("media") || agent.name.toLowerCase().includes("media")) return "media";
  if (agent.tags.includes("memory") || agent.name.toLowerCase().includes("memory")) return "memory";
  if (agent.tags.includes("review") || agent.name.toLowerCase().includes("critic")) return "critic";
  return "execution";
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
}: {
  agents: AgentDefinition[];
  edges: Array<{ from: string; to: string; active: boolean }>;
}) {
  const orch = agents.find((a) => a.kind === "orchestrator");
  const members = agents.filter((a) => a.kind !== "orchestrator").slice(0, 6);
  const nodes: Array<{ id: string; label: string; x: number; y: number; hub?: boolean }> = [];
  if (orch) {
    nodes.push({ id: orch.agentId, label: orch.name, x: 200, y: 110, hub: true });
  }
  const positions = [
    [70, 40],
    [200, 28],
    [330, 40],
    [60, 170],
    [200, 200],
    [340, 170],
  ];
  members.forEach((m, i) => {
    const [x, y] = positions[i] ?? [200, 110];
    nodes.push({ id: m.agentId, label: m.name, x, y });
  });
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const linkSet =
    edges.length > 0
      ? edges
      : orch
        ? members.map((m) => ({
            from: orch.agentId,
            to: m.agentId,
            active: healthLabel(m) === "Busy",
          }))
        : [];

  return (
    <svg className="lv-ag-network" viewBox="0 0 400 230" role="img" aria-label="Agent network">
      {linkSet.map((link) => {
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
        <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
          <circle r={node.hub ? 28 : 22} className={`lv-ag-node${node.hub ? " is-hub" : ""}`} />
          <text textAnchor="middle" dy="4" className="lv-ag-node-label">
            {node.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function AgentsPage() {
  const toast = useAppToast();
  const { sample: telemetry, error: telemetryError } = useSystemTelemetry({ enabled: true, intervalMs: 4000 });

  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [summary, setSummary] = useState<AgentFleetSummary | null>(null);
  const [missions, setMissions] = useState<AgentMission[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [eventsLive, setEventsLive] = useState(true);

  const [roleFilter, setRoleFilter] = useState("All Roles");
  const [statusFilter, setStatusFilter] = useState("All Status");
  const [missionTab, setMissionTab] = useState<(typeof MISSION_TABS)[number]>("All Tasks");
  const [commTab, setCommTab] = useState("Agent Network");
  const [logFilter, setLogFilter] = useState<(typeof LOG_FILTERS)[number]>("All");
  const [capTab, setCapTab] = useState<(typeof CAPABILITY_TABS)[number]>("Capabilities");
  const [query, setQuery] = useState("");

  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [taskRequest, setTaskRequest] = useState("search leviathan agent capabilities");
  const [priority, setPriority] = useState<"low" | "med" | "high">("high");
  const [dryRun, setDryRun] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createKind, setCreateKind] = useState("research");

  const agentById = useMemo(() => Object.fromEntries(agents.map((a) => [a.agentId, a])), [agents]);

  const loadAll = useCallback(async () => {
    setLoadError(null);
    try {
      const [fleet, missionRes, eventRes, caps] = await Promise.all([
        api.listAgents(),
        api.listAgentMissions({ limit: 100 }),
        api.listAgentEvents({ limit: 80 }),
        api.listCapabilities().catch(() => ({ capabilities: [] as CapabilityListItem[] })),
      ]);
      setAgents(fleet.agents);
      setSummary(fleet.summary);
      setMissions(missionRes.missions);
      setEvents(eventRes.events);
      setCapabilities(caps.capabilities ?? []);
      setEventsLive(true);
      if (!selectedAgentId && fleet.agents.length > 0) {
        const preferred =
          fleet.agents.find((a) => a.kind === "coding") ??
          fleet.agents.find((a) => a.enabled) ??
          fleet.agents[0];
        setSelectedAgentId(preferred.agentId);
      }
    } catch (err) {
      setLoadError(errMsg(err, "Failed to load agent fleet"));
      setEventsLive(false);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    void loadAll();
    const id = window.setInterval(() => void loadAll(), 5000);
    return () => window.clearInterval(id);
  }, [loadAll]);

  const roster = useMemo(() => {
    return agents.filter((agent) => {
      if (agent.archived) return false;
      if (query && !agent.name.toLowerCase().includes(query.toLowerCase())) return false;
      const label = healthLabel(agent);
      if (statusFilter !== "All Status" && label !== statusFilter) return false;
      if (roleFilter !== "All Roles" && !agent.role.toLowerCase().includes(roleFilter.toLowerCase())) return false;
      return true;
    });
  }, [agents, query, roleFilter, statusFilter]);

  const filteredMissions = useMemo(() => {
    if (missionTab === "All Tasks") return missions;
    if (missionTab === "Completed") return missions.filter((m) => m.status === "completed");
    if (missionTab === "Running") return missions.filter((m) => isActiveJobStatus(m.status) && m.status !== "queued");
    return missions.filter((m) => m.status === "queued");
  }, [missionTab, missions]);

  const filteredEvents = useMemo(() => {
    if (logFilter === "All") return events;
    const map: Record<string, string[]> = {
      System: ["system"],
      Agents: ["agents"],
      Tasks: ["tasks"],
      Warnings: ["warn", "warning"],
      Errors: ["errors", "error"],
    };
    const wanted = map[logFilter] ?? [];
    return events.filter((e) => wanted.includes(e.category) || wanted.includes(e.level));
  }, [events, logFilter]);

  const networkEdges = useMemo(() => {
    const edges: Array<{ from: string; to: string; active: boolean }> = [];
    for (const agent of agents) {
      if (agent.kind !== "orchestrator" || !agent.orchestrator) continue;
      for (const memberId of agent.orchestrator.memberAgentIds) {
        const member = agentById[memberId];
        edges.push({
          from: agent.agentId,
          to: memberId,
          active: member ? healthLabel(member) === "Busy" : false,
        });
      }
    }
    return edges;
  }, [agents, agentById]);

  const resourceRows = useMemo(() => {
    const rows: Array<{ label: string; detail: string; pct: number }> = [];
    if (summary) {
      const busy = summary.health.busy ?? 0;
      const total = Math.max(1, summary.agentCount);
      rows.push({
        label: "Active Workers",
        detail: `${busy} / ${total}`,
        pct: Math.min(100, Math.round((busy / total) * 100)),
      });
      rows.push({
        label: "Active Missions",
        detail: String(summary.activeMissions),
        pct: Math.min(100, summary.activeMissions * 10),
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

  async function onLaunch() {
    if (!selectedAgentId) {
      toast("Select an agent first");
      return;
    }
    if (!taskRequest.trim()) {
      toast("Task request is required");
      return;
    }
    await withBusy(async () => {
      await api.launchAgentMission(selectedAgentId, {
        request: taskRequest.trim(),
        priority,
        dryRun,
      });
    }, dryRun ? "Dry-run plan complete" : "Mission launched");
  }

  async function onStopSelected() {
    const active = missions.find(
      (m) => m.agentId === selectedAgentId && isActiveJobStatus(m.status),
    );
    if (!active) {
      toast("No active mission for selected agent");
      return;
    }
    await withBusy(async () => {
      await api.cancelAgentMission(active.missionId);
    }, "Cancel requested");
  }

  async function onCreateAgent() {
    if (!createName.trim()) {
      toast("Agent name required");
      return;
    }
    await withBusy(async () => {
      const created = await api.createAgent({
        name: createName.trim(),
        kind: createKind,
        role: createKind === "orchestrator" ? "Goals & Decomposition" : "Specialist",
        orchestrator:
          createKind === "orchestrator"
            ? { memberAgentIds: agents.filter((a) => a.kind !== "orchestrator").slice(0, 3).map((a) => a.agentId) }
            : undefined,
      });
      setCreateName("");
      setSelectedAgentId(created.agent.agentId);
    }, "Agent created");
  }

  async function onToggleSelected() {
    if (!selectedAgentId) return;
    const agent = agentById[selectedAgentId];
    if (!agent) return;
    await withBusy(async () => {
      if (agent.enabled) await api.disableAgent(selectedAgentId);
      else await api.enableAgent(selectedAgentId);
    }, agent.enabled ? "Agent disabled" : "Agent enabled");
  }

  const selectedCaps = useMemo(() => {
    const agent = agentById[selectedAgentId];
    if (!agent) return [] as Array<{ id: string; title: string; desc: string }>;
    if (agent.capabilities.length === 0 && capabilities.length > 0) {
      return capabilities.slice(0, 12).map((c, index) => {
        const id = typeof c.id === "string" && c.id ? c.id : `cap-${index}`;
        const title = typeof c.name === "string" && c.name ? c.name : id;
        const desc =
          typeof c.description === "string" && c.description
            ? c.description
            : "Registered capability";
        return { id, title, desc };
      });
    }
    return agent.capabilities.map((id) => ({
      id,
      title: id,
      desc: "Assigned on agent definition — executed via ExecutionGateway",
    }));
  }, [agentById, selectedAgentId, capabilities]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Agents Mode"
      searchPlaceholder="Search agents, tasks, workflows, or ask Leviathan..."
      systemItems={[
        summary?.agentsEnabled ? "AGENTS ENABLED" : "AGENTS FEATURE OFF",
        `${summary?.agentCount ?? agents.length} AGENTS`,
        `${summary?.activeMissions ?? 0} ACTIVE`,
      ]}
      layout="wide"
      pageClass="lv-app--agents"
    >
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

        {loadError ? (
          <div className="lv-ag-panel" style={{ marginBottom: 12 }}>
            <p>{loadError}</p>
            <button type="button" className="lv-ag-btn-gold" onClick={() => void loadAll()}>
              Retry
            </button>
          </div>
        ) : null}

        <div className="lv-ag-grid-top">
          <section className="lv-ag-panel">
            <SectionTitle n={1} title="AGENT ROSTER / DIRECTORY" />
            <div className="lv-ag-roster-tools">
              <input type="search" placeholder="Search agents..." value={query} onChange={(e) => setQuery(e.target.value)} />
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option>All Roles</option>
                <option>Analysis</option>
                <option>Implementation</option>
                <option>Decomposition</option>
              </select>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option>All Status</option>
                <option>Online</option>
                <option>Busy</option>
                <option>Idle</option>
                <option>Offline</option>
              </select>
              <input
                type="text"
                placeholder="New agent name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
              />
              <select value={createKind} onChange={(e) => setCreateKind(e.target.value)}>
                <option value="research">research</option>
                <option value="coding">coding</option>
                <option value="generic">generic</option>
                <option value="specialist">specialist</option>
                <option value="orchestrator">orchestrator</option>
              </select>
              <button type="button" className="lv-ag-btn-teal" disabled={busy} onClick={() => void onCreateAgent()}>
                Create
              </button>
            </div>
            <div className="lv-ag-roster-grid">
              {roster.length === 0 ? (
                <p className="lv-ag-empty">No agents match filters.</p>
              ) : (
                roster.map((agent) => {
                  const label = healthLabel(agent);
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
                    >
                      <div className="lv-ag-agent-head">
                        <span className="lv-ag-agent-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24"><AgentIcon kind={agentIconKind(agent)} /></svg>
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
                      <div className="lv-ag-agent-model">{agent.modelRef || "model: inherit"}</div>
                      <div className="lv-ag-tags">
                        <span>{agent.kind}</span>
                        <span>v{agent.version}</span>
                        {agent.tags.slice(0, 3).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
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
                      <th>Role</th>
                      <th>Active</th>
                      <th>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.filter((a) => !a.archived).map((agent) => {
                      const label = healthLabel(agent);
                      const active = missions.filter(
                        (m) => m.agentId === agent.agentId && isActiveJobStatus(m.status),
                      ).length;
                      return (
                        <tr key={agent.agentId}>
                          <td>
                            <span className="lv-ag-table-agent">
                              <span className="lv-ag-agent-icon is-sm" aria-hidden="true">
                                <svg viewBox="0 0 24 24"><AgentIcon kind={agentIconKind(agent)} /></svg>
                              </span>
                              {agent.name}
                            </span>
                          </td>
                          <td>
                            <span className={`lv-ag-status is-${statusTone(label)}`}>
                              <i />
                              {label}
                            </span>
                          </td>
                          <td>{agent.modelRef || "—"}</td>
                          <td>{agent.kind}</td>
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
              <SectionTitle n={3} title="ORCHESTRATOR / CONTROL" />
              <div className="lv-ag-orch-actions">
                <button type="button" className="lv-ag-btn-gold" disabled={busy} onClick={() => void onLaunch()}>
                  Launch Agent
                </button>
                <button type="button" className="lv-ag-btn-stop" disabled={busy} onClick={() => void onStopSelected()}>
                  Stop Agent
                </button>
                <button type="button" className="lv-ag-btn-teal" disabled={busy} onClick={() => void onToggleSelected()}>
                  Enable / Disable
                </button>
              </div>
              <div className="lv-ag-orch-fields">
                <label>
                  <span>Select Agent</span>
                  <select value={selectedAgentId} onChange={(e) => setSelectedAgentId(e.target.value)}>
                    {agents.filter((a) => !a.archived).map((a) => (
                      <option key={a.agentId} value={a.agentId}>
                        {a.name} ({a.kind})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Task request</span>
                  <input type="text" value={taskRequest} onChange={(e) => setTaskRequest(e.target.value)} />
                </label>
                <div className="lv-ag-priority">
                  <span>Task Priority</span>
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
                    <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
                  </span>
                </label>
              </div>
              <button type="button" className="lv-ag-btn-gold is-wide" disabled={busy} onClick={() => void onLaunch()}>
                Deploy Task
              </button>
              {selectedAgentId && agentById[selectedAgentId]?.healthReason ? (
                <p className="lv-ag-empty">{agentById[selectedAgentId]?.healthReason}</p>
              ) : null}
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
                disabled={busy}
                onClick={() => {
                  setMissionTab("All Tasks");
                  void onLaunch();
                }}
              >
                + New Task
              </button>
            </div>
            <div className="lv-ag-tabs">
              {MISSION_TABS.map((tab) => {
                const count =
                  tab === "All Tasks"
                    ? missions.length
                    : tab === "Completed"
                      ? missions.filter((m) => m.status === "completed").length
                      : tab === "Running"
                        ? missions.filter((m) => isActiveJobStatus(m.status) && m.status !== "queued").length
                        : missions.filter((m) => m.status === "queued").length;
                return (
                  <button
                    key={tab}
                    type="button"
                    className={missionTab === tab ? "is-active" : ""}
                    onClick={() => setMissionTab(tab)}
                  >
                    {tab} ({count})
                  </button>
                );
              })}
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
                        <tr key={m.missionId}>
                          <td title={m.missionId}>{m.missionId.slice(0, 12)}</td>
                          <td>{m.title}</td>
                          <td>{agent?.name ?? m.agentId.slice(0, 8)}</td>
                          <td>
                            <span className={`lv-ag-pill is-${isActiveJobStatus(m.status) ? "cyan" : "muted"}`}>
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
                                onClick={() =>
                                  void withBusy(async () => {
                                    await api.cancelAgentMission(m.missionId);
                                  }, "Cancelled")
                                }
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
          </section>

          <section className="lv-ag-panel">
            <SectionTitle n={5} title="COMMUNICATION / COORDINATION" />
            <div className="lv-ag-tabs">
              {["Agent Network", "Delegation Chain", "Message Log"].map((tab) => (
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
                <AgentNetwork agents={agents.filter((a) => !a.archived)} edges={networkEdges} />
                <div className="lv-ag-net-legend">
                  <span>
                    <i className="is-active" /> Active Link
                  </span>
                  <span>
                    <i className="is-idle" /> Idle Link
                  </span>
                </div>
              </>
            ) : null}
            {commTab === "Delegation Chain" ? (
              <ul className="lv-ag-logs">
                {missions
                  .filter((m) => m.parentMissionId)
                  .slice(0, 20)
                  .map((m) => (
                    <li key={m.missionId}>
                      <time>{m.createdAt.slice(11, 19)}</time>
                      <span className="lv-ag-log-src">[{agentById[m.agentId]?.name ?? m.agentId.slice(0, 8)}]</span>
                      <span className="lv-ag-log-text">
                        child of {m.parentMissionId?.slice(0, 12)} · {m.status}
                      </span>
                    </li>
                  ))}
                {missions.every((m) => !m.parentMissionId) ? (
                  <li className="lv-ag-empty">No delegation chains yet — launch an orchestrator mission.</li>
                ) : null}
              </ul>
            ) : null}
            {commTab === "Message Log" ? (
              <ul className="lv-ag-logs">
                {events.slice(0, 20).map((e) => (
                  <li key={e.eventId}>
                    <time>{e.createdAt.slice(11, 19)}</time>
                    <span className="lv-ag-log-src">[{e.category}]</span>
                    <span className="lv-ag-log-text">{e.message}</span>
                  </li>
                ))}
              </ul>
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
                onClick={() => setCapTab("Capabilities")}
              >
                Refresh view
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
              {capTab === "Capabilities" || capTab === "Tools & Integrations" ? (
                selectedCaps.length === 0 ? (
                  <p className="lv-ag-empty">No capabilities assigned to selected agent.</p>
                ) : (
                  selectedCaps.map((cap) => (
                    <div key={cap.id} className="lv-ag-cap-card">
                      <span className="lv-ag-agent-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><CapIcon kind="search" /></svg>
                      </span>
                      <strong>{cap.title}</strong>
                      <small>{cap.desc}</small>
                    </div>
                  ))
                )
              ) : (
                <p className="lv-ag-empty">
                  {capTab} linkage uses dataset/knowledge policy fields on the agent definition
                  ({agentById[selectedAgentId]?.datasetAccess ?? "none"} /{" "}
                  {agentById[selectedAgentId]?.memoryPolicy ?? "default"}).
                </p>
              )}
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  );
}
