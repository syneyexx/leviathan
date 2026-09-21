import { useMemo, useState } from "react";
import { media } from "../assets/media";
import { SubMenu } from "../components/SubMenu";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type NodeType = {
  id: string;
  label: string;
  count: string;
  color: string;
};

type GraphNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  r: number;
  color: string;
  type: string;
  core?: boolean;
};

const NODE_TYPES: NodeType[] = [
  { id: "concept", label: "Concept", count: "3.2K", color: "#F0C875" },
  { id: "memory", label: "Memory", count: "2.1K", color: "#22C9D6" },
  { id: "project", label: "Project", count: "184", color: "#D6A957" },
  { id: "model", label: "Model", count: "96", color: "#9B8CFF" },
  { id: "dataset", label: "Dataset", count: "412", color: "#E45959" },
  { id: "tool", label: "Tool", count: "78", color: "#DB8A34" },
  { id: "agent", label: "Agent", count: "54", color: "#4285E8" },
  { id: "code", label: "Code", count: "1.4K", color: "#20DC8C" },
];

const GRAPH_NODES: GraphNode[] = [
  { id: "hades", label: "HADES", x: 500, y: 280, r: 28, color: "#F0C875", type: "concept", core: true },
  { id: "leviathan", label: "LEVIATHAN", x: 360, y: 160, r: 16, color: "#D6A957", type: "project" },
  { id: "roadmap", label: "Roadmap", x: 280, y: 230, r: 12, color: "#D6A957", type: "project" },
  { id: "tasks", label: "Tasks", x: 320, y: 320, r: 11, color: "#D6A957", type: "project" },
  { id: "python", label: "Python", x: 620, y: 140, r: 14, color: "#4285E8", type: "code" },
  { id: "cpp", label: "C++", x: 700, y: 200, r: 12, color: "#4285E8", type: "code" },
  { id: "codegen", label: "Code Gen", x: 660, y: 280, r: 13, color: "#4285E8", type: "code" },
  { id: "apis", label: "APIs", x: 720, y: 340, r: 11, color: "#4285E8", type: "code" },
  { id: "market", label: "Market Analysis", x: 420, y: 420, r: 14, color: "#20DC8C", type: "concept" },
  { id: "risk", label: "Risk Mgmt", x: 520, y: 450, r: 12, color: "#20DC8C", type: "concept" },
  { id: "training", label: "Model Training", x: 620, y: 400, r: 14, color: "#9B8CFF", type: "model" },
  { id: "rag", label: "RAG", x: 700, y: 430, r: 12, color: "#9B8CFF", type: "model" },
  { id: "embed", label: "Embeddings", x: 760, y: 360, r: 11, color: "#9B8CFF", type: "model" },
  { id: "hf", label: "HuggingFace", x: 380, y: 360, r: 12, color: "#E45959", type: "dataset" },
  { id: "local", label: "Local Datasets", x: 300, y: 400, r: 11, color: "#E45959", type: "dataset" },
  { id: "web", label: "Web Search", x: 240, y: 300, r: 12, color: "#DB8A34", type: "tool" },
  { id: "mcp", label: "MCP", x: 220, y: 180, r: 11, color: "#DB8A34", type: "tool" },
  { id: "computer", label: "Computer Use", x: 180, y: 250, r: 12, color: "#DB8A34", type: "tool" },
];

const EDGES: [string, string][] = [
  ["hades", "leviathan"],
  ["hades", "roadmap"],
  ["hades", "tasks"],
  ["hades", "python"],
  ["hades", "cpp"],
  ["hades", "codegen"],
  ["hades", "apis"],
  ["hades", "market"],
  ["hades", "risk"],
  ["hades", "training"],
  ["hades", "rag"],
  ["hades", "embed"],
  ["hades", "hf"],
  ["hades", "local"],
  ["hades", "web"],
  ["hades", "mcp"],
  ["hades", "computer"],
  ["leviathan", "roadmap"],
  ["python", "codegen"],
  ["training", "rag"],
  ["market", "risk"],
];

const VIEWS = ["Graph", "Tree", "Timeline", "Clusters", "Analytics"] as const;

const NODE_DETAILS: Record<
  string,
  { description: string; created: string; updated: string; connections: string; relevance: number; tags: string[] }
> = {
  hades: {
    description:
      "Central intelligence nucleus connecting projects, models, datasets, tools, and memory into one dynamic knowledge network.",
    created: "2025-11-02",
    updated: "2 minutes ago",
    connections: "1,842",
    relevance: 100,
    tags: ["Core", "Concept"],
  },
};

const DEFAULT_DETAIL = {
  description: "Linked knowledge node in the Leviathan brain graph. Mock metadata for UI preview.",
  created: "2026-01-14",
  updated: "1 hour ago",
  connections: "48",
  relevance: 72,
  tags: ["Linked"],
};

export function BrainPage() {
  const toast = useAppToast();
  const [view, setView] = useState<(typeof VIEWS)[number]>("Graph");
  const [activeTypes, setActiveTypes] = useState<Set<string>>(
    () => new Set(NODE_TYPES.map((item) => item.id)),
  );
  const [selectedId, setSelectedId] = useState("hades");
  const [showLabels, setShowLabels] = useState(true);
  const [query, setQuery] = useState("");

  const visibleNodes = useMemo(() => {
    const q = query.trim().toLowerCase();
    return GRAPH_NODES.filter((node) => {
      if (!activeTypes.has(node.type) && !node.core) return false;
      if (!q) return true;
      return node.label.toLowerCase().includes(q);
    });
  }, [activeTypes, query]);

  const nodeMap = useMemo(() => new Map(GRAPH_NODES.map((node) => [node.id, node])), []);
  const selected = nodeMap.get(selectedId) ?? GRAPH_NODES[0];
  const detail = NODE_DETAILS[selected.id] ?? {
    ...DEFAULT_DETAIL,
    tags: [selected.type],
  };

  const toggleType = (id: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Brain Mode"
      searchPlaceholder="Search nodes, concepts, memories, datasets..."
      pageClass="lv-app--brain"
    >
      <main className="lv-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src={media.architectureBg} alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Dynamic Knowledge Network
              <span />
            </div>
            <h1 className="lv-hero-title">Brain</h1>
            <p className="lv-page-quote">“All knowledge is connected.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Graph</span>
            <span>Memory</span>
            <span>Reason</span>
            <span>Link</span>
          </div>
        </section>

        <SubMenu />

        <div className="lv-toolbar">
          <div className="lv-tabs" role="tablist">
            {VIEWS.map((item) => (
              <button
                key={item}
                className={`lv-tab${view === item ? " is-active" : ""}`}
                type="button"
                onClick={() => {
                  setView(item);
                  if (item !== "Graph") toast(`${item} view (mock)`);
                }}
              >
                {item === "Graph" ? <span className="lv-tab-dot" /> : null}
                {item}
              </button>
            ))}
          </div>
          <input
            className="lv-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter graph…"
            aria-label="Filter graph"
          />
          <select className="lv-select" defaultValue="all" aria-label="Domain">
            <option value="all">All Domains</option>
            <option value="projects">Projects</option>
            <option value="models">Models</option>
            <option value="tools">Tools</option>
          </select>
          <button className="lv-btn" type="button" onClick={() => toast("Zoom out")}>
            −
          </button>
          <button className="lv-btn" type="button">
            100%
          </button>
          <button className="lv-btn" type="button" onClick={() => toast("Zoom in")}>
            +
          </button>
          <button className="lv-btn-gold lv-btn" type="button" onClick={() => toast("Add Node")}>
            + Add Node
          </button>
        </div>

        <div className="lv-brain-layout">
          <aside className="lv-panel lv-brain-filters">
            <div className="lv-section-label">Filter Nodes</div>
            <input
              className="lv-input"
              style={{ width: "100%" }}
              placeholder="Search types…"
              aria-label="Search node types"
            />
            <div className="lv-filter-list">
              {NODE_TYPES.map((type) => (
                <button
                  key={type.id}
                  className={`lv-filter-item${activeTypes.has(type.id) ? " is-active" : ""}`}
                  type="button"
                  onClick={() => toggleType(type.id)}
                >
                  <span className="lv-filter-swatch" style={{ color: type.color, background: type.color }} />
                  <span>{type.label}</span>
                  <span>{type.count}</span>
                </button>
              ))}
            </div>
            <button
              className="lv-toggle"
              type="button"
              onClick={() => setShowLabels((value) => !value)}
            >
              <span className={`lv-switch${showLabels ? " is-on" : ""}`} />
              Show Labels
            </button>
            <button className="lv-toggle" type="button" onClick={() => toast("Show Clusters")}>
              <span className="lv-switch is-on" />
              Show Clusters
            </button>
            <button className="lv-toggle" type="button" onClick={() => toast("Physics Layout")}>
              <span className="lv-switch is-on" />
              Physics Layout
            </button>
          </aside>

          <div className="lv-brain-workspace">
            <div className="lv-graph-canvas" aria-label="Knowledge graph">
              <svg viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">
                {EDGES.map(([from, to]) => {
                  const a = nodeMap.get(from);
                  const b = nodeMap.get(to);
                  if (!a || !b) return null;
                  if (!visibleNodes.some((n) => n.id === from) || !visibleNodes.some((n) => n.id === to)) {
                    return null;
                  }
                  return (
                    <line
                      key={`${from}-${to}`}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke="rgba(214,169,87,0.22)"
                      strokeWidth={from === "hades" ? 1.4 : 1}
                    />
                  );
                })}
                {visibleNodes.map((node) => (
                  <g
                    key={node.id}
                    className={`lv-graph-node${selectedId === node.id ? " is-active" : ""}`}
                    onClick={() => setSelectedId(node.id)}
                  >
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={selectedId === node.id ? node.r + 3 : node.r}
                      fill={node.core ? "rgba(214,169,87,0.18)" : "rgba(8,10,9,0.85)"}
                      stroke={node.color}
                      strokeWidth={node.core ? 2.2 : 1.4}
                    />
                    {node.core ? (
                      <circle cx={node.x} cy={node.y} r={8} fill={node.color} opacity={0.9} />
                    ) : (
                      <circle cx={node.x} cy={node.y} r={3.5} fill={node.color} />
                    )}
                    {showLabels ? (
                      <text
                        className={`lv-graph-label${node.core ? " core" : ""}`}
                        x={node.x}
                        y={node.y + node.r + 16}
                        textAnchor="middle"
                      >
                        {node.label}
                      </text>
                    ) : null}
                  </g>
                ))}
              </svg>
            </div>

            <div className="lv-brain-bottom">
              <article className="lv-panel lv-card">
                <div className="lv-section-label">Selected Nodes</div>
                <p className="lv-node-desc">{selected.label} · {selected.type}</p>
              </article>
              <article className="lv-panel lv-card">
                <div className="lv-section-label">Quick Actions</div>
                <div className="lv-quick-actions">
                  {[
                    { label: "Add Node", icon: <path d="M12 5v14M5 12h14" /> },
                    { label: "Create Cluster", icon: <circle cx="12" cy="12" r="7" /> },
                    {
                      label: "Find Related",
                      icon: (
                        <>
                          <circle cx="11" cy="11" r="6" />
                          <path d="M20 20l-3-3" />
                        </>
                      ),
                    },
                    { label: "Analyze Graph", icon: <path d="M5 19V9M12 19V5M19 19v-7" /> },
                  ].map((action) => (
                    <button
                      key={action.label}
                      className="lv-quick-action"
                      type="button"
                      onClick={() => toast(action.label)}
                    >
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        {action.icon}
                      </svg>
                      {action.label}
                    </button>
                  ))}
                </div>
              </article>
              <article className="lv-panel lv-card">
                <div className="lv-section-label">Graph Statistics</div>
                <div className="lv-stat-strip">
                  <div className="lv-stat-card">
                    <strong>12.4K</strong>
                    <span>Nodes</span>
                  </div>
                  <div className="lv-stat-card">
                    <strong>28</strong>
                    <span>Clusters</span>
                  </div>
                  <div className="lv-stat-card">
                    <strong>342.8K</strong>
                    <span>Links</span>
                  </div>
                  <div className="lv-stat-card">
                    <strong>10</strong>
                    <span>Domains</span>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </div>

        <p className="lv-footer-quote">“A greater mind is a more connected mind.” — LEVIATHAN</p>
      </main>

      <aside className="lv-right">
        <article className="lv-panel lv-panel-premium lv-node-details">
          <div className="lv-node-details-head">
            <h2>Node Details</h2>
            <button className="lv-icon-btn" type="button" aria-label="Close" onClick={() => toast("Close")}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <h3 className="lv-node-title">{selected.label}</h3>
          <div className="lv-toolbar">
            {detail.tags.map((tag) => (
              <span key={tag} className="lv-tag gold">
                {tag}
              </span>
            ))}
          </div>
          <p className="lv-node-desc">{detail.description}</p>
          <div className="lv-tabs">
            <button className="lv-tab is-active" type="button">
              Overview
            </button>
            <button className="lv-tab" type="button" onClick={() => toast("Relations")}>
              Relations (184)
            </button>
            <button className="lv-tab" type="button" onClick={() => toast("Content")}>
              Content
            </button>
            <button className="lv-tab" type="button" onClick={() => toast("Metrics")}>
              Metrics
            </button>
          </div>
          <div className="lv-meta-grid">
            <div className="lv-meta-item">
              <span>Type</span>
              <strong>{selected.type}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Created</span>
              <strong>{detail.created}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Updated</span>
              <strong>{detail.updated}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Connections</span>
              <strong>{detail.connections}</strong>
            </div>
          </div>
          <div className="lv-relevance">
            <div className="lv-meta-item">
              <span>Relevance</span>
              <strong>{detail.relevance}%</strong>
            </div>
            <div className="lv-relevance-bar">
              <span style={{ width: `${detail.relevance}%` }} />
            </div>
          </div>
          <div className="lv-detail-actions">
            <button className="lv-btn" type="button" onClick={() => toast("Open in Chat")}>
              Open in Chat
            </button>
            <button className="lv-btn" type="button" onClick={() => toast("Expand Node")}>
              Expand Node
            </button>
            <button className="lv-btn" type="button" onClick={() => toast("Add Relation")}>
              Add Relation
            </button>
            <button className="lv-btn-gold lv-btn" type="button" onClick={() => toast("Edit Node")}>
              Edit Node
            </button>
          </div>
        </article>
      </aside>
    </AppShell>
  );
}
