import { useMemo, useState, type ReactNode } from "react";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type FilterType = {
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
  hub?: boolean;
  core?: boolean;
  parent?: string;
};

const FILTER_TYPES: FilterType[] = [
  { id: "all", label: "All Types", count: "12.4K", color: "#F0C875" },
  { id: "concept", label: "Concept", count: "3.2K", color: "#5B8DEF" },
  { id: "memory", label: "Memory", count: "2.1K", color: "#22C9D6" },
  { id: "document", label: "Document", count: "1.8K", color: "#3DB8A8" },
  { id: "dataset", label: "Dataset", count: "1.1K", color: "#E4599A" },
  { id: "model", label: "Model", count: "892", color: "#9B8CFF" },
  { id: "agent", label: "Agent", count: "743", color: "#2BB8A8" },
  { id: "tool", label: "Tool", count: "612", color: "#DB8A34" },
  { id: "project", label: "Project", count: "521", color: "#D6A957" },
  { id: "task", label: "Task", count: "420", color: "#E8C56A" },
  { id: "event", label: "Event", count: "318", color: "#A8C4E8" },
];

const LEGEND = FILTER_TYPES.filter((item) => item.id !== "all");

const CX = 520;
const CY = 300;

function polar(angleDeg: number, radius: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + Math.cos(rad) * radius, y: CY + Math.sin(rad) * radius };
}

function buildGraph(): { nodes: GraphNode[]; edges: [string, string, string][] } {
  const clusters: {
    id: string;
    label: string;
    angle: number;
    color: string;
    type: string;
    children: string[];
  }[] = [
    {
      id: "projects",
      label: "Projects",
      angle: 200,
      color: "#D6A957",
      type: "project",
      children: ["LEVIATHAN", "Roadmap", "Tasks", "Documentation", "Releases"],
    },
    {
      id: "programming",
      label: "Programming",
      angle: 250,
      color: "#4285E8",
      type: "concept",
      children: ["Python", "C++", "Code Generation", "Software Architecture", "APIs", "Best Practices"],
    },
    {
      id: "trading",
      label: "Trading",
      angle: 310,
      color: "#20DC8C",
      type: "concept",
      children: ["Market Analysis", "Technical Analysis", "Risk Management", "Strategies", "Backtesting"],
    },
    {
      id: "models",
      label: "AI / Models",
      angle: 20,
      color: "#9B8CFF",
      type: "model",
      children: ["Model Training", "Fine-tuning", "Evaluation", "RAG", "Embeddings"],
    },
    {
      id: "tools",
      label: "Tools",
      angle: 70,
      color: "#DB8A34",
      type: "tool",
      children: ["Web Search", "File System", "Browser Control", "API Tools", "MCP", "Computer Use"],
    },
    {
      id: "datasets",
      label: "Datasets",
      angle: 120,
      color: "#E4599A",
      type: "dataset",
      children: ["HuggingFace", "Local Datasets", "Synthetic Data", "Curated Data"],
    },
    {
      id: "knowledge",
      label: "Knowledge",
      angle: 155,
      color: "#5B9FE8",
      type: "document",
      children: ["Research Papers", "Books", "Scientific Data", "Web Sources"],
    },
  ];

  const nodes: GraphNode[] = [
    {
      id: "hades",
      label: "HADES",
      x: CX,
      y: CY,
      r: 36,
      color: "#F0C875",
      type: "concept",
      core: true,
    },
  ];
  const edges: [string, string, string][] = [];

  clusters.forEach((cluster) => {
    const hub = polar(cluster.angle, 175);
    nodes.push({
      id: cluster.id,
      label: cluster.label,
      x: hub.x,
      y: hub.y,
      r: 22,
      color: cluster.color,
      type: cluster.type,
      hub: true,
    });
    edges.push(["hades", cluster.id, cluster.color]);

    const childCount = cluster.children.length;
    cluster.children.forEach((child, index) => {
      const spread = 62;
      const start = cluster.angle - spread / 2;
      const step = childCount > 1 ? spread / (childCount - 1) : 0;
      const childPos = polar(start + step * index, 278);
      const childId = `${cluster.id}-${index}`;
      nodes.push({
        id: childId,
        label: child,
        x: childPos.x,
        y: childPos.y,
        r: 8,
        color: cluster.color,
        type: cluster.type,
        parent: cluster.id,
      });
      edges.push([cluster.id, childId, cluster.color]);
    });
  });

  // Cross-links between hubs (subtle)
  edges.push(["programming", "trading", "rgba(214,169,87,0.18)"]);
  edges.push(["models", "tools", "rgba(214,169,87,0.18)"]);
  edges.push(["projects", "knowledge", "rgba(214,169,87,0.18)"]);

  return { nodes, edges };
}

const { nodes: GRAPH_NODES, edges: GRAPH_EDGES } = buildGraph();

const VIEWS: { id: "Graph" | "Tree" | "Timeline" | "Clusters" | "Analytics"; icon: ReactNode }[] = [
  {
    id: "Graph",
    icon: (
      <>
        <circle cx="8" cy="8" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="16" cy="8" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="12" cy="16" r="2.2" fill="currentColor" stroke="none" />
        <path d="M9.5 9.2l2 5M14.5 9.2l-2 5" />
      </>
    ),
  },
  {
    id: "Tree",
    icon: (
      <>
        <path d="M12 4v6M8 20v-6h8v6" />
        <circle cx="12" cy="4" r="2" />
      </>
    ),
  },
  {
    id: "Timeline",
    icon: (
      <>
        <path d="M4 12h16" />
        <circle cx="8" cy="12" r="2" fill="currentColor" stroke="none" />
        <circle cx="16" cy="12" r="2" fill="currentColor" stroke="none" />
      </>
    ),
  },
  {
    id: "Clusters",
    icon: (
      <>
        <circle cx="8" cy="8" r="2.5" />
        <circle cx="16" cy="8" r="2.5" />
        <circle cx="8" cy="16" r="2.5" />
        <circle cx="16" cy="16" r="2.5" />
      </>
    ),
  },
  {
    id: "Analytics",
    icon: <path d="M5 18V10M12 18V6M19 18v-8" />,
  },
];

const STARS = Array.from({ length: 70 }, (_, index) => {
  const x = (index * 97) % 1040;
  const y = (index * 53) % 600;
  const r = 0.6 + ((index * 17) % 10) / 10;
  return { x, y, r, o: 0.15 + ((index * 13) % 40) / 100 };
});

export function BrainPage() {
  const toast = useAppToast();
  const [view, setView] = useState<(typeof VIEWS)[number]["id"]>("Graph");
  const [activeTypes, setActiveTypes] = useState<Set<string>>(
    () => new Set(FILTER_TYPES.map((item) => item.id)),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [showClusters, setShowClusters] = useState(true);
  const [showDepth, setShowDepth] = useState(false);
  const [physics, setPhysics] = useState(true);
  const [query, setQuery] = useState("");
  const [typeQuery, setTypeQuery] = useState("");
  const [zoom, setZoom] = useState(100);

  const nodeMap = useMemo(() => new Map(GRAPH_NODES.map((node) => [node.id, node])), []);

  const visibleNodes = useMemo(() => {
    const q = query.trim().toLowerCase();
    const allOn = activeTypes.has("all");
    return GRAPH_NODES.filter((node) => {
      if (node.core) return true;
      if (!allOn && !activeTypes.has(node.type)) return false;
      if (!showClusters && node.hub) return false;
      if (!q) return true;
      return node.label.toLowerCase().includes(q);
    });
  }, [activeTypes, query, showClusters]);

  const selected = selectedId ? nodeMap.get(selectedId) ?? null : null;

  const toggleType = (id: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (id === "all") {
        return next.has("all")
          ? new Set<string>()
          : new Set(FILTER_TYPES.map((item) => item.id));
      }
      if (next.has(id)) next.delete(id);
      else next.add(id);
      const nonAll = FILTER_TYPES.filter((item) => item.id !== "all").every((item) => next.has(item.id));
      if (nonAll) next.add("all");
      else next.delete("all");
      return next;
    });
  };

  const filteredTypes = FILTER_TYPES.filter((item) =>
    item.label.toLowerCase().includes(typeQuery.trim().toLowerCase()),
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Brain Mode"
      searchPlaceholder="Search nodes, concepts, memories, datasets..."
      pageClass="lv-app--brain"
    >
      <main className="lv-main lv-brain-main">
        <section className="lv-brain-hero">
          <div className="lv-brain-hero-media">
            <img src="/assets/hero.jpg" alt="" />
          </div>
          <div className="lv-brain-hero-shade" />
          <div className="lv-brain-hero-copy">
            <h1>BRAIN</h1>
            <div className="lv-brain-hero-kicker">Dynamic Knowledge Network</div>
            <p>“All knowledge is connected.”</p>
          </div>
        </section>

        <div className="lv-brain-toolbar">
          <div className="lv-brain-view-tabs" role="tablist">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                className={`lv-brain-view-tab${view === item.id ? " is-active" : ""}`}
                type="button"
                onClick={() => {
                  setView(item.id);
                  if (item.id !== "Graph") toast(`${item.id} view (mock)`);
                }}
              >
                <svg className="lv-icon" viewBox="0 0 24 24">
                  {item.icon}
                </svg>
                {item.id}
              </button>
            ))}
          </div>

          <label className="lv-brain-search">
            <svg className="lv-icon" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="6" />
              <path d="M20 20l-3.2-3.2" />
            </svg>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search"
              aria-label="Search graph"
            />
          </label>

          <select className="lv-select lv-brain-domain" defaultValue="all" aria-label="Domain">
            <option value="all">All Domains</option>
            <option value="projects">Projects</option>
            <option value="models">Models</option>
            <option value="tools">Tools</option>
            <option value="trading">Trading</option>
          </select>

          <div className="lv-brain-tool-icons">
            <button className="lv-icon-btn" type="button" aria-label="Map" onClick={() => toast("Map")}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M4 7l6-2 4 2 6-2v14l-6 2-4-2-6 2V7z" />
                <path d="M10 5v14M14 7v14" />
              </svg>
            </button>
            <button className="lv-icon-btn" type="button" aria-label="Connect" onClick={() => toast("Connect")}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <circle cx="7" cy="12" r="3" />
                <circle cx="17" cy="7" r="3" />
                <circle cx="17" cy="17" r="3" />
                <path d="M9.7 10.5l4.6-2.2M9.7 13.5l4.6 2.2" />
              </svg>
            </button>
            <button className="lv-icon-btn" type="button" aria-label="Settings" onClick={() => toast("Graph settings")}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.5 6.5l1.4 1.4M16.1 16.1l1.4 1.4M17.5 6.5l-1.4 1.4M7.9 16.1l-1.4 1.4" />
              </svg>
            </button>
          </div>

          <button className="lv-btn lv-btn-gold lv-brain-add" type="button" onClick={() => toast("Add Node")}>
            + Add Node
          </button>
        </div>

        <div className="lv-brain-layout">
          <aside className="lv-panel lv-brain-filters">
            <div className="lv-section-label">Filter Nodes</div>
            <label className="lv-brain-search lv-brain-search--block">
              <svg className="lv-icon" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="6" />
                <path d="M20 20l-3.2-3.2" />
              </svg>
              <input
                value={typeQuery}
                onChange={(event) => setTypeQuery(event.target.value)}
                placeholder="Search nodes..."
                aria-label="Search node types"
              />
            </label>

            <div className="lv-filter-list">
              {filteredTypes.map((type) => (
                <label key={type.id} className={`lv-filter-check${activeTypes.has(type.id) ? " is-active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={activeTypes.has(type.id)}
                    onChange={() => toggleType(type.id)}
                  />
                  <span className="lv-filter-swatch" style={{ background: type.color, boxShadow: `0 0 8px ${type.color}` }} />
                  <span className="lv-filter-label">{type.label}</span>
                  <span className="lv-filter-count">{type.count}</span>
                </label>
              ))}
            </div>

            <div className="lv-section-label">Relationship Filter</div>
            <select className="lv-select" defaultValue="all" aria-label="Relations" style={{ width: "100%" }}>
              <option value="all">All Relations</option>
              <option value="depends">Depends On</option>
              <option value="contains">Contains</option>
              <option value="related">Related To</option>
            </select>

            <div className="lv-brain-toggles">
              <button className="lv-toggle" type="button" onClick={() => setShowLabels((v) => !v)}>
                <span className={`lv-switch${showLabels ? " is-on" : ""}`} />
                Show Labels
              </button>
              <button className="lv-toggle" type="button" onClick={() => setShowClusters((v) => !v)}>
                <span className={`lv-switch${showClusters ? " is-on" : ""}`} />
                Show Clusters
              </button>
              <button className="lv-toggle" type="button" onClick={() => setShowDepth((v) => !v)}>
                <span className={`lv-switch${showDepth ? " is-on" : ""}`} />
                Show Depth
              </button>
              <button className="lv-toggle" type="button" onClick={() => setPhysics((v) => !v)}>
                <span className={`lv-switch${physics ? " is-on" : ""}`} />
                Physics Layout
              </button>
            </div>
          </aside>

          <div className="lv-brain-workspace">
            <div className="lv-graph-canvas" aria-label="Knowledge graph">
              <div className="lv-graph-zoom">
                <button type="button" onClick={() => setZoom((z) => Math.max(50, z - 10))}>
                  −
                </button>
                <span>{zoom}%</span>
                <button type="button" onClick={() => setZoom((z) => Math.min(160, z + 10))}>
                  +
                </button>
                <button type="button" aria-label="Fit" onClick={() => setZoom(100)}>
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
                  </svg>
                </button>
              </div>

              <svg
                viewBox="0 0 1040 600"
                preserveAspectRatio="xMidYMid meet"
                style={{ transform: `scale(${zoom / 100})`, transformOrigin: "center center" }}
              >
                <defs>
                  <radialGradient id="hadesGlow" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="#F5DFA9" stopOpacity="0.95" />
                    <stop offset="45%" stopColor="#D6A957" stopOpacity="0.55" />
                    <stop offset="100%" stopColor="#D6A957" stopOpacity="0" />
                  </radialGradient>
                  <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="3.5" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>

                {STARS.map((star, index) => (
                  <circle key={index} cx={star.x} cy={star.y} r={star.r} fill="#F5DFA9" opacity={star.o} />
                ))}

                {showDepth
                  ? [90, 168, 268].map((radius) => (
                      <circle
                        key={radius}
                        cx={CX}
                        cy={CY}
                        r={radius}
                        fill="none"
                        stroke="rgba(214,169,87,0.08)"
                        strokeDasharray="3 6"
                      />
                    ))
                  : null}

                {GRAPH_EDGES.map(([from, to, color]) => {
                  const a = nodeMap.get(from);
                  const b = nodeMap.get(to);
                  if (!a || !b) return null;
                  if (!visibleNodes.some((n) => n.id === from) || !visibleNodes.some((n) => n.id === to)) {
                    return null;
                  }
                  const isHubLink = from === "hades";
                  return (
                    <line
                      key={`${from}-${to}`}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke={color.startsWith("rgba") ? color : `${color}55`}
                      strokeWidth={isHubLink ? 1.6 : 1.1}
                      opacity={isHubLink ? 0.85 : 0.65}
                    />
                  );
                })}

                {visibleNodes.map((node) => {
                  const active = selectedId === node.id;
                  const labelOffset = node.core ? 56 : node.hub ? 34 : 18;
                  return (
                    <g
                      key={node.id}
                      className={`lv-graph-node${active ? " is-active" : ""}${node.hub ? " is-hub" : ""}${node.core ? " is-core" : ""}`}
                      onClick={() => setSelectedId(node.id)}
                      filter={node.core || node.hub ? "url(#softGlow)" : undefined}
                    >
                      {node.core ? (
                        <>
                          <circle cx={node.x} cy={node.y} r={72} fill="url(#hadesGlow)" />
                          <circle
                            cx={node.x}
                            cy={node.y}
                            r={48}
                            fill="none"
                            stroke="rgba(240,200,117,0.18)"
                            strokeWidth={10}
                          />
                          <circle
                            cx={node.x}
                            cy={node.y}
                            r={node.r}
                            fill="rgba(12,10,6,0.94)"
                            stroke="#F0C875"
                            strokeWidth={2.2}
                          />
                          <g
                            transform={`translate(${node.x}, ${node.y - 4}) scale(0.72) translate(-24, -24)`}
                            stroke="#F0C875"
                            fill="none"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <circle cx="24" cy="24" r="18" stroke="rgba(240,200,117,0.35)" />
                            <path d="M24 8v32M14 14l10-4 10 4M12 24h24M14 34l10 4 10-4" />
                          </g>
                        </>
                      ) : (
                        <>
                          {node.hub ? (
                            <circle
                              cx={node.x}
                              cy={node.y}
                              r={node.r + 10}
                              fill={node.color}
                              opacity={0.12}
                            />
                          ) : null}
                          <circle
                            cx={node.x}
                            cy={node.y}
                            r={active ? node.r + 3 : node.r}
                            fill={node.hub ? `${node.color}28` : "rgba(8,10,9,0.88)"}
                            stroke={node.color}
                            strokeWidth={node.hub ? 2 : 1.3}
                          />
                          <circle cx={node.x} cy={node.y} r={node.hub ? 5.5 : 2.4} fill={node.color} />
                        </>
                      )}
                      {showLabels ? (
                        <text
                          className={`lv-graph-label${node.core ? " core" : ""}${node.hub ? " hub" : ""}`}
                          x={node.x}
                          y={node.y + labelOffset}
                          textAnchor="middle"
                        >
                          {node.label}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </svg>

              <div className="lv-graph-legend">
                {LEGEND.map((item) => (
                  <span key={item.id}>
                    <i style={{ background: item.color }} />
                    {item.label}
                  </span>
                ))}
              </div>
            </div>

            <div className="lv-brain-bottom">
              <article className="lv-panel lv-card">
                <div className="lv-section-label">
                  Selected Nodes ({selected ? 1 : 0})
                </div>
                {selected ? (
                  <p className="lv-node-desc">
                    {selected.label} · {selected.type}
                  </p>
                ) : (
                  <p className="lv-node-desc lv-empty-hint">
                    No nodes selected. Click on a node to view details or select multiple nodes.
                  </p>
                )}
              </article>

              <article className="lv-panel lv-card">
                <div className="lv-section-label">Quick Actions</div>
                <div className="lv-quick-actions">
                  {[
                    { label: "Add Node", icon: <path d="M12 5v14M5 12h14" /> },
                    {
                      label: "Create Cluster",
                      icon: (
                        <>
                          <circle cx="8" cy="8" r="2.5" />
                          <circle cx="16" cy="8" r="2.5" />
                          <circle cx="8" cy="16" r="2.5" />
                          <circle cx="16" cy="16" r="2.5" />
                        </>
                      ),
                    },
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
                    <span>Connections</span>
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
            <div className="lv-node-details-title-row">
              <span className="lv-node-trident" aria-hidden="true">
                <svg viewBox="0 0 24 24" className="lv-icon">
                  <path d="M12 2v22M5 7l7-3 7 3M4 14h16M6 20l6 3 6-3" />
                </svg>
              </span>
              <div>
                <h2>Node Details</h2>
                <h3 className="lv-node-title">{selected?.label ?? "HADES"}</h3>
              </div>
            </div>
            <button className="lv-icon-btn" type="button" aria-label="Close" onClick={() => setSelectedId(null)}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          <div className="lv-toolbar">
            <span className="lv-tag blue">Core</span>
            <span className="lv-tag cyan">Concept</span>
          </div>

          <p className="lv-node-desc">
            {selected && selected.id !== "hades"
              ? `Linked knowledge node “${selected.label}” in the Leviathan brain graph.`
              : "Central intelligence system connecting projects, models, datasets, tools, and memory into one dynamic knowledge network."}
          </p>

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
              <strong>{selected?.type ?? "Concept"}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Created</span>
              <strong>Jan 12, 2025</strong>
            </div>
            <div className="lv-meta-item">
              <span>Last Updated</span>
              <strong>Sep 17, 2026</strong>
            </div>
            <div className="lv-meta-item">
              <span>Connections</span>
              <strong>1,842</strong>
            </div>
          </div>

          <div className="lv-relevance">
            <div className="lv-meta-item">
              <span>Relevance</span>
              <strong>100%</strong>
            </div>
            <div className="lv-relevance-bar">
              <span style={{ width: "100%" }} />
            </div>
          </div>

          <div className="lv-meta-item">
            <span>Domains</span>
            <div className="lv-toolbar" style={{ marginTop: 6 }}>
              <span className="lv-tag gold">Core</span>
              <span className="lv-tag">System</span>
              <span className="lv-tag">Meta</span>
            </div>
          </div>

          <div className="lv-meta-item">
            <span>Status</span>
            <strong className="lv-model-status">
              <span className="lv-status-dot ready" />
              Active
            </strong>
          </div>

          <div className="lv-detail-actions">
            <button className="lv-btn" type="button" onClick={() => toast("Open in Chat")}>
              Open in Chat
            </button>
            <button className="lv-btn" type="button" onClick={() => toast("Expand Node")}>
              Expand Node
            </button>
            <button className="lv-btn" type="button" onClick={() => toast("Add Relation")}>
              + Add Relation
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
