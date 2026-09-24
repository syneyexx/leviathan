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
import { BrainGraphCanvas } from "./brain/BrainGraphCanvas";
import { BrainTimelineView } from "./brain/BrainTimelineView";
import { BrainTreeView } from "./brain/BrainTreeView";
import { colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain/brain-live";

type DetailTab = "Overview" | "Relations" | "Content" | "Metrics";

function deepLink(node: LiveBrainNode): string | null {
  if (node.type === "knowledge.document") return "/knowledge";
  if (node.type === "evidence") return `/evidence?evidence=${encodeURIComponent(node.id.replace(/^evidence:/, ""))}`;
  if (node.type === "research.project") return `/research?project=${encodeURIComponent(node.id.replace(/^research:project:/, ""))}`;
  if (node.type === "dataset") return `/datasets?dataset=${encodeURIComponent(node.id.replace(/^dataset:/, ""))}`;
  if (node.type === "memory") return "/memory";
  if (node.type === "module") return `/modules?module=${encodeURIComponent(node.id.replace(/^module:/, ""))}`;
  if (node.type.startsWith("mcp.")) return "/mcp";
  if (node.type === "workflow") return "/workflows";
  if (node.type === "capability") return "/tools";
  return null;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function prettyType(type: string): string {
  return type
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => part.length <= 3 ? part.toUpperCase() : `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function displayDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function ToggleRow({ label, value, onChange }: { label: string; value: boolean; onChange: () => void }) {
  return (
    <button className="lv-gv-toggle" type="button" onClick={onChange} aria-pressed={value}>
      <span className="lv-gv-toggle-icon" aria-hidden="true">◇</span>
      <span>{label}</span>
      <span className={`lv-gv-switch${value ? " is-on" : ""}`}><i /></span>
    </button>
  );
}

export function BrainPage() {
  const toast = useAppToast();
  const [searchParams] = useSearchParams();
  const [view, setView] = useState<BrainView>("Graph");
  const [nodes, setNodes] = useState<LiveBrainNode[]>([]);
  const [edges, setEdges] = useState<LiveBrainEdge[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [nodeSearch, setNodeSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState(() => searchParams.get("types") || "");
  const [relationFilter, setRelationFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [showClusters, setShowClusters] = useState(true);
  const [showDepth, setShowDepth] = useState(false);
  const [physicsLayout, setPhysicsLayout] = useState(true);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());
  const [detailTab, setDetailTab] = useState<DetailTab>("Overview");

  const load = useCallback(async (root?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.brainGraph({ limit: 250, q: q.trim() || undefined, types: typeFilter || undefined, root });
      setNodes(data.nodes);
      setEdges(data.edges);
      setStats(data.stats as Record<string, unknown>);
      setActiveTypes(new Set(data.nodes.map((node) => node.type)));
      setSelectedId((previous) => {
        if (previous && data.nodes.some((node) => node.id === previous)) return previous;
        return data.nodes.find((node) => /leviathan/i.test(node.label))?.id ?? data.nodes[0]?.id ?? null;
      });
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

  useEffect(() => { void load(); }, [load]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const node of nodes) counts[node.type] = (counts[node.type] ?? 0) + 1;
    return counts;
  }, [nodes]);
  const typeOptions = useMemo(() => Object.keys(typeCounts).sort((a, b) => typeCounts[b] - typeCounts[a] || a.localeCompare(b)), [typeCounts]);
  const relationOptions = useMemo(() => [...new Set(edges.map((edge) => edge.relation).filter(Boolean))].sort(), [edges]);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  const visibleNodes = useMemo(() => {
    const query = nodeSearch.trim().toLowerCase();
    return nodes.filter((node) => {
      if (!activeTypes.has(node.type)) return false;
      if (!query) return true;
      return node.label.toLowerCase().includes(query) || node.type.toLowerCase().includes(query) || node.id.toLowerCase().includes(query);
    });
  }, [nodes, activeTypes, nodeSearch]);
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target) && (!relationFilter || edge.relation === relationFilter)), [edges, visibleNodeIds, relationFilter]);

  const selected = (selectedId ? nodeMap.get(selectedId) : null) ?? visibleNodes[0] ?? nodes[0] ?? null;
  const selectedEdges = useMemo(() => selected ? edges.filter((edge) => edge.source === selected.id || edge.target === selected.id) : [], [edges, selected]);
  const connectionCount = selectedEdges.length;
  const degrees = useMemo(() => {
    const map = new Map<string, number>();
    for (const edge of edges) {
      map.set(edge.source, (map.get(edge.source) ?? 0) + 1);
      map.set(edge.target, (map.get(edge.target) ?? 0) + 1);
    }
    return map;
  }, [edges]);
  const maxDegree = useMemo(() => Math.max(1, ...degrees.values()), [degrees]);
  const relevance = selected ? Math.round(((degrees.get(selected.id) ?? 0) / maxDegree) * 100) : 0;

  const headerStats = useMemo(() => {
    const nodeCount = (stats?.node_count as number | undefined) ?? nodes.length;
    const edgeCount = (stats?.edge_count as number | undefined) ?? edges.length;
    const byType = (stats?.by_type as Record<string, number> | undefined) ?? typeCounts;
    return [
      { label: "Nodes", value: formatCount(nodeCount), icon: "nodes" },
      { label: "Connections", value: formatCount(edgeCount), icon: "links" },
      { label: "Knowledge Domains", value: String(Object.keys(byType).length), icon: "domains" },
      { label: "Last Updated", value: loading ? "Refreshing…" : error ? "Error" : "Live", icon: "clock" },
    ];
  }, [stats, nodes.length, edges.length, typeCounts, loading, error]);

  const toggleType = (type: string) => {
    setActiveTypes((previous) => {
      const next = new Set(previous);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };
  const allTypesActive = typeOptions.length > 0 && typeOptions.every((type) => activeTypes.has(type));
  const toggleAllTypes = () => setActiveTypes(allTypesActive ? new Set() : new Set(typeOptions));
  const isGraph = view === "Graph";
  const selectedMetaEntries = selected ? Object.entries(selected.meta ?? {}).filter(([, value]) => value != null).slice(0, 10) : [];
  const status = selected && typeof selected.meta?.status === "string" ? selected.meta.status : selected && selected.meta?.available === false ? "Unavailable" : "Active";
  const domains = selected ? [prettyType(selected.type.split(".")[0]), typeof selected.meta?.scope === "string" ? selected.meta.scope : null, typeof selected.meta?.provider_kind === "string" ? selected.meta.provider_kind : null].filter((value): value is string => Boolean(value)).slice(0, 3) : [];

  const nodeDetails = (
    <aside className="lv-panel lv-panel-premium lv-node-details lv-gv-details">
      <div className="lv-node-details-head"><h2>Node Details</h2><button type="button" className="lv-gv-close" onClick={() => setSelectedId(null)} aria-label="Close node details">×</button></div>
      {selected ? (
        <>
          <div className="lv-gv-detail-identity">
            <div className="lv-gv-detail-emblem" style={{ color: colorForType(selected.type) }}>L</div>
            <div><h3 className="lv-node-title">{selected.label}</h3><div className="lv-toolbar"><span className="lv-tag gold">{prettyType(selected.type)}</span><span className="lv-tag">Live</span></div></div>
          </div>
          <p className="lv-node-desc">{typeof selected.meta?.description === "string" ? selected.meta.description : "Live projection node from LEVIATHAN's authoritative Knowledge, Evidence, Research, Dataset, Memory, Tool and Runtime stores."}</p>
          <div className="lv-gv-detail-tabs">
            {(["Overview", "Relations", "Content", "Metrics"] as DetailTab[]).map((tab) => <button key={tab} type="button" className={detailTab === tab ? "is-active" : ""} onClick={() => setDetailTab(tab)}>{tab}{tab === "Relations" ? ` (${connectionCount})` : ""}</button>)}
          </div>

          {detailTab === "Overview" ? (
            <div className="lv-gv-detail-body">
              <div className="lv-gv-meta-list">
                <div><span>Type</span><strong>{prettyType(selected.type)}</strong></div>
                <div><span>Created</span><strong>{displayDate(selected.created_at)}</strong></div>
                <div><span>Last Updated</span><strong>{typeof selected.meta?.updated_at === "string" ? displayDate(selected.meta.updated_at) : "Live projection"}</strong></div>
                <div><span>Connections</span><strong>{connectionCount.toLocaleString()}</strong></div>
              </div>
              <div className="lv-gv-relevance"><div><span>Graph Relevance</span><strong>{relevance}%</strong></div><div className="lv-gv-progress"><i style={{ width: `${relevance}%` }} /></div></div>
              <div className="lv-gv-detail-section"><span>Domains</span><div className="lv-gv-domain-tags">{domains.map((domain) => <i key={domain}>{domain}</i>)}</div></div>
              <div className="lv-gv-status"><span>Status</span><strong className={status.toLowerCase().includes("unavailable") ? "is-bad" : "is-good"}><i />{status}</strong></div>
            </div>
          ) : null}

          {detailTab === "Relations" ? (
            <ul className="lv-gv-relations">{selectedEdges.length ? selectedEdges.map((edge) => { const otherId = edge.source === selected.id ? edge.target : edge.source; const other = nodeMap.get(otherId); return <li key={edge.id}><button type="button" onClick={() => other && setSelectedId(other.id)}><span>{edge.relation}</span><strong>{other?.label ?? otherId}</strong></button></li>; }) : <li className="lv-br-muted">No relationships in the current bounded projection.</li>}</ul>
          ) : null}

          {detailTab === "Content" ? (
            <div className="lv-gv-content-list">{selectedMetaEntries.length ? selectedMetaEntries.map(([key, value]) => <div key={key}><span>{key}</span><code>{typeof value === "object" ? JSON.stringify(value) : String(value)}</code></div>) : <p className="lv-br-muted">No additional source metadata exposed by this projection.</p>}</div>
          ) : null}

          {detailTab === "Metrics" ? (
            <div className="lv-gv-metric-grid"><div><strong>{connectionCount}</strong><span>Connections</span></div><div><strong>{relevance}%</strong><span>Relative Degree</span></div><div><strong>{selectedEdges.filter((edge) => edge.source === selected.id).length}</strong><span>Outgoing</span></div><div><strong>{selectedEdges.filter((edge) => edge.target === selected.id).length}</strong><span>Incoming</span></div></div>
          ) : null}

          <div className="lv-detail-actions lv-gv-detail-actions">
            <Link className="lv-btn" to={`/chat?brain_node=${encodeURIComponent(selected.id)}`}>◉ Open in Chat</Link>
            <button className="lv-btn" type="button" onClick={() => void load(selected.id)}>⟳ Expand Node</button>
            {deepLink(selected) ? <Link className="lv-btn" to={deepLink(selected)!}>＋ Open Source</Link> : <button className="lv-btn" type="button" disabled>＋ No Source Link</button>}
            <button className="lv-btn" type="button" onClick={() => setView("Tree")}>◇ Open in Tree</button>
          </div>
        </>
      ) : <p className="lv-node-desc">{loading ? "Loading…" : "Select a node in the graph to inspect it."}</p>}
    </aside>
  );

  return (
    <AppShell activeMode="explore" modeLabel="Brain Mode" searchPlaceholder="Search nodes, concepts, memories, datasets..." layout="wide" pageClass="lv-app--brain-views lv-app--brain-fidelity">
      <main className={`lv-main lv-br-main${isGraph ? " lv-gv-main" : ""}`}>
        {isGraph ? (
          <section className="lv-page-hero lv-gv-hero">
            <div className="lv-hero-media"><img src={media.architectureBg} alt="" width={1400} height={380} /></div>
            <div className="lv-hero-shade" />
            <div className="lv-hero-content">
              <div className="lv-hero-kicker"><span />Dynamic Knowledge Network<span /></div>
              <h1 className="lv-hero-title">Brain</h1>
              <p className="lv-page-quote">“All knowledge is connected.”</p>
            </div>
            <div className="lv-hero-rail" aria-hidden="true"><span>Graph</span><span>Memory</span><span>Reason</span><span>Link</span></div>
          </section>
        ) : <BrainHeader stats={headerStats} quote={view === "Analytics" ? "“Knowledge compounds. Intelligence emerges.”" : "“Everything is connected.”"} />}

        <BrainViewTabs
          view={view}
          onChange={setView}
          trailing={<>
            <input className="lv-br-input lv-gv-top-filter" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Filter graph…" aria-label="Filter graph" />
            <select className="lv-br-select" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} aria-label="Type filter">
              <option value="">All types</option>
              {typeOptions.map((type) => <option key={type} value={type}>{prettyType(type)} ({typeCounts[type]})</option>)}
            </select>
            <button className="lv-br-btn" type="button" onClick={() => void load()}>Refresh</button>
            <button className="lv-br-btn is-gold" type="button" onClick={() => toast("Brain is a read projection — add knowledge through its authoritative source.")}>+ Add Node</button>
          </>}
        />

        {error ? <div role="alert" className="lv-panel lv-gv-error">{error}</div> : null}
        {view === "Tree" ? <BrainTreeView nodes={nodes} edges={edges} onToast={toast} onSelect={setSelectedId} /> : null}
        {view === "Timeline" ? <BrainTimelineView nodes={nodes} edges={edges} onToast={toast} /> : null}
        {view === "Clusters" ? <BrainClustersView nodes={nodes} edges={edges} onToast={toast} /> : null}
        {view === "Analytics" ? <BrainAnalyticsView nodes={nodes} edges={edges} stats={stats} onToast={toast} /> : null}

        {isGraph ? <>
          <div className="lv-brain-layout lv-gv-layout">
            <aside className="lv-panel lv-brain-filters lv-gv-filters">
              <div className="lv-section-label">Filter Nodes</div>
              <label className="lv-gv-filter-search"><span aria-hidden="true">⌕</span><input value={nodeSearch} onChange={(event) => setNodeSearch(event.target.value)} placeholder="Search nodes..." /></label>
              <div className="lv-gv-type-list">
                <button className={`lv-gv-type-row${allTypesActive ? " is-active" : ""}`} type="button" onClick={toggleAllTypes}><span className="lv-gv-check">{allTypesActive ? "✓" : ""}</span><span>All Types</span><em>{formatCount(nodes.length)}</em></button>
                {typeOptions.map((type) => <button key={type} className={`lv-gv-type-row${activeTypes.has(type) ? " is-active" : ""}`} type="button" onClick={() => toggleType(type)}><span className="lv-gv-check" style={{ color: colorForType(type), borderColor: colorForType(type) }}>{activeTypes.has(type) ? "•" : ""}</span><span>{prettyType(type)}</span><em>{formatCount(typeCounts[type])}</em></button>)}
              </div>
              <div className="lv-gv-filter-section"><div className="lv-section-label">Relationship Filter</div><select className="lv-br-select" value={relationFilter} onChange={(event) => setRelationFilter(event.target.value)}><option value="">All Relations</option>{relationOptions.map((relation) => <option key={relation} value={relation}>{relation}</option>)}</select></div>
              <div className="lv-gv-filter-section lv-gv-toggle-list">
                <ToggleRow label="Show Labels" value={showLabels} onChange={() => setShowLabels((value) => !value)} />
                <ToggleRow label="Show Clusters" value={showClusters} onChange={() => setShowClusters((value) => !value)} />
                <ToggleRow label="Show Depth" value={showDepth} onChange={() => setShowDepth((value) => !value)} />
                <ToggleRow label="Physics Layout" value={physicsLayout} onChange={() => setPhysicsLayout((value) => !value)} />
              </div>
              <div className="lv-gv-filter-foot">{loading ? "Loading projection…" : `${visibleNodes.length} visible · ${visibleEdges.length} links`}</div>
            </aside>

            <div className="lv-brain-workspace lv-gv-workspace">
              <BrainGraphCanvas nodes={visibleNodes} edges={visibleEdges} selectedId={selected?.id ?? null} onSelect={(id) => { setSelectedId(id); setDetailTab("Overview"); }} showLabels={showLabels} showClusters={showClusters} showDepth={showDepth} physicsLayout={physicsLayout} />
            </div>

            {nodeDetails}
          </div>

          <div className="lv-brain-bottom lv-gv-bottom">
            <article className="lv-panel lv-card"><div className="lv-section-label">Selected Nodes (1)</div><p className="lv-node-desc">{selected ? `${selected.label} · ${prettyType(selected.type)}` : "Click a node to view details or select multiple nodes."}</p></article>
            <article className="lv-panel lv-card"><div className="lv-section-label">Quick Actions</div><div className="lv-quick-actions"><button className="lv-quick-action" type="button" onClick={() => toast("Brain is read-only; create nodes through Knowledge, Research or Datasets.")}>＋ Add Node</button><button className="lv-quick-action" type="button" onClick={() => setView("Clusters")}>Create Cluster</button><button className="lv-quick-action" type="button" onClick={() => selected && setShowDepth(true)}>⌕ Find Related</button><button className="lv-quick-action" type="button" onClick={() => setView("Analytics")}>▥ Analyze Graph</button></div></article>
            <article className="lv-panel lv-card"><div className="lv-section-label">Graph Statistics</div><div className="lv-stat-strip">{headerStats.slice(0, 4).map((item) => <div key={item.label} className="lv-stat-card"><strong>{item.value}</strong><span>{item.label}</span></div>)}</div></article>
          </div>
          <p className="lv-footer-quote">“A greater mind is a more connected mind.” — LEVIATHAN</p>
        </> : null}
      </main>
    </AppShell>
  );
}
