import { useState } from "react";
import {
  Panel,
  ProgressBar,
  StatusDot,
} from "../components/media/MediaWidgets";
import { mediaControlCrops } from "../assets/mediaControlAssets";
import { MediaPlatformShell } from "../layouts/MediaPlatformShell";
import { useAppToast } from "../state/useAppToast";

const ROSTER = [
  { name: "Research", status: "Online", model: "gpt-4.1", tags: "research · web · analysis", tone: "green" as const },
  { name: "Coding", status: "Busy", model: "claude-3.7", tags: "code · refactor · tests", tone: "gold" as const },
  { name: "Trading", status: "Online", model: "qwen3-14b", tags: "markets · risk · exec", tone: "green" as const },
  { name: "Memory", status: "Online", model: "hermes-3", tags: "recall · index · sync", tone: "green" as const },
  { name: "Media", status: "Idle", model: "gpt-4.1", tags: "clips · captions · publish", tone: "gold" as const },
  { name: "Critic", status: "Online", model: "claude-3.7", tags: "review · QA · score", tone: "green" as const },
  { name: "Planner", status: "Busy", model: "o3-mini", tags: "goals · decompose · route", tone: "gold" as const },
  { name: "Execution", status: "Offline", model: "local-8b", tags: "tools · shell · deploy", tone: "red" as const },
];

const STATUS = [
  { agent: "Research", status: "Online", model: "gpt-4.1", role: "Discovery", tasks: "3 | 1", last: "2m" },
  { agent: "Coding", status: "Busy", model: "claude-3.7", role: "Implementation", tasks: "2 | 0", last: "1m" },
  { agent: "Trading", status: "Online", model: "qwen3-14b", role: "Market Ops", tasks: "1 | 2", last: "5m" },
  { agent: "Memory", status: "Online", model: "hermes-3", role: "Context", tasks: "0 | 0", last: "8m" },
  { agent: "Planner", status: "Busy", model: "o3-mini", role: "Orchestration", tasks: "4 | 1", last: "30s" },
];

const TASKS = [
  { id: "T-4821", desc: "Synthesize market regime brief", agent: "Research", status: "Running", priority: "High", progress: 68, eta: "6m" },
  { id: "T-4820", desc: "Refactor media scheduler module", agent: "Coding", status: "Running", priority: "High", progress: 42, eta: "18m" },
  { id: "T-4819", desc: "Rebalance overnight exposure", agent: "Trading", status: "Queued", priority: "Med", progress: 0, eta: "—", },
  { id: "T-4818", desc: "Index new knowledge batch", agent: "Memory", status: "Running", priority: "Med", progress: 81, eta: "3m" },
  { id: "T-4817", desc: "Critique campaign copy pack", agent: "Critic", status: "Queued", priority: "Low", progress: 0, eta: "—" },
  { id: "T-4816", desc: "Plan multi-agent media sprint", agent: "Planner", status: "Running", priority: "High", progress: 55, eta: "9m" },
];

const LOGS = [
  { t: "14:37:26", text: "Planner decomposed mission T-4821 into 4 steps", kind: "Agents" },
  { t: "14:36:58", text: "Coding agent acquired write lock on scheduler", kind: "Tasks" },
  { t: "14:36:12", text: "Memory sync completed (+128 embeddings)", kind: "System" },
  { t: "14:35:40", text: "Trading agent paused pending risk approval", kind: "Warnings" },
  { t: "14:34:09", text: "Tool Web Search executed (142ms)", kind: "Tasks" },
];

const TOOLS = [
  ["Web Search", "Real-time internet access"],
  ["Browser Automation", "Interact with web apps"],
  ["APIs & Integrations", "Connect external services"],
  ["Code Execution", "Run code & notebooks"],
  ["Image & Video Gen", "Create and edit media"],
  ["Market Data", "Real-time & historical"],
  ["File System", "Read, write, manage files"],
  ["Memory Access", "Store & retrieve context"],
  ["Document Analysis", "PDF, DOCX, CSV"],
  ["Reasoning & Planning", "Multi-step execution"],
  ["Communication", "Agent-to-agent messaging"],
  ["Deploy Hooks", "Ship approved changes"],
];

const NODES = [
  { id: "orch", label: "Orchestrator", x: 160, y: 90 },
  { id: "research", label: "Research", x: 40, y: 30 },
  { id: "trading", label: "Trading", x: 280, y: 30 },
  { id: "memory", label: "Memory", x: 40, y: 150 },
  { id: "coding", label: "Coding", x: 280, y: 150 },
  { id: "critic", label: "Critic", x: 100, y: 190 },
  { id: "planner", label: "Planner", x: 220, y: 190 },
];

export function AgentsPage() {
  const toast = useAppToast();
  const [autonomy, setAutonomy] = useState(70);
  const [workers, setWorkers] = useState(3);
  const [taskTab, setTaskTab] = useState("All Tasks (12)");

  return (
    <MediaPlatformShell
      activePlatform="agents"
      searchPlaceholder="Search agents, tasks, tools..."
      createAccent="gold"
      sidebarPoster={mediaControlCrops.agentsSidebarPoster}
      sidebarCaption="Discipline creates freedom."
      promo={{ image: mediaControlCrops.agentsPoster, caption: "A multiplicity of minds. A singular purpose." }}
      statusItems={[
        { label: "Fleet Status", value: "Online" },
        { label: "Memory", value: "Synced" },
        { label: "Tools", value: "Ready" },
        { label: "Alerts", value: "None" },
      ]}
    >
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.agentsHeroWide} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">Agents</h1>
              <div className="mp-hero-flow">Orchestrate. Delegate. Execute.</div>
              <div className="mp-list-meta" style={{ marginTop: 8 }}>
                “A multiplicity of minds. A singular purpose.” — LEVIATHAN
              </div>
            </div>
            <div className="mp-hero-quotes">
              <span>Higher intelligence</span>
              <span>Greater leverage</span>
              <span>A brighter tomorrow</span>
            </div>
          </div>
        </section>

        <div className="mp-grid-3" style={{ gridTemplateColumns: "1.3fr 1fr 1fr" }}>
          <Panel title="1 · Agent Roster / Directory">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 8 }}>
              {ROSTER.map((a) => (
                <button
                  key={a.name}
                  type="button"
                  className="mp-tool-tile"
                  onClick={() => toast(`${a.name} agent`)}
                  style={{ minHeight: 96 }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                    <strong>{a.name}</strong>
                    <StatusDot tone={a.tone === "red" ? "red" : a.tone === "gold" ? "gold" : "green"} />
                  </div>
                  <span className="mp-list-meta">{a.status}</span>
                  <span className="mp-list-meta">{a.model}</span>
                  <span className="mp-list-meta">{a.tags}</span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="2 · Agent Status">
            <table className="mp-table">
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
                {STATUS.map((s) => (
                  <tr key={s.agent}>
                    <td>{s.agent}</td>
                    <td>
                      <span className="mp-badge is-green">
                        <StatusDot tone={s.status === "Busy" ? "gold" : "green"} /> {s.status}
                      </span>
                    </td>
                    <td>{s.model}</td>
                    <td>{s.role}</td>
                    <td>{s.tasks}</td>
                    <td>{s.last}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="3 · Orchestrator / Control">
            <div className="mp-stack">
              <div style={{ display: "flex", gap: 8 }}>
                <button className="mp-btn mp-btn-solid" type="button" onClick={() => toast("Launch Agent")} style={{ background: "var(--mp-gold-bright)", color: "#111" }}>
                  Launch Agent
                </button>
                <button className="mp-btn" type="button" onClick={() => toast("Stop Agent")}>
                  Stop Agent
                </button>
              </div>
              {[
                ["Select Agent", "Coding Agent"],
                ["Assign Role", "Custom (specify)"],
                ["Task Priority", "High"],
                ["Approval Mode", "Auto (Low Risk)"],
              ].map(([label, value]) => (
                <label key={label} className="mp-stack" style={{ gap: 4 }}>
                  <span className="mp-list-meta">{label}</span>
                  <select className="mp-select" defaultValue={value}>
                    <option>{value}</option>
                  </select>
                </label>
              ))}
              <label className="mp-stack" style={{ gap: 4 }}>
                <span className="mp-list-meta">Autonomy Level · {autonomy}%</span>
                <input type="range" min={0} max={100} value={autonomy} onChange={(e) => setAutonomy(Number(e.target.value))} />
              </label>
              <label className="mp-stack" style={{ gap: 4 }}>
                <span className="mp-list-meta">Max Workers · {workers}</span>
                <input type="range" min={1} max={16} value={workers} onChange={(e) => setWorkers(Number(e.target.value))} />
              </label>
              <div className="mp-chip-row">
                {["Access Tools", "Web Access", "Use Memory", "Write Disk"].map((c) => (
                  <label key={c} className="mp-list-meta" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                    <input type="checkbox" defaultChecked={c !== "Write Disk"} /> {c}
                  </label>
                ))}
              </div>
              <button className="mp-btn mp-btn-solid" type="button" onClick={() => toast("Deploy Task")} style={{ justifyContent: "center" }}>
                Deploy Task
              </button>
            </div>
          </Panel>
        </div>

        <div className="mp-grid-3">
          <Panel
            title="4 · Active Missions / Tasks"
            action={
              <div className="mp-tabs">
                {["All Tasks (12)", "Running (4)", "Queued (6)", "Completed (128)"].map((t) => (
                  <button key={t} type="button" className={`mp-tab${taskTab === t ? " is-active" : ""}`} onClick={() => setTaskTab(t)}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <table className="mp-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Task</th>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Progress</th>
                  <th>ETA</th>
                </tr>
              </thead>
              <tbody>
                {TASKS.map((t) => (
                  <tr key={t.id}>
                    <td style={{ color: "var(--mp-cyan, #22c9d6)" }}>{t.id}</td>
                    <td>{t.desc}</td>
                    <td>{t.agent}</td>
                    <td>
                      <span className={`mp-badge ${t.status === "Running" ? "is-green" : "is-muted"}`}>{t.status}</span>
                    </td>
                    <td>
                      <span className={`mp-badge ${t.priority === "High" ? "is-red" : t.priority === "Med" ? "is-gold" : "is-muted"}`}>{t.priority}</span>
                    </td>
                    <td style={{ minWidth: 100 }}>
                      <ProgressBar value={t.progress} tone="teal" showValue />
                    </td>
                    <td>{t.eta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="5 · Communication / Agent Network">
            <svg viewBox="0 0 320 220" style={{ width: "100%", height: "auto" }} role="img" aria-label="Agent network">
              {NODES.filter((n) => n.id !== "orch").map((n) => {
                const orch = NODES[0];
                return (
                  <line
                    key={`e-${n.id}`}
                    x1={orch.x}
                    y1={orch.y}
                    x2={n.x}
                    y2={n.y}
                    stroke="rgba(214,169,87,0.45)"
                    strokeWidth="1.5"
                  />
                );
              })}
              {NODES.map((n) => (
                <g key={n.id}>
                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={n.id === "orch" ? 22 : 16}
                    fill={n.id === "orch" ? "rgba(214,169,87,0.25)" : "rgba(34,201,214,0.15)"}
                    stroke={n.id === "orch" ? "#d6a957" : "#22c9d6"}
                    strokeWidth="1.5"
                  />
                  <text x={n.x} y={n.y + (n.id === "orch" ? 36 : 30)} textAnchor="middle" fill="#e8e4dc" fontSize="9">
                    {n.label}
                  </text>
                </g>
              ))}
            </svg>
          </Panel>

          <Panel title="6 · Resources / System Usage">
            <div className="mp-stack">
              <ProgressBar label="Total Token Usage · 1.2M / 5.0M" value={24} tone="teal" />
              <ProgressBar label="Memory Usage · 18.4 / 64 GB" value={29} tone="gold" />
              <ProgressBar label="Active Workers · 7 / 16" value={44} tone="green" />
              <ProgressBar label="Context Budget · 210K / 1.0M" value={21} tone="teal" />
              <ProgressBar label="CPU Usage" value={32} tone="gold" />
              <ProgressBar label="GPU Usage" value={41} tone="teal" />
              <div className="mp-badge is-green" style={{ width: "fit-content" }}>
                Average Latency · Good
              </div>
            </div>
          </Panel>
        </div>

        <div className="mp-grid-2">
          <Panel
            title="7 · Logs / Event Timeline"
            action={
              <div className="mp-tabs">
                {["All", "System", "Agents", "Tasks", "Warnings", "Errors"].map((t, i) => (
                  <button key={t} type="button" className={`mp-tab${i === 0 ? " is-active" : ""}`}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-list">
              {LOGS.map((l) => (
                <div key={l.t + l.text} className="mp-list-row">
                  <span className="mp-list-meta" style={{ width: 64 }}>
                    {l.t}
                  </span>
                  <span className="mp-badge is-muted">{l.kind}</span>
                  <span className="mp-list-title">{l.text}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="8 · Knowledge / Skills / Tool Access"
            action={
              <button className="mp-btn" type="button" onClick={() => toast("Manage Tools")}>
                Manage Tools
              </button>
            }
          >
            <div className="mp-tabs" style={{ marginBottom: 8 }}>
              {["Capabilities", "Tools & Integrations", "Datasets", "Knowledge Sources"].map((t, i) => (
                <button key={t} type="button" className={`mp-tab${i === 0 ? " is-active" : ""}`}>
                  {t}
                </button>
              ))}
            </div>
            <div className="mp-tool-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
              {TOOLS.map(([name, desc]) => (
                <button key={name} type="button" className="mp-tool-tile" onClick={() => toast(name)}>
                  <strong>{name}</strong>
                  <span className="mp-list-meta">{desc}</span>
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </MediaPlatformShell>
  );
}
