import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import { buildClusters, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Donut, Heatmap, Panel } from "./brain-shared";

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function pretty(value: string): string {
  return value.split(/[._-]+/g).filter(Boolean).map((part) => part.length <= 3 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`).join(" ");
}

function hash(value: string): number {
  let result = 0;
  for (let i = 0; i < value.length; i += 1) result = Math.imul(31, result) + value.charCodeAt(i) | 0;
  return Math.abs(result);
}

export function BrainClustersView({ nodes, edges, onToast }: { nodes: LiveBrainNode[]; edges: LiveBrainEdge[]; onToast?: (msg: string) => void }) {
  const clusters = useMemo(() => buildClusters(nodes, edges), [nodes, edges]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"size" | "name">("size");
  const [mapScale, setMapScale] = useState(1);
  const [mapOffset, setMapOffset] = useState({ x: 0, y: 0 });
  const [draggedPositions, setDraggedPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const mapRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ pointerId: number; id: string | null; x: number; y: number; startX: number; startY: number } | null>(null);
  const [showAllConcepts, setShowAllConcepts] = useState(false);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const degreeById = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    return degree;
  }, [edges]);

  const list = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = clusters.filter((cluster) => !needle || cluster.label.toLowerCase().includes(needle) || pretty(cluster.label).toLowerCase().includes(needle));
    return [...rows].sort((a, b) => sort === "size" ? b.nodes - a.nodes || a.label.localeCompare(b.label) : a.label.localeCompare(b.label));
  }, [clusters, query, sort]);

  const selected = clusters.find((cluster) => cluster.id === selectedId) ?? clusters[0] ?? null;
  const totalNodes = nodes.length;
  const donut = clusters.slice(0, 5).map((cluster) => ({ value: cluster.nodes, color: cluster.color, label: pretty(cluster.label) }));
  const remaining = clusters.slice(5).reduce((sum, cluster) => sum + cluster.nodes, 0);
  if (remaining > 0) donut.push({ value: remaining, color: "#8c949d", label: "Other Clusters" });

  const relationshipCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of edges) {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target || source.type === target.type) continue;
      const key = [source.type, target.type].sort().join("\u0000");
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [edges, nodeById]);

  const related = useMemo(() => {
    if (!selected) return [];
    const rows: { id: string; label: string; color: string; count: number; strength: number }[] = [];
    for (const cluster of clusters) {
      if (cluster.id === selected.id) continue;
      const key = [selected.id, cluster.id].sort().join("\u0000");
      const count = relationshipCounts.get(key) ?? 0;
      if (count > 0) rows.push({ id: cluster.id, label: pretty(cluster.label), color: cluster.color, count, strength: 0 });
    }
    const max = Math.max(1, ...rows.map((row) => row.count));
    return rows.sort((a, b) => b.count - a.count).slice(0, 6).map((row) => ({ ...row, strength: row.count / max }));
  }, [clusters, relationshipCounts, selected]);

  const selectedMembers = useMemo(() => {
    if (!selected) return [];
    return nodes
      .filter((node) => node.type === selected.id)
      .sort((a, b) => (degreeById.get(b.id) ?? 0) - (degreeById.get(a.id) ?? 0) || a.label.localeCompare(b.label));
  }, [degreeById, nodes, selected]);

  const visibleConcepts = showAllConcepts ? selectedMembers : selectedMembers.slice(0, 5);
  const visualClusters = useMemo(() => clusters.slice(0, 10), [clusters]);
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    if (visualClusters.length === 0) return map;
    const focusId = selected?.id ?? visualClusters[0].id;
    map.set(focusId, { x: visualClusters.length <= 3 ? 450 : 450, y: 205 });
    const others = visualClusters.filter((cluster) => cluster.id !== focusId);
    others.forEach((cluster, index) => {
      const angle = others.length === 2 ? (index === 0 ? Math.PI : 0) : (index / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
      map.set(cluster.id, { x: 450 + Math.cos(angle) * 300, y: 205 + Math.sin(angle) * 145 });
    });
    return map;
  }, [selected?.id, visualClusters]);

  const mapViewBox = useMemo(() => {
    const width = 900 / mapScale;
    const height = 410 / mapScale;
    return `${(900 - width) / 2 + mapOffset.x} ${(410 - height) / 2 + mapOffset.y} ${width} ${height}`;
  }, [mapScale, mapOffset]);
  const positionFor = (id: string) => draggedPositions.get(id) ?? positions.get(id);
  const mapPoint = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = mapRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: event.clientX * (900 / mapScale) / rect.width, y: event.clientY * (410 / mapScale) / rect.height };
  };
  const startDrag = (event: ReactPointerEvent<SVGSVGElement>, id: string | null) => {
    if (event.button !== 0) return;
    const point = mapPoint(event);
    const current = id ? positionFor(id) : mapOffset;
    dragRef.current = { pointerId: event.pointerId, id, x: current?.x ?? 0, y: current?.y ?? 0, startX: point.x, startY: point.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveDrag = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const point = mapPoint(event);
    const next = { x: drag.x + point.x - drag.startX, y: drag.y + point.y - drag.startY };
    if (drag.id) setDraggedPositions((previous) => new Map(previous).set(drag.id!, next));
    else setMapOffset(next);
  };
  const finishDrag = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
  };
  const wheelZoom = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setMapScale((value) => Math.max(0.6, Math.min(2.4, Number((value * (event.deltaY > 0 ? 0.9 : 1.1)).toFixed(2)))));
  };
  const stars = useMemo(() => Array.from({ length: 140 }, (_, index) => ({ x: hash(`star-x-${index}`) % 900, y: hash(`star-y-${index}`) % 410, r: index % 12 === 0 ? 1.5 : 0.6 })), []);

  const matrixClusters = clusters.slice(0, 6);
  const relationshipMatrix = useMemo(() => {
    let max = 1;
    const raw = matrixClusters.map((a) => matrixClusters.map((b) => {
      if (a.id === b.id) return a.internalEdges ?? 0;
      const value = relationshipCounts.get([a.id, b.id].sort().join("\u0000")) ?? 0;
      max = Math.max(max, value);
      return value;
    }));
    return raw.map((row) => row.map((value) => value / max));
  }, [matrixClusters, relationshipCounts]);

  const clusterDescription = selected
    ? `${formatCount(selected.nodes)} live Brain projection nodes grouped by ${pretty(selected.label)}. Relationships and concepts below are derived from the current /api/brain/graph projection.`
    : "No clusters available in the current Brain projection.";

  const zoomOut = () => setMapScale((value) => Math.max(0.6, Number((value - 0.1).toFixed(2))));
  const zoomIn = () => setMapScale((value) => Math.min(2.4, Number((value + 0.1).toFixed(2))));
  const resetZoom = () => { setMapScale(1); setMapOffset({ x: 0, y: 0 }); setDraggedPositions(new Map()); };
  const exploreStrongestRelationship = () => {
    const strongest = related[0];
    if (!strongest) {
      onToast?.("No inter-cluster relationships are available in this bounded projection.");
      return;
    }
    setSelectedId(strongest.id);
    setShowAllConcepts(false);
    onToast?.(`Focused related cluster: ${strongest.label}.`);
  };

  return (
    <div className="lv-bc lv-bc-ref">
      <div className="lv-bc-grid">
        <Panel title="Cluster Overview" className="lv-bc-overview">
          <div className="lv-bc-summary">
            <div><strong>{clusters.length}</strong><span>Total Clusters</span></div>
            <div><strong>{formatCount(totalNodes)}</strong><span>Total Nodes</span></div>
            <div><strong>{formatCount(edges.length)}</strong><span>Total Connections</span></div>
          </div>
          <div className="lv-bc-overview-tools">
            <label className="lv-bc-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search clusters..." aria-label="Search clusters" /></label>
            <select className="lv-br-select" value={sort} onChange={(event) => setSort(event.target.value as "size" | "name")}><option value="size">Sort by Size</option><option value="name">Sort by Name</option></select>
          </div>
          {list.length === 0 ? <p className="lv-br-muted">No clusters in the current projection.</p> : (
            <ul className="lv-bc-list">
              {list.map((cluster) => (
                <li key={cluster.id}><button type="button" className={`lv-bc-item${selected?.id === cluster.id ? " is-active" : ""}`} onClick={() => { setSelectedId(cluster.id); setShowAllConcepts(false); }}><span className="lv-bc-dot" style={{ background: cluster.color, boxShadow: `0 0 8px ${cluster.color}` }} /><span>{pretty(cluster.label)}</span><em>{formatCount(cluster.nodes)} nodes</em></button></li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="lv-bc-center">
          <Panel title="Cluster Visualization" className="lv-bc-viz" action={<span className="lv-bc-viz-subtitle">Knowledge organized into semantic clusters and their relationships</span>}>
            <div className="lv-bc-map">
              <div className="lv-bc-legend"><span><i />Strong Relationship</span><span><i className="is-moderate" />Moderate Relationship</span><span><i className="is-weak" />Weak Relationship</span></div>
              <svg ref={mapRef} className="lv-bc-links" viewBox={mapViewBox} preserveAspectRatio="xMidYMid meet" aria-label="Interactive cluster relationship network" onPointerDown={(event) => startDrag(event, (event.target as Element).closest("[data-cluster-id]")?.getAttribute("data-cluster-id") ?? null)} onPointerMove={moveDrag} onPointerUp={finishDrag} onPointerCancel={finishDrag} onWheel={wheelZoom}>
                <defs>{visualClusters.map((cluster) => <filter key={cluster.id} id={`cluster-glow-${hash(cluster.id)}`} x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="7" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>)}<radialGradient id="lv-bc-stellar-haze"><stop stopColor="#ac7e49" stopOpacity=".17" /><stop offset=".5" stopColor="#316387" stopOpacity=".07" /><stop offset="1" stopColor="#020608" stopOpacity="0" /></radialGradient></defs>
                <ellipse cx="450" cy="205" rx="480" ry="270" fill="url(#lv-bc-stellar-haze)" pointerEvents="none" />
                <g pointerEvents="none">{stars.map((star, index) => <circle key={index} cx={star.x} cy={star.y} r={star.r} fill={index % 3 === 0 ? "#e7ba72" : "#99d2ed"} opacity={index % 11 === 0 ? ".55" : ".22"} />)}</g>
                {visualClusters.flatMap((source, sourceIndex) => visualClusters.slice(sourceIndex + 1).map((target) => {
                  const count = relationshipCounts.get([source.id, target.id].sort().join("\u0000")) ?? 0;
                  if (!count) return null;
                  const a = positionFor(source.id); const b = positionFor(target.id);
                  if (!a || !b) return null;
                  const maxRelationship = Math.max(1, ...relationshipCounts.values());
                  const ratio = count / maxRelationship;
                  return <line key={`${source.id}:${target.id}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(177,188,207,.48)" strokeWidth={0.6 + ratio * 2} strokeDasharray={ratio < 0.35 ? "2 7" : ratio < 0.7 ? "6 5" : undefined} />;
                }))}
                {visualClusters.map((cluster) => {
                  const point = positionFor(cluster.id); if (!point) return null;
                  const active = selected?.id === cluster.id;
                  const radius = active ? 45 : 35 + Math.min(10, Math.sqrt(cluster.nodes) * 2);
                  const particles = Array.from({ length: Math.min(45, Math.max(14, Math.round(Math.sqrt(cluster.nodes) * 4))) }, (_, index) => {
                    const seed = hash(`${cluster.id}:${index}`);
                    const angle = ((seed % 360) / 180) * Math.PI;
                    const distance = radius + 16 + (seed % 54);
                    return { x: Math.cos(angle) * distance, y: Math.sin(angle) * distance * 0.82, r: 0.8 + seed % 3 };
                  });
                  return <g key={cluster.id} data-cluster-id={cluster.id} className={`lv-bc-orbit${active ? " is-active" : ""}`} transform={`translate(${point.x} ${point.y})`} onClick={() => { setSelectedId(cluster.id); setShowAllConcepts(false); }} style={{ cursor: "grab" }}>
                    {particles.map((particle, index) => <g key={index} pointerEvents="none"><line x1={0} y1={0} x2={particle.x} y2={particle.y} stroke={cluster.color} strokeOpacity=".14" strokeWidth=".45" /><circle cx={particle.x} cy={particle.y} r={particle.r} fill={cluster.color} opacity={0.44 + (index % 4) * 0.12} /></g>)}
                    <circle r={radius + 19} fill={cluster.color} opacity=".025" stroke={cluster.color} strokeOpacity=".2" strokeDasharray="2 6" />
                    <circle r={radius} fill="rgba(4,8,12,.92)" stroke={cluster.color} strokeWidth={active ? 2.2 : 1.5} filter={`url(#cluster-glow-${hash(cluster.id)})`} />
                    <circle cy="-14" r="5" fill={cluster.color} />
                    <text y="4" textAnchor="middle" className="lv-bc-map-label"><tspan x="0">{pretty(cluster.label).split(" ").slice(0, 2).join(" ")}</tspan><tspan x="0" dy="13">{pretty(cluster.label).split(" ").slice(2).join(" ")}</tspan></text>
                  </g>;
                })}
              </svg>
              <div className="lv-bc-map-controls" aria-label="Cluster map zoom controls"><button type="button" onClick={zoomOut} aria-label="Zoom out">−</button><span>{Math.round(mapScale * 100)}%</span><button type="button" onClick={zoomIn} aria-label="Zoom in">＋</button><button type="button" onClick={resetZoom} aria-label="Reset zoom">⌗</button></div>
            </div>
          </Panel>

          <div className="lv-bc-bottom">
            <Panel title="Cluster Distribution" className="lv-bc-mini-panel">
              <div className="lv-bc-donut-wrap"><Donut slices={donut} center={`${formatCount(totalNodes)}\nNodes`} size={105} /><ul className="lv-bc-donut-legend">{donut.map((slice) => <li key={slice.label}><span className="lv-bc-dot" style={{ background: slice.color }} /><span title={slice.label}>{slice.label}</span><em>{totalNodes ? ((slice.value / totalNodes) * 100).toFixed(1) : "0.0"}%</em></li>)}</ul></div>
            </Panel>
            <Panel title="Inter-Cluster Relationships" className="lv-bc-mini-panel"><Heatmap grid={relationshipMatrix} rowLabels={matrixClusters.map((cluster) => pretty(cluster.label).slice(0, 7))} colLabels={matrixClusters.map((cluster) => pretty(cluster.label).slice(0, 3))} /></Panel>
            <Panel title="Cluster Size Distribution" className="lv-bc-mini-panel"><div className="lv-bc-bars">{clusters.slice(0, 12).map((cluster) => { const max = Math.max(1, ...clusters.map((item) => item.nodes)); return <div key={cluster.id} className="lv-bc-bar-col"><div className="lv-bc-bar" style={{ height: `${Math.max(7, (cluster.nodes / max) * 100)}%`, background: cluster.color, boxShadow: `0 0 8px ${cluster.color}66` }} /><span>{pretty(cluster.label).slice(0, 4)}</span></div>; })}</div></Panel>
          </div>
        </div>

        <Panel title="Cluster Details" className="lv-bc-detail">
          {!selected ? <p className="lv-br-muted">Select a cluster.</p> : <>
            <div className="lv-bc-detail-head"><div className="lv-bc-detail-icon" style={{ borderColor: selected.color, color: selected.color, boxShadow: `0 0 18px ${selected.color}55` }}>⌘</div><div><h3>{pretty(selected.label)}</h3><span className="lv-br-badge" style={{ borderColor: `${selected.color}88`, color: selected.color }}>Live Cluster</span></div></div>
            <p className="lv-br-desc">{clusterDescription}</p>
            <div className="lv-bc-metrics"><div><strong>{formatCount(selected.nodes)}</strong><span>Nodes</span></div><div><strong>{formatCount(selected.internalEdges ?? 0)}</strong><span>Internal</span></div><div><strong>{related.length}</strong><span>Related</span></div></div>
            <section className="lv-bc-section"><strong>Top Concepts</strong><ul>{visibleConcepts.map((node, index) => <li key={node.id}><span className="lv-bc-rank" style={{ color: selected.color }}>{index + 1}</span><span title={node.id}>{node.label}</span><em>{degreeById.get(node.id) ?? 0}</em></li>)}</ul>{selectedMembers.length > 5 ? <button type="button" className="lv-bc-wide-action" onClick={() => setShowAllConcepts((value) => !value)}>{showAllConcepts ? "Show Top Concepts ↑" : `View All Concepts (${selectedMembers.length}) →`}</button> : null}</section>
            <section className="lv-bc-section lv-bc-related"><strong>Related Clusters</strong><ul>{related.length ? related.map((row) => <li key={row.id}><button type="button" className="lv-bc-related-row" onClick={() => { setSelectedId(row.id); setShowAllConcepts(false); }}><div><span><i className="lv-bc-dot" style={{ background: row.color }} />{row.label}</span><em>{row.count}</em></div><div className="lv-br-bar"><span style={{ width: `${Math.max(8, row.strength * 100)}%`, background: row.color }} /></div></button></li>) : <li className="lv-br-muted">No inter-cluster edges in this bounded projection.</li>}</ul><button type="button" className="lv-bc-wide-action" onClick={exploreStrongestRelationship} disabled={!related.length}>Explore Strongest Relationship →</button></section>
          </>}
        </Panel>
      </div>
    </div>
  );
}
