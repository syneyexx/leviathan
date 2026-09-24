import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import { colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";

type Point = { x: number; y: number };
type Viewport = { x: number; y: number; scale: number };
type PositionedNode = LiveBrainNode & Point & { r: number; color: string; cluster: string; core: boolean };
type ClusterLayout = { type: string; label: string; color: string; x: number; y: number; count: number; radius: number };

type Props = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  showLabels: boolean;
  showClusters: boolean;
  showDepth: boolean;
  physicsLayout: boolean;
};

const WIDTH = 1000;
const HEIGHT = 610;
const CENTER: Point = { x: WIDTH / 2, y: HEIGHT / 2 };

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function prettyType(type: string): string {
  return type
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => part.length <= 3 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function clusterKey(node: LiveBrainNode): string {
  if (node.type === "capability" && typeof node.meta?.provider_kind === "string" && node.meta.provider_kind.trim()) {
    return `capability.${node.meta.provider_kind.trim().toLowerCase()}`;
  }
  return node.type;
}

function clusterColor(key: string, sample: LiveBrainNode): string {
  const base = colorForType(sample.type);
  if (!key.startsWith("capability.")) return base;
  const capabilityPalette = ["#E6A13A", "#F0C875", "#E8794A", "#38C9D6", "#8D6EF4", "#42C58A"];
  return capabilityPalette[hashString(key) % capabilityPalette.length];
}

function buildLayout(nodes: LiveBrainNode[], edges: LiveBrainEdge[], physics: boolean): PositionedNode[] {
  if (nodes.length === 0) return [];

  const groups = new Map<string, LiveBrainNode[]>();
  for (const node of nodes) {
    const key = clusterKey(node);
    const group = groups.get(key) ?? [];
    group.push(node);
    groups.set(key, group);
  }

  const groupEntries = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  const actualHub = nodes.find((node) => /leviathan/i.test(node.label)) ?? nodes.find((node) => node.type === "atlas") ?? null;
  const positioned: PositionedNode[] = [];

  groupEntries.forEach(([key, group], groupIndex) => {
    const color = clusterColor(key, group[0]);
    const includesHub = actualHub ? group.some((node) => node.id === actualHub.id) : false;
    const nonHubIndex = includesHub ? Math.max(0, groupIndex - 1) : groupIndex;
    const nonHubCount = Math.max(1, groupEntries.length - (actualHub ? 1 : 0));
    const angle = (nonHubIndex / nonHubCount) * Math.PI * 2 - Math.PI / 2;
    const orbit = 258 + (groupIndex % 2) * 20;
    const groupCenter = includesHub
      ? CENTER
      : { x: CENTER.x + Math.cos(angle) * orbit, y: CENTER.y + Math.sin(angle) * orbit * 0.72 };

    group.forEach((node, index) => {
      if (actualHub && node.id === actualHub.id) {
        positioned.push({ ...node, ...CENTER, r: 34, color: "#E6BD58", cluster: key, core: true });
        return;
      }
      const seed = hashString(node.id);
      // A golden-angle spiral spreads large document collections across the
      // cluster instead of stacking every fourth node on the same ring.
      const localAngle = index * 2.399963229728653 + (seed % 29) * 0.014;
      const localRadius = index === 0 ? 0 : 27 + Math.sqrt(index) * 14;
      positioned.push({
        ...node,
        x: groupCenter.x + Math.cos(localAngle) * localRadius,
        y: groupCenter.y + Math.sin(localAngle) * localRadius * 0.82,
        r: index === 0 ? Math.min(24, 13 + Math.sqrt(group.length) * 2.4) : 4.5 + Math.min(3, Math.log2(index + 2) * 0.7),
        color,
        cluster: key,
        core: false,
      });
    });
  });

  if (!physics || positioned.length > 500) return positioned;

  const byId = new Map(positioned.map((node) => [node.id, node]));
  for (let iteration = 0; iteration < 28; iteration += 1) {
    for (const edge of edges) {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b || a.core || b.core) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = a.cluster === b.cluster ? 80 : 165;
      const force = (distance - desired) * 0.009;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      a.x += fx;
      a.y += fy;
      b.x -= fx;
      b.y -= fy;
    }
    for (const node of positioned) {
      if (node.core) continue;
      node.x += (CENTER.x - node.x) * 0.0007;
      node.y += (CENTER.y - node.y) * 0.0007;
      node.x = Math.max(35, Math.min(WIDTH - 35, node.x));
      node.y = Math.max(35, Math.min(HEIGHT - 35, node.y));
    }
    // Collision separation also works for unconnected nodes. The live graph
    // can contain hundreds of isolated documents with no edges to repel them.
    for (let aIndex = 0; aIndex < positioned.length; aIndex += 1) {
      const a = positioned[aIndex];
      for (let bIndex = aIndex + 1; bIndex < positioned.length; bIndex += 1) {
        const b = positioned[bIndex];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.hypot(dx, dy);
        const minimum = a.r + b.r + (a.core || b.core ? 25 : 13);
        if (distance >= minimum) continue;
        const angle = distance < 0.001 ? (hashString(a.id + b.id) % 360) * Math.PI / 180 : Math.atan2(dy, dx);
        const displacement = (minimum - distance) * 0.45;
        if (!a.core) { a.x -= Math.cos(angle) * displacement; a.y -= Math.sin(angle) * displacement; }
        if (!b.core) { b.x += Math.cos(angle) * displacement; b.y += Math.sin(angle) * displacement; }
      }
    }
  }
  return positioned;
}

export function BrainGraphCanvas({ nodes, edges, selectedId, onSelect, showLabels, showClusters, showDepth, physicsLayout }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ id: string; pointerId: number } | null>(null);
  const panRef = useRef<{ pointerId: number; clientX: number; clientY: number; x: number; y: number } | null>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, scale: 1 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const initial = useMemo(() => buildLayout(nodes, edges, physicsLayout), [nodes, edges, physicsLayout]);
  const [positions, setPositions] = useState<Map<string, Point>>(() => new Map(initial.map((node) => [node.id, { x: node.x, y: node.y }])));

  useEffect(() => {
    setPositions(new Map(initial.map((node) => [node.id, { x: node.x, y: node.y }])));
  }, [initial]);

  const rendered = useMemo<PositionedNode[]>(() => initial.map((node) => ({ ...node, ...(positions.get(node.id) ?? { x: node.x, y: node.y }) })), [initial, positions]);
  const byId = useMemo(() => new Map(rendered.map((node) => [node.id, node])), [rendered]);
  const hasActualCore = rendered.some((node) => node.core);
  const hovered = hoveredId ? byId.get(hoveredId) : null;
  const denseGraph = rendered.length > 45;
  const stars = useMemo(() => Array.from({ length: 170 }, (_, index) => ({
    x: hashString(`brain-star-x-${index}`) % WIDTH,
    y: hashString(`brain-star-y-${index}`) % HEIGHT,
    radius: index % 13 === 0 ? 1.35 : 0.45,
    opacity: index % 11 === 0 ? 0.56 : 0.18,
  })), []);

  const connectedToSelected = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedId) return ids;
    ids.add(selectedId);
    for (const edge of edges) {
      if (edge.source === selectedId) ids.add(edge.target);
      if (edge.target === selectedId) ids.add(edge.source);
    }
    return ids;
  }, [edges, selectedId]);

  const clusters = useMemo<ClusterLayout[]>(() => {
    const map = new Map<string, ClusterLayout>();
    for (const node of rendered) {
      if (node.core) continue;
      const row = map.get(node.cluster) ?? { type: node.cluster, label: prettyType(node.cluster), color: node.color, x: 0, y: 0, count: 0, radius: 42 };
      row.x += node.x;
      row.y += node.y;
      row.count += 1;
      map.set(node.cluster, row);
    }
    return [...map.values()].map((row) => ({ ...row, x: row.x / Math.max(1, row.count), y: row.y / Math.max(1, row.count), radius: Math.min(112, 38 + Math.sqrt(row.count) * 11) }));
  }, [rendered]);

  const pointInGraph = (clientX: number, clientY: number): Point | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const svgX = ((clientX - rect.left) / rect.width) * WIDTH;
    const svgY = ((clientY - rect.top) / rect.height) * HEIGHT;
    return { x: (svgX - viewport.x) / viewport.scale, y: (svgY - viewport.y) / viewport.scale };
  };

  const handleNodePointerDown = (event: ReactPointerEvent<SVGGElement>, id: string) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { id, pointerId: event.pointerId };
    onSelect(id);
  };

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panRef.current = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, x: viewport.x, y: viewport.y };
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      const point = pointInGraph(event.clientX, event.clientY);
      if (!point) return;
      setPositions((previous) => {
        const next = new Map(previous);
        next.set(dragRef.current!.id, point);
        return next;
      });
      return;
    }
    if (panRef.current?.pointerId === event.pointerId) {
      const rect = event.currentTarget.getBoundingClientRect();
      const dx = (event.clientX - panRef.current.clientX) * (WIDTH / Math.max(rect.width, 1));
      const dy = (event.clientY - panRef.current.clientY) * (HEIGHT / Math.max(rect.height, 1));
      setViewport((previous) => ({ ...previous, x: panRef.current!.x + dx, y: panRef.current!.y + dy }));
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    if (panRef.current?.pointerId === event.pointerId) panRef.current = null;
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    setViewport((previous) => ({ ...previous, scale: Math.max(0.45, Math.min(2.5, previous.scale * factor)) }));
  };

  const zoomBy = (factor: number) => setViewport((previous) => ({ ...previous, scale: Math.max(0.45, Math.min(2.5, previous.scale * factor)) }));
  const reset = () => setViewport({ x: 0, y: 0, scale: 1 });

  return (
    <div className="lv-gv-stage">
      <div className="lv-gv-controls" aria-label="Graph viewport controls">
        <button type="button" onClick={() => zoomBy(0.86)} aria-label="Zoom out">−</button>
        <span>{Math.round(viewport.scale * 100)}%</span>
        <button type="button" onClick={() => zoomBy(1.16)} aria-label="Zoom in">+</button>
        <button type="button" onClick={reset} aria-label="Fit graph">⌗</button>
      </div>
      <svg
        ref={svgRef}
        className="lv-gv-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
        aria-label="Interactive LEVIATHAN knowledge graph"
      >
        <defs>
          <filter id="lv-gv-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <filter id="lv-gv-soft-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="8" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <radialGradient id="lv-gv-core" cx="50%" cy="45%" r="60%"><stop offset="0%" stopColor="#33250e" /><stop offset="70%" stopColor="#0b0c0b" /><stop offset="100%" stopColor="#040605" /></radialGradient>
          <radialGradient id="lv-gv-nebula"><stop offset="0%" stopColor="#866135" stopOpacity=".16" /><stop offset="42%" stopColor="#263a45" stopOpacity=".075" /><stop offset="100%" stopColor="#030708" stopOpacity="0" /></radialGradient>
        </defs>
        <rect width={WIDTH} height={HEIGHT} fill="transparent" />
        <g className="lv-gv-stars" pointerEvents="none">
          <ellipse cx="510" cy="314" rx="505" ry="340" fill="url(#lv-gv-nebula)" />
          {stars.map((star, index) => <circle key={index} cx={star.x} cy={star.y} r={star.radius} fill={index % 4 === 0 ? "#dcb977" : "#bad4de"} opacity={star.opacity} />)}
        </g>
        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          {showClusters ? (
            <g className="lv-gv-scaffold" pointerEvents="none">
              {!hasActualCore ? clusters.map((cluster) => <line key={`spoke:${cluster.type}`} x1={CENTER.x} y1={CENTER.y} x2={cluster.x} y2={cluster.y} stroke={cluster.color} strokeOpacity=".13" strokeWidth="1" strokeDasharray="2 7" />) : null}
              {clusters.map((cluster) => (
                <g key={cluster.type} className="lv-gv-cluster-halo">
                  <circle cx={cluster.x} cy={cluster.y} r={cluster.radius} fill={cluster.color} opacity=".025" stroke={cluster.color} strokeOpacity=".12" strokeDasharray="3 9" />
                  <circle cx={cluster.x} cy={cluster.y} r="14" fill="rgba(3,8,9,.94)" stroke={cluster.color} strokeOpacity=".72" filter="url(#lv-gv-glow)" />
                  <circle cx={cluster.x} cy={cluster.y} r="3.5" fill={cluster.color} />
                  <text x={cluster.x} y={cluster.y + 26} textAnchor="middle" fill={cluster.color} opacity=".84">{cluster.label}</text>
                </g>
              ))}
            </g>
          ) : null}

          {!hasActualCore ? (
            <g className="lv-gv-visual-core" pointerEvents="none" transform={`translate(${CENTER.x} ${CENTER.y})`}>
              <circle r="53" fill="none" stroke="#E6BD58" strokeOpacity=".13" strokeDasharray="2 8" filter="url(#lv-gv-soft-glow)" />
              <circle r="38" fill="url(#lv-gv-core)" stroke="#E6BD58" strokeWidth="2" filter="url(#lv-gv-glow)" />
              <circle r="7" fill="#E6BD58" />
              <text y="4" textAnchor="middle" className="lv-gv-core-mark">L</text>
              <text y="58" textAnchor="middle" className="lv-gv-label is-core">LEVIATHAN</text>
            </g>
          ) : null}

          <g className="lv-gv-links">
            {edges.map((edge) => {
              const source = byId.get(edge.source);
              const target = byId.get(edge.target);
              if (!source || !target) return null;
              const active = selectedId != null && (edge.source === selectedId || edge.target === selectedId);
              return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={active ? "is-active" : ""} stroke={active ? source.color : "rgba(192,170,112,.28)"} strokeWidth={active ? 1.7 : 0.72} opacity={active ? 0.92 : 0.66}><title>{edge.relation}</title></line>;
            })}
          </g>

          {rendered.map((node) => {
            const selected = selectedId === node.id;
            const hoveredNode = hoveredId === node.id;
            const depthDimmed = showDepth && selectedId != null && !connectedToSelected.has(node.id);
            const labelVisible = showLabels && (node.core || hoveredNode || (!denseGraph && node.label.length <= 22) || (denseGraph && node.r >= 19 && node.label.length <= 18));
            return (
              <g key={node.id} className={`lv-gv-node${node.core ? " is-core" : ""}${selected ? " is-selected" : ""}${depthDimmed ? " is-depth-dimmed" : ""}`} transform={`translate(${node.x} ${node.y})`} onPointerEnter={() => setHoveredId(node.id)} onPointerLeave={() => setHoveredId((current) => current === node.id ? null : current)} onFocus={() => setHoveredId(node.id)} onBlur={() => setHoveredId((current) => current === node.id ? null : current)} tabIndex={0} role="button" aria-label={`${node.label}, ${prettyType(node.type)}`} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(node.id); } }} onPointerDown={(event) => handleNodePointerDown(event, node.id)} onClick={(event) => { event.stopPropagation(); onSelect(node.id); }} style={{ color: node.color }}>
                {node.core ? <circle r={node.r + 16} fill="none" stroke={node.color} strokeOpacity=".2" filter="url(#lv-gv-soft-glow)" /> : null}
                <circle r={selected ? node.r + 3 : node.r} fill={node.core ? "url(#lv-gv-core)" : "rgba(3,8,9,.94)"} stroke="currentColor" strokeWidth={node.core ? 2.2 : selected ? 2 : 1.15} filter={node.core || selected ? "url(#lv-gv-glow)" : undefined} />
                <circle r={node.core ? 7 : Math.max(2.4, node.r * 0.27)} fill="currentColor" opacity={node.core ? 0.95 : 0.86} />
                {node.core ? <text y="4" textAnchor="middle" className="lv-gv-core-mark">L</text> : null}
                {labelVisible && node.label.length <= 22 ? <text y={node.r + 13} textAnchor="middle" className={node.core ? "lv-gv-label is-core" : "lv-gv-label"}>{node.label}</text> : null}
                <title>{`${node.label} · ${node.type}`}</title>
              </g>
            );
          })}
        </g>
      </svg>
      {hovered ? <div className="lv-gv-hover-card" role="tooltip" style={{ left: `${((hovered.x * viewport.scale + viewport.x) / WIDTH) * 100}%`, top: `${((hovered.y * viewport.scale + viewport.y) / HEIGHT) * 100}%` }}><strong>{hovered.label}</strong><span>{prettyType(hovered.type)}</span></div> : null}
      <div className="lv-gv-legend" aria-hidden="true">
        {[...new Map(nodes.map((node) => [node.type, colorForType(node.type)])).entries()].slice(0, 10).map(([type, color]) => <span key={type}><i style={{ background: color }} />{prettyType(type)}</span>)}
      </div>
    </div>
  );
}
