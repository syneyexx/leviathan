import { useMemo, useState } from "react";
import { mediaControlCrops } from "../assets/mediaControlAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type AgentStatus = "Online" | "Busy" | "Idle" | "Offline";

const AGENTS = [
  { name: "Research", role: "Information & Analysis", status: "Online" as AgentStatus, model: "gpt-4.1", tags: ["research", "web", "analysis"], tasks: "5 | 2", last: "1m ago", icon: "research" },
  { name: "Coding", role: "Implementation & Verify", status: "Busy" as AgentStatus, model: "claude-3.7", tags: ["code", "tests", "refactor"], tasks: "3 | 1", last: "just now", icon: "coding" },
  { name: "Trading", role: "Markets & Execution", status: "Online" as AgentStatus, model: "gpt-4.1", tags: ["markets", "risk", "orders"], tasks: "2 | 0", last: "4m ago", icon: "trading" },
  { name: "Memory", role: "Context & Recall", status: "Online" as AgentStatus, model: "qwen3-14b", tags: ["memory", "index", "recall"], tasks: "1 | 0", last: "8m ago", icon: "memory" },
  { name: "Media", role: "Create & Publish", status: "Idle" as AgentStatus, model: "gpt-4.1", tags: ["video", "caption", "schedule"], tasks: "0 | 0", last: "22m ago", icon: "media" },
  { name: "Critic", role: "Review & Guardrails", status: "Online" as AgentStatus, model: "claude-3.7", tags: ["review", "qa", "policy"], tasks: "2 | 1", last: "3m ago", icon: "critic" },
  { name: "Planner", role: "Goals & Decomposition", status: "Busy" as AgentStatus, model: "o3-mini", tags: ["plan", "delegate", "roadmap"], tasks: "4 | 2", last: "2m ago", icon: "planner" },
  { name: "Execution", role: "Tools & Runtime", status: "Offline" as AgentStatus, model: "hermes-3", tags: ["tools", "runtime", "shell"], tasks: "0 | 0", last: "2h ago", icon: "execution" },
] as const;

const MISSION_TABS = ["All Tasks", "Running", "Queued", "Completed"] as const;

const MISSIONS = [
  { id: 2401, task: "Deep research · rate-cut odds", agent: "Research", status: "Running", priority: "High", progress: 68, eta: "6m" },
  { id: 2402, task: "Implement feature from spec", agent: "Coding", status: "Running", priority: "High", progress: 42, eta: "18m" },
  { id: 2403, task: "Rebalance paper portfolio", agent: "Trading", status: "Queued", priority: "Med", progress: 10, eta: "25m" },
  { id: 2404, task: "Critique media campaign draft", agent: "Critic", status: "Running", priority: "Med", progress: 55, eta: "9m" },
  { id: 2405, task: "Plan Q2 agent fleet roadmap", agent: "Planner", status: "Queued", priority: "Low", progress: 8, eta: "40m" },
  { id: 2406, task: "Index new knowledge pack", agent: "Memory", status: "Running", priority: "Med", progress: 81, eta: "3m" },
  { id: 2407, task: "Schedule weekly recap reel", agent: "Media", status: "Queued", priority: "Low", progress: 5, eta: "1h" },
  { id: 2408, task: "Verify tool sandbox health", agent: "Execution", status: "Queued", priority: "High", progress: 0, eta: "—" },
] as const;

const RESOURCES = [
  { label: "Total Token Usage", detail: "1.2M / 5.0M", pct: 24 },
  { label: "Memory Usage", detail: "18.4 GB / 64 GB", pct: 29 },
  { label: "Active Workers", detail: "7 / 16", pct: 44 },
  { label: "Average Latency", detail: "Good", pct: 72 },
  { label: "Context Budget", detail: "210K / 1.0M", pct: 21 },
  { label: "CPU Usage", detail: "32%", pct: 32 },
  { label: "GPU Usage", detail: "68%", pct: 68 },
] as const;

const LOG_FILTERS = ["All", "System", "Agents", "Tasks", "Warnings", "Errors"] as const;

const LOGS = [
  { time: "14:37:21", source: "Coding", text: "Completed web search · 14 sources", dur: "2.3s", kind: "Agents" },
  { time: "14:36:58", source: "System", text: "Worker pool scaled · +2 slots", dur: "0.4s", kind: "System" },
  { time: "14:36:12", source: "Research", text: "Delegated synthesis to Critic", dur: "1.1s", kind: "Tasks" },
  { time: "14:35:40", source: "Planner", text: "Mission graph updated · 4 nodes", dur: "0.8s", kind: "Tasks" },
  { time: "14:34:55", source: "Trading", text: "Risk check passed · exposure 18%", dur: "0.6s", kind: "Agents" },
  { time: "14:33:18", source: "Memory", text: "Warning · context pressure rising", dur: "—", kind: "Warnings" },
  { time: "14:31:02", source: "Execution", text: "Error · sandbox offline", dur: "—", kind: "Errors" },
  { time: "14:29:44", source: "Critic", text: "Approved media caption batch", dur: "3.2s", kind: "Agents" },
] as const;

const CAPABILITY_TABS = ["Capabilities", "Tools & Integrations", "Datasets", "Knowledge Sources"] as const;

const CAPABILITIES = [
  { title: "Web Search", desc: "Live retrieval across the open web.", icon: "search" },
  { title: "Code Execution", desc: "Sandboxed runtimes for verify loops.", icon: "code" },
  { title: "Browser Automation", desc: "Navigate and extract from UIs.", icon: "globe" },
  { title: "Image & Video Gen", desc: "Cinematic media synthesis.", icon: "image" },
  { title: "APIs", desc: "Authenticated external connectors.", icon: "api" },
  { title: "Market Data", desc: "Quotes, books, and regime feeds.", icon: "chart" },
  { title: "File System", desc: "Workspace read/write with policy.", icon: "folder" },
  { title: "Datasets", desc: "Curated training and eval packs.", icon: "data" },
  { title: "Memory Access", desc: "Long-term recall and indexing.", icon: "memory" },
  { title: "Reasoning & Planning", desc: "Multi-step goal decomposition.", icon: "brain" },
  { title: "Document Analysis", desc: "Parse PDFs, sheets, and specs.", icon: "doc" },
  { title: "Communication", desc: "Inter-agent message bus.", icon: "chat" },
] as const;

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
    case "globe":
      return (<><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16" /></>);
    case "image":
      return (<><rect x="4" y="6" width="16" height="12" rx="2" /><path d="M8 14l3-3 2.5 2.5L16 11l2 2" /></>);
    case "api":
      return <path d="M8 8h8v8H8zM12 4v4M12 16v4M4 12h4M16 12h4" />;
    case "chart":
      return <path d="M5 19V10M12 19V6M19 19v-5" />;
    case "folder":
      return (<><path d="M4 9h16v9H4z" /><path d="M4 9l1.6-2.8h5L12 9" /></>);
    case "data":
      return (<><ellipse cx="12" cy="7" rx="6" ry="2.5" /><path d="M6 7v5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V7M6 12v5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5" /></>);
    case "memory":
      return (<><ellipse cx="12" cy="8" rx="6" ry="3" /><path d="M6 8v6c0 1.7 2.7 3 6 3s6-1.3 6-3V8" /></>);
    case "brain":
      return <path d="M9 8a3 3 0 015 0 3 3 0 012.5 2.8A3 3 0 0115 16H9a3 3 0 01-1.5-5.2A3 3 0 019 8z" />;
    case "doc":
      return <path d="M7 4h7l3 3v13H7zM14 4v3h3M9 11h6M9 15h5" />;
    default:
      return <path d="M5 7h14v8H9l-4 3V7z" />;
  }
}

function statusTone(status: AgentStatus) {
  if (status === "Online") return "ok";
  if (status === "Busy") return "warn";
  if (status === "Idle") return "cyan";
  return "off";
}

function SectionTitle({ n, title }: { n: number; title: string }) {
  return (
    <header className="lv-ag-section-head">
      <span className="lv-ag-section-num">{n}.</span>
      <h2>{title}</h2>
    </header>
  );
}

function AgentNetwork() {
  const nodes: Array<{ id: string; label: string; x: number; y: number; hub?: boolean }> = [
    { id: "orch", label: "Orchestrator", x: 200, y: 110, hub: true },
    { id: "research", label: "Research", x: 70, y: 40 },
    { id: "planner", label: "Planner", x: 200, y: 28 },
    { id: "critic", label: "Critic", x: 330, y: 40 },
    { id: "coding", label: "Coding", x: 60, y: 170 },
    { id: "memory", label: "Memory", x: 200, y: 200 },
    { id: "trading", label: "Trading", x: 340, y: 170 },
  ];

  const links: Array<[string, string, "active" | "idle"]> = [
    ["orch", "research", "active"],
    ["orch", "planner", "active"],
    ["orch", "critic", "active"],
    ["orch", "coding", "active"],
    ["orch", "memory", "idle"],
    ["orch", "trading", "idle"],
    ["planner", "critic", "active"],
    ["research", "memory", "idle"],
  ];

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));

  return (
    <svg className="lv-ag-network" viewBox="0 0 400 230" role="img" aria-label="Agent network">
      {links.map(([a, b, tone]) => {
        const from = byId[a];
        const to = byId[b];
        return (
          <line key={`${a}-${b}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={`lv-ag-link is-${tone}`} />
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
  const [roleFilter, setRoleFilter] = useState("All Roles");
  const [statusFilter, setStatusFilter] = useState("All Status");
  const [missionTab, setMissionTab] = useState<(typeof MISSION_TABS)[number]>("All Tasks");
  const [commTab, setCommTab] = useState("Agent Network");
  const [logFilter, setLogFilter] = useState<(typeof LOG_FILTERS)[number]>("All");
  const [capTab, setCapTab] = useState<(typeof CAPABILITY_TABS)[number]>("Capabilities");
  const [autonomy, setAutonomy] = useState(70);
  const [maxWorkers, setMaxWorkers] = useState(3);
  const [priority, setPriority] = useState<"Low" | "Med" | "High">("High");
  const [checks, setChecks] = useState({ tools: true, memory: true, web: true, multi: false });
  const [query, setQuery] = useState("");

  const roster = useMemo(() => {
    return AGENTS.filter((agent) => {
      if (query && !agent.name.toLowerCase().includes(query.toLowerCase())) return false;
      if (statusFilter !== "All Status" && agent.status !== statusFilter) return false;
      if (roleFilter !== "All Roles" && !agent.role.toLowerCase().includes(roleFilter.toLowerCase())) return false;
      return true;
    });
  }, [query, roleFilter, statusFilter]);

  const missions = useMemo(() => {
    if (missionTab === "All Tasks") return MISSIONS;
    if (missionTab === "Completed") return [];
    const key = missionTab === "Running" ? "Running" : "Queued";
    return MISSIONS.filter((m) => m.status === key);
  }, [missionTab]);

  const logs = useMemo(() => {
    if (logFilter === "All") return LOGS;
    return LOGS.filter((l) => l.kind === logFilter);
  }, [logFilter]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Agents Mode"
      searchPlaceholder="Search agents, tasks, workflows, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
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
        <div className="lv-ag-grid-top">
          <section className="lv-ag-panel">
            <SectionTitle n={1} title="AGENT ROSTER / DIRECTORY" />
            <div className="lv-ag-roster-tools">
              <input type="search" placeholder="Search agents..." value={query} onChange={(e) => setQuery(e.target.value)} />
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option>All Roles</option>
                <option>Analysis</option>
                <option>Implementation</option>
                <option>Markets</option>
              </select>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option>All Status</option>
                <option>Online</option>
                <option>Busy</option>
                <option>Idle</option>
                <option>Offline</option>
              </select>
              <select defaultValue="Sort: Name" onChange={() => toast("Sort")}>
                <option>Sort: Name</option>
                <option>Sort: Status</option>
                <option>Sort: Activity</option>
              </select>
            </div>
            <div className="lv-ag-roster-grid">
              {roster.map((agent) => (
                <article key={agent.name} className="lv-ag-agent-card">
                  <div className="lv-ag-agent-head">
                    <span className="lv-ag-agent-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24"><AgentIcon kind={agent.icon} /></svg>
                    </span>
                    <div>
                      <strong>{agent.name}</strong>
                      <small>{agent.role}</small>
                    </div>
                    <span className={`lv-ag-status is-${statusTone(agent.status)}`}>
                      <i />
                      {agent.status}
                    </span>
                  </div>
                  <div className="lv-ag-agent-model">{agent.model}</div>
                  <div className="lv-ag-tags">
                    {agent.tags.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                </article>
              ))}
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
                      <th>Tasks</th>
                      <th>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {AGENTS.map((agent) => (
                      <tr key={agent.name}>
                        <td>
                          <span className="lv-ag-table-agent">
                            <span className="lv-ag-agent-icon is-sm" aria-hidden="true">
                              <svg viewBox="0 0 24 24"><AgentIcon kind={agent.icon} /></svg>
                            </span>
                            {agent.name}
                          </span>
                        </td>
                        <td>
                          <span className={`lv-ag-status is-${statusTone(agent.status)}`}>
                            <i />
                            {agent.status}
                          </span>
                        </td>
                        <td>{agent.model}</td>
                        <td>{agent.role.split(" ")[0]}</td>
                        <td>{agent.tasks}</td>
                        <td>{agent.last}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="lv-ag-panel lv-ag-orchestrator">
              <SectionTitle n={3} title="ORCHESTRATOR / CONTROL" />
              <div className="lv-ag-orch-actions">
                <button type="button" className="lv-ag-btn-gold" onClick={() => toast("Launch Agent")}>
                  Launch Agent
                </button>
                <button type="button" className="lv-ag-btn-stop" onClick={() => toast("Stop Agent")}>
                  Stop Agent
                </button>
              </div>
              <div className="lv-ag-orch-fields">
                <label>
                  <span>Select Agent</span>
                  <select defaultValue="Coding Agent">
                    {AGENTS.map((a) => (
                      <option key={a.name}>{a.name} Agent</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Assign Role</span>
                  <input type="text" defaultValue="Implement feature from spec" />
                </label>
                <div className="lv-ag-priority">
                  <span>Task Priority</span>
                  <div>
                    {(["Low", "Med", "High"] as const).map((p) => (
                      <button key={p} type="button" className={priority === p ? "is-active" : ""} onClick={() => setPriority(p)}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
                <label>
                  <span>Approval Mode</span>
                  <select defaultValue="Auto (Low Risk)">
                    <option>Auto (Low Risk)</option>
                    <option>Manual</option>
                    <option>Hybrid</option>
                  </select>
                </label>
                <label className="lv-ag-slider">
                  <span>
                    Autonomy Level <em>{autonomy}%</em>
                  </span>
                  <input type="range" min={0} max={100} value={autonomy} onChange={(e) => setAutonomy(Number(e.target.value))} />
                </label>
                <label>
                  <span>Max Workers</span>
                  <input type="number" min={1} max={16} value={maxWorkers} onChange={(e) => setMaxWorkers(Number(e.target.value))} />
                </label>
              </div>
              <div className="lv-ag-checks">
                {(
                  [
                    ["tools", "Access Tools"],
                    ["memory", "Use Memory"],
                    ["multi", "Multi-step"],
                    ["web", "Web Access"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={checks[key]}
                      onChange={() => setChecks((prev) => ({ ...prev, [key]: !prev[key] }))}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <button type="button" className="lv-ag-btn-gold is-wide" onClick={() => toast("Deploy Task")}>
                Deploy Task
              </button>
            </section>
          </div>
        </div>

        <div className="lv-ag-grid-mid">
          <section className="lv-ag-panel">
            <div className="lv-ag-panel-bar">
              <SectionTitle n={4} title="ACTIVE MISSIONS / TASKS" />
              <button type="button" className="lv-ag-btn-teal" onClick={() => toast("New Task")}>
                + New Task
              </button>
            </div>
            <div className="lv-ag-tabs">
              {MISSION_TABS.map((tab) => {
                const count =
                  tab === "All Tasks"
                    ? MISSIONS.length
                    : tab === "Completed"
                      ? 128
                      : MISSIONS.filter((m) => m.status === (tab === "Running" ? "Running" : "Queued")).length;
                return (
                  <button key={tab} type="button" className={missionTab === tab ? "is-active" : ""} onClick={() => setMissionTab(tab)}>
                    {tab} ({count})
                  </button>
                );
              })}
            </div>
            <div className="lv-ag-table-wrap">
              <table className="lv-ag-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Task</th>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Progress</th>
                    <th>ETA</th>
                  </tr>
                </thead>
                <tbody>
                  {missions.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="lv-ag-empty">
                        No completed tasks in the live window — 128 archived.
                      </td>
                    </tr>
                  ) : (
                    missions.map((m) => (
                      <tr key={m.id}>
                        <td>#{m.id}</td>
                        <td>{m.task}</td>
                        <td>{m.agent}</td>
                        <td>
                          <span className={`lv-ag-pill is-${m.status === "Running" ? "cyan" : "muted"}`}>{m.status}</span>
                        </td>
                        <td>
                          <span className={`lv-ag-prio is-${m.priority.toLowerCase()}`}>{m.priority}</span>
                        </td>
                        <td>
                          <div className="lv-ag-prog">
                            <div className="lv-ag-prog-track">
                              <span style={{ width: `${m.progress}%` }} />
                            </div>
                            <em>{m.progress}%</em>
                          </div>
                        </td>
                        <td>{m.eta}</td>
                      </tr>
                    ))
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
                  onClick={() => {
                    setCommTab(tab);
                    if (tab !== "Agent Network") toast(tab);
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>
            {commTab === "Agent Network" ? (
              <>
                <AgentNetwork />
                <div className="lv-ag-net-legend">
                  <span>
                    <i className="is-active" /> Active Link
                  </span>
                  <span>
                    <i className="is-idle" /> Idle Link
                  </span>
                </div>
              </>
            ) : (
              <div className="lv-ag-empty-panel">{commTab} view — open for live stream.</div>
            )}
          </section>

          <section className="lv-ag-panel">
            <SectionTitle n={6} title="RESOURCES / SYSTEM USAGE" />
            <div className="lv-ag-usage">
              {RESOURCES.map((row) => (
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
              <span className="lv-ag-live">
                <i /> Live
              </span>
            </div>
            <div className="lv-ag-tabs">
              {LOG_FILTERS.map((tab) => (
                <button key={tab} type="button" className={logFilter === tab ? "is-active" : ""} onClick={() => setLogFilter(tab)}>
                  {tab}
                </button>
              ))}
            </div>
            <ul className="lv-ag-logs">
              {logs.map((log) => (
                <li key={log.time + log.text}>
                  <time>{log.time}</time>
                  <span className="lv-ag-log-src">[{log.source}]</span>
                  <span className="lv-ag-log-text">{log.text}</span>
                  <em>{log.dur}</em>
                </li>
              ))}
            </ul>
          </section>

          <section className="lv-ag-panel">
            <div className="lv-ag-panel-bar">
              <SectionTitle n={8} title="KNOWLEDGE / SKILLS / TOOL ACCESS" />
              <button type="button" className="lv-ag-btn-teal" onClick={() => toast("Manage Tools")}>
                Manage Tools
              </button>
            </div>
            <div className="lv-ag-tabs">
              {CAPABILITY_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={capTab === tab ? "is-active" : ""}
                  onClick={() => {
                    setCapTab(tab);
                    if (tab !== "Capabilities") toast(tab);
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="lv-ag-cap-grid">
              {CAPABILITIES.map((cap) => (
                <button key={cap.title} type="button" className="lv-ag-cap-card" onClick={() => toast(cap.title)}>
                  <span className="lv-ag-agent-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><CapIcon kind={cap.icon} /></svg>
                  </span>
                  <strong>{cap.title}</strong>
                  <small>{cap.desc}</small>
                </button>
              ))}
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  );
}
