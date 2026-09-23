import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { media } from "../assets/media";
import { api } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { BrainView } from "./brain/brain-mock";
import { BrainHeader, BrainViewTabs } from "./brain/brain-shared";
import { BrainAnalyticsView } from "./brain/BrainAnalyticsView";
import { BrainClustersView } from "./brain/BrainClustersView";
import { BrainTimelineView } from "./brain/BrainTimelineView";
import { BrainTreeView } from "./brain/BrainTreeView";

type BrainNode = {
  id: string;
  type: string;
  label: string;
  created_at?: string | null;
  meta?: Record<string, unknown>;
};

type BrainEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

type LayoutNode = BrainNode & {
  x: number;
  y: number;
  r: number;
  color: string;
  core?: boolean;
};

const TYPE_COLORS: Record<string, string> = {
  "knowledge.document": "#F0C875",
  evidence: "#22C9D6",
  "research.project": "#D6A957",
  dataset: "#E45959",
  module: "#9B8CFF",
  capability: "#DB8A34",
  "mcp.server": "#4285E8",
  "mcp.tool": "#60A5FA",
  workflow: "#20DC8C",
  atlas: "#F472B6",
  run: "#94A3B8",
  concept: "#F0C875",
  memory: "#22C9D6",
  project: "#D6A957",
  model: "#9B8CFF",
  tool: "#DB8A34",
  agent: "#4285E8",
  code: "#20DC8C",
  conversation: "#A1A1AA",
};

function colorFor(type: string): string {
  return TYPE_COLORS[type] || TYPE_COLORS[type.split(".")[0]] || "#A1A1AA";
}

function deepLink(node: BrainNode): string | null {
  if (node.type === "knowledge.document") return `/knowledge`;
  if (node.type === "evidence") return `/evidence?evidence=${encodeURIComponent(node.id.replace(/^evidence:/, ""))}`;
  if (node.type === "research.project")
    return `/research?project=${encodeURIComponent(node.id.replace(/^research:project:/, ""))}`;
  if (node.type === "dataset") return `/datasets?dataset=${encodeURIComponent(node.id.replace(/^dataset:/, ""))}`;
  if (node.type === "memory") return `/memory`;
  if (node.type === "module") return `/modules?module=${encodeURIComponent(node.id.replace(/^module:/, ""))}`;
  if (node.type.startsWith("mcp.")) return `/mcp`;
  if (node.type === "workflow") return `/workflows`;
  if (node.type === "capability") return `/tools`;
  return null;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function layoutNodes(nodes: BrainNode[]): LayoutNode[] {
  if (nodes.length === 0) return [];
  const w = 900;
  const h = 520;
  const cx = w / 2;
  const cy = h / 2;
  const byType = new Map<string, BrainNode[]>();
  for (const n of nodes) {
    const list = byType.get(n.type) ?? [];
    list.push(n);
    byType.set(n.type, list);
  }
  const types = Array.from(byType.keys());
  const positioned: LayoutNode[] = [];
  types.forEach((type, ti) => {
    const group = byType.get(type) ?? [];
    const ring = 70 + ti * 42;
    group.forEach((n, i) => {
      const angle = (i / Math.max(group.length, 1)) * Math.PI * 2 + ti * 0.35;
      positioned.push({
        ...n,
        x: cx + Math.cos(angle) * ring,
        y: cy + Math.sin(angle) * ring * 0.72,
        r: 8 + Math.min(10, (n.label?.length || 4) / 6),
        color: colorFor(n.type),
        core: i === 0 && ti === 0,
      });
    });
  });
  if (positioned.length > 0) {
    const hub =
      positioned.find((n) => /leviathan/i.test(n.label)) ??
      positioned.find((n) => n.type === "atlas") ??
      positioned[0];
    hub.x = cx;
    hub.y = cy;
    hub.r = Math.max(hub.r, 22);
    hub.core = true;
  }
  return positioned;
}

export function BrainPage() {
  const toast = useAppToast();
  const [searchParams] = useSearchParams();
  const [view, setView] = useState<BrainView>("Graph");
  const [nodes, setNodes] = useState<BrainNode[]>([]);
  const [edges, setEdges] = useState<BrainEdge[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState(() => searchParams.get("types") || "");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.brainGraph({
        limit: 200,
        q: q.trim() || undefined,
        types: typeFilter || undefined,
      });
      setNodes(data.nodes);
      setEdges(data.edges);
      setStats(data.stats as Record<string, unknown>);
      setActiveTypes(new Set(data.nodes.map((n) => n.type)));
      if (data.nodes.length > 0) {
        setSelectedId((prev) => (prev && data.nodes.some((n) => n.id === prev) ? prev : data.nodes[0].id));
      } else {
        setSelectedId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Brain graph unavailable");
      setNodes([]);
      setEdges([]);
      setStats(null);
      setActiveTypes(new Set());
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [q, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const graphNodes: LayoutNode[] = useMemo(() => layoutNodes(nodes), [nodes]);
  const graphEdges: Array<{ id: string; source: string; target: string }> = edges;

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of graphNodes) counts[n.type] = (counts[n.type] ?? 0) + 1;
    return counts;
  }, [graphNodes]);

  const typeOptions = Object.keys(typeCounts).sort();

  const visibleNodes = useMemo(() => {
    const query = q.trim().toLowerCase();
    return graphNodes.filter((node) => {
      if (!node.core && activeTypes.size > 0 && !activeTypes.has(node.type)) return false;
      if (!query) return true;
      return node.label.toLowerCase().includes(query) || node.type.toLowerCase().includes(query);
    });
  }, [graphNodes, activeTypes, q]);

  const nodeMap = useMemo(() => new Map(graphNodes.map((n) => [n.id, n])), [graphNodes]);
  const selected = (selectedId ? nodeMap.get(selectedId) : null) ?? visibleNodes[0] ?? graphNodes[0] ?? null;

  const connectionCount = useMemo(() => {
    if (!selected) return 0;
    return graphEdges.filter((e) => e.source === selected.id || e.target === selected.id).length;
  }, [graphEdges, selected]);

  const headerStats = useMemo(() => {
    const nodeCount = (stats?.node_count as number | undefined) ?? graphNodes.length;
    const edgeCount = (stats?.edge_count as number | undefined) ?? graphEdges.length;
    const byType = (stats?.by_type as Record<string, number> | undefined) ?? typeCounts;
    return [
      { label: "Nodes", value: formatCount(nodeCount), icon: "nodes" },
      { label: "Connections", value: formatCount(edgeCount), icon: "links" },
      { label: "Knowledge Domains", value: String(Object.keys(byType).length), icon: "domains" },
      {
        label: "Last Updated",
        value: loading ? "Refreshing…" : error ? "Error" : "Live",
        icon: "clock",
      },
    ];
  }, [stats, graphNodes.length, graphEdges.length, typeCounts, loading, error]);

  const toggleType = (type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const isGraph = view === "Graph";

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Brain Mode"
      searchPlaceholder="Search nodes, concepts, memories, datasets..."
      layout={isGraph ? "standard" : "wide"}
      pageClass={isGraph ? "lv-app--brain" : "lv-app--brain-views"}
    >
      <main className={`lv-main${isGraph ? "" : " lv-br-main"}`}>
        {isGraph ? (
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
        ) : (
          <BrainHeader
            stats={headerStats}
            quote={
              view === "Analytics"
                ? "“Knowledge compounds. Intelligence emerges.”"
                : "“Everything is connected.”"
            }
          />
        )}

        <BrainViewTabs
          view={view}
          onChange={setView}
          trailing={
            <>
              <input
                className="lv-br-input"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void load();
                }}
                placeholder="Filter graph…"
                aria-label="Filter graph"
                style={{ width: 160 }}
              />
              <select
                className="lv-br-select"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                aria-label="Type filter"
                style={{ width: "auto" }}
              >
                <option value="">All types</option>
                {typeOptions.map((t) => (
                  <option key={t} value={t}>
                    {t} ({typeCounts[t]})
                  </option>
                ))}
              </select>
              <button className="lv-br-btn" type="button" onClick={() => void load()}>
                Refresh
              </button>
              <button
                className="lv-br-btn is-gold"
                type="button"
                onClick={() => toast("Brain is a read projection — mutate via Knowledge / Research / Datasets.")}
              >
                + Add Node
              </button>
            </>
          }
        />

        {error ? (
          <div role="alert" className="lv-panel" style={{ padding: 10, fontSize: 12, color: "#f0a0a0" }}>
            {error}
          </div>
        ) : null}

        {view === "Tree" ? <BrainTreeView nodes={nodes} edges={edges} onToast={toast} onSelect={setSelectedId} /> : null}
        {view === "Timeline" ? <BrainTimelineView nodes={nodes} edges={edges} onToast={toast} /> : null}
        {view === "Clusters" ? <BrainClustersView nodes={nodes} edges={edges} onToast={toast} /> : null}
        {view === "Analytics" ? (
          <BrainAnalyticsView nodes={nodes} edges={edges} stats={stats} onToast={toast} />
        ) : null}

        {isGraph ? (
          <>
            <div className="lv-brain-layout">
              <aside className="lv-panel lv-brain-filters">
                <div className="lv-section-label">Filter Nodes</div>
                <div className="lv-filter-list">
                  {typeOptions.map((type) => (
                    <button
                      key={type}
                      className={`lv-filter-item${activeTypes.has(type) ? " is-active" : ""}`}
                      type="button"
                      onClick={() => toggleType(type)}
                    >
                      <span
                        className="lv-filter-swatch"
                        style={{ color: colorFor(type), background: colorFor(type) }}
                      />
                      <span>{type}</span>
                      <span>{typeCounts[type]}</span>
                    </button>
                  ))}
                </div>
                <button className="lv-toggle" type="button" onClick={() => setShowLabels((v) => !v)}>
                  <span className={`lv-switch${showLabels ? " is-on" : ""}`} />
                  Show Labels
                </button>
                <button className="lv-toggle" type="button" onClick={() => setView("Clusters")}>
                  <span className="lv-switch is-on" />
                  Show Clusters
                </button>
                <p style={{ fontSize: 10, opacity: 0.65, margin: "8px 0 0" }}>
                  {loading
                    ? "Loading projection…"
                    : error
                      ? error
                      : `${visibleNodes.length} visible · ${graphEdges.length} links`}
                </p>
              </aside>

              <div className="lv-brain-workspace">
                <div className="lv-graph-canvas" aria-label="Knowledge graph">
                  <svg viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">
                    {graphEdges.map((e) => {
                      const a = nodeMap.get(e.source);
                      const b = nodeMap.get(e.target);
                      if (!a || !b) return null;
                      if (
                        !visibleNodes.some((n) => n.id === e.source) ||
                        !visibleNodes.some((n) => n.id === e.target)
                      ) {
                        return null;
                      }
                      return (
                        <line
                          key={e.id}
                          x1={a.x}
                          y1={a.y}
                          x2={b.x}
                          y2={b.y}
                          stroke="rgba(214,169,87,0.22)"
                          strokeWidth={a.core || b.core ? 1.4 : 1}
                        />
                      );
                    })}
                    {visibleNodes.map((node) => (
                      <g
                        key={node.id}
                        className={`lv-graph-node${selected?.id === node.id ? " is-active" : ""}`}
                        onClick={() => setSelectedId(node.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={selected?.id === node.id ? node.r + 3 : node.r}
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
                        <title>{`${node.label} (${node.type})`}</title>
                      </g>
                    ))}
                  </svg>
                </div>

                <div className="lv-brain-bottom">
                  <article className="lv-panel lv-card">
                    <div className="lv-section-label">Selected Nodes</div>
                    <p className="lv-node-desc">
                      {selected ? `${selected.label} · ${selected.type}` : "Select a node"}
                    </p>
                  </article>
                  <article className="lv-panel lv-card">
                    <div className="lv-section-label">Quick Actions</div>
                    <div className="lv-quick-actions">
                      {[
                        { label: "Refresh", run: () => void load() },
                        { label: "Tree View", run: () => setView("Tree") },
                        { label: "Find Related", run: () => toast("Related nodes shown via edges") },
                        { label: "Analytics", run: () => setView("Analytics") },
                      ].map((action) => (
                        <button key={action.label} className="lv-quick-action" type="button" onClick={action.run}>
                          {action.label}
                        </button>
                      ))}
                    </div>
                  </article>
                  <article className="lv-panel lv-card">
                    <div className="lv-section-label">Graph Statistics</div>
                    <div className="lv-stat-strip">
                      {headerStats.slice(0, 4).map((s) => (
                        <div key={s.label} className="lv-stat-card">
                          <strong>{s.value}</strong>
                          <span>{s.label}</span>
                        </div>
                      ))}
                    </div>
                  </article>
                </div>
              </div>
            </div>

            <p className="lv-footer-quote">“A greater mind is a more connected mind.” — LEVIATHAN</p>
          </>
        ) : null}
      </main>

      {isGraph ? (
        <aside className="lv-right">
          <article className="lv-panel lv-panel-premium lv-node-details">
            <div className="lv-node-details-head">
              <h2>Node Details</h2>
            </div>
            {selected ? (
              <>
                <h3 className="lv-node-title">{selected.label}</h3>
                <div className="lv-toolbar">
                  <span className="lv-tag gold">{selected.type}</span>
                  {error ? <span className="lv-tag">Error</span> : <span className="lv-tag">Live</span>}
                </div>
                <p className="lv-node-desc">
                  {typeof selected.meta?.description === "string"
                    ? selected.meta.description
                    : "Bounded projection node from Knowledge, Evidence, Research, Datasets, and Runtime."}
                </p>
                <div className="lv-meta-grid">
                  <div className="lv-meta-item">
                    <span>Type</span>
                    <strong>{selected.type}</strong>
                  </div>
                  <div className="lv-meta-item">
                    <span>Created</span>
                    <strong>{selected.created_at || "—"}</strong>
                  </div>
                  <div className="lv-meta-item">
                    <span>Connections</span>
                    <strong>{connectionCount}</strong>
                  </div>
                  <div className="lv-meta-item">
                    <span>Id</span>
                    <strong style={{ fontSize: 10 }}>{selected.id}</strong>
                  </div>
                </div>
                {selected.meta && Object.keys(selected.meta).length > 0 ? (
                  <pre style={{ fontSize: 10, maxHeight: 160, overflow: "auto", opacity: 0.8 }}>
                    {JSON.stringify(selected.meta, null, 2)}
                  </pre>
                ) : null}
                <div className="lv-detail-actions">
                  {deepLink(selected) ? (
                    <Link className="lv-btn-gold lv-btn" to={deepLink(selected)!}>
                      Open authoritative page
                    </Link>
                  ) : (
                    <button
                      className="lv-btn"
                      type="button"
                      onClick={() => toast("No deep-link for this node type")}
                    >
                      No deep-link
                    </button>
                  )}
                  <button className="lv-btn" type="button" onClick={() => setView("Tree")}>
                    Open in Tree
                  </button>
                </div>
              </>
            ) : (
              <p className="lv-node-desc">
                {loading ? "Loading…" : "No entities yet — ingest knowledge, run research, or connect MCP."}
              </p>
            )}
          </article>
        </aside>
      ) : null}
    </AppShell>
  );
}
