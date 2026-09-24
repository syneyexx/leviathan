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

const BASE_WIDTH = 1000;
const BASE_HEIGHT = 610;

function graphSize(count: number): { width: number; height: number } {
  const expansion = Math.max(0, Math.sqrt(count) - 6);
  return { width: BASE_WIDTH + expansion * 165, height: BASE_HEIGHT + expansion * 115 };
}

function NodeGlyph({ type, core, radius }: { type: string; core: boolean; radius: number }) {
  const kind = core ? "core" : type.toLowerCase();
  const size = Math.min(13, Math.max(3.8, radius * 0.67));
  const shared = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  let glyph;
  if (kind === "core" || kind === "module") glyph = <><path d="M0 -8 7 -4 7 4 0 8 -7 4 -7 -4Z" /><path d="M0 -8V0L7 4M0 0-7 4" /></>;
  else if (kind === "dataset") glyph = <><ellipse cx="0" cy="-5" rx="7" ry="3" /><path d="M-7 -5V5C-7 9 7 9 7 5V-5M-7 0C-7 4 7 4 7 0" /></>;
  else if (kind === "knowledge.document" || kind === "memory") glyph = <><path d="M-6 -8H3L7 -4V8H-6Z" /><path d="M3 -8V-4H7M-3 0H4M-3 4H4" /></>;
  else if (kind === "capability" || kind === "tool" || kind.startsWith("mcp.")) glyph = <><path d="M-5 -7H5V7H-5Z M-8 -3H-5M-8 3H-5M5 -3H8M5 3H8M-3 -10V-7M3 -10V-7M-3 7V10M3 7V10" /><circle cx="0" cy="0" r="2" /></>;
  else if (kind === "agent") glyph = <><circle cy="-4" r="3" /><path d="M-7 7C-7 0 7 0 7 7" /></>;
  else if (kind === "workflow" || kind === "run") glyph = <><circle cx="-6" cy="-5" r="2" /><circle cx="6" cy="0" r="2" /><circle cx="-6" cy="6" r="2" /><path d="M-4 -5H0V0H4M0 0V6H-4" /></>;
  else if (kind === "research.project" || kind === "project") glyph = <><circle cy="-1" r="6" /><path d="M4 4 9 9M-3 -1H3M0 -4V2" /></>;
  else if (kind === "evidence") glyph = <><path d="M0 -9 7 -5V0C7 5 3 8 0 9-3 8-7 5-7 0V-5Z" /><path d="m-3 0 2 2 4-4" /></>;
  else if (kind === "model" || kind === "concept") glyph = <><circle cx="-5" cy="-3" r="2" /><circle cx="5" cy="-3" r="2" /><circle cy="6" r="2" /><path d="M-3 -3H3M-4 -1-1 4M4 -1 1 4" /></>;
  else glyph = <><circle r="5" /><path d="M-8 0H8M0 -8V8" /></>;
  return <g {...shared} pointerEvents="none" transform={`scale(${size / 10})`}>{glyph}</g>;
}

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

function buildLayout(nodes: LiveBrainNode[], edges: LiveBrainEdge[], physics: boolean, width: number, height: number): PositionedNode[] {
  if (nodes.length === 0) return [];
  const center = { x: width / 2, y: height / 2 };

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
    const orbit = Math.min(width, height) * (groupEntries.length < 3 ? 0.27 : 0.34);
    const groupCenter = includesHub
      ? center
      : { x: center.x + Math.cos(angle) * orbit, y: center.y + Math.sin(angle) * orbit * 0.78 };

    group.forEach((node, index) => {
      if (actualHub && node.id === actualHub.id) {
        positioned.push({ ...node, ...center, r: 34, color: "#E6BD58", cluster: key, core: true });
        return;
      }
      const seed = hashString(node.id);
      // A golden-angle spiral spreads large document collections across the
      // cluster instead of stacking every fourth node on the same ring.
      const localAngle = index * 2.399963229728653 + (seed % 29) * 0.014;
      const localRadius = index === 0 ? 0 : 42 + Math.sqrt(index) * 25;
      positioned.push({
        ...node,
        x: groupCenter.x + Math.cos(localAngle) * localRadius,
        y: groupCenter.y + Math.sin(localAngle) * localRadius,
        r: index === 0 ? Math.min(26, 14 + Math.sqrt(group.length) * 2.4) : 7 + Math.min(3, Math.log2(index + 2) * 0.65),
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
      const desired = a.cluster === b.cluster ? 115 : 280;
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
      node.x += (center.x - node.x) * 0.00015;
      node.y += (center.y - node.y) * 0.00015;
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
        const minimum = a.r + b.r + (a.core || b.core ? 48 : 26);
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
  const { width, height } = useMemo(() => graphSize(nodes.length), [nodes.length]);
  const center = useMemo(() => ({ x: width / 2, y: height / 2 }), [width, height]);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ id: string; pointerId: number } | null>(null);
  const panRef = useRef<{ pointerId: number; clientX: number; clientY: number; x: number; y: number } | null>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, scale: 1 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const initial = useMemo(() => buildLayout(nodes, edges, physicsLayout, width, height), [nodes, edges, physicsLayout, width, height]);
  const [positions, setPositions] = useState<Map<string, Point>>(() => new Map(initial.map((node) => [node.id, { x: node.x, y: node.y }])));

  useEffect(() => {
    setPositions(new Map(initial.map((node) => [node.id, { x: node.x, y: node.y }])));
  }, [initial]);

  useEffect(() => {
    const scale = nodes.length > 80 ? Math.min(2.2, Math.sqrt(nodes.length) / 7) : 1;
    setViewport({ x: center.x * (1 - scale), y: center.y * (1 - scale), scale });
  }, [center, nodes.length]);

  const rendered = useMemo<PositionedNode[]>(() => initial.map((node) => ({ ...node, ...(positions.get(node.id) ?? { x: node.x, y: node.y }) })), [initial, positions]);
  const byId = useMemo(() => new Map(rendered.map((node) => [node.id, node])), [rendered]);
  const hasActualCore = rendered.some((node) => node.core);
  const hovered = hoveredId ? byId.get(hoveredId) : null;
  const denseGraph = rendered.length > 45;
  const stars = useMemo(() => Array.from({ length: 170 }, (_, index) => ({
    x: hashString(`brain-star-x-${index}`) % width,
    y: hashString(`brain-star-y-${index}`) % height,
    radius: index % 13 === 0 ? 1.35 : 0.45,
    opacity: index % 11 === 0 ? 0.56 : 0.18,
  })), [width, height]);

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
    const svgX = ((clientX - rect.left) / rect.width) * width;
    const svgY = ((clientY - rect.top) / rect.height) * height;
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
      const draggedId = dragRef.current.id;
      setPositions((previous) => {
        const next = new Map(previous);
        next.set(draggedId, point);
        return next;
      });
      return;
    }
    if (panRef.current?.pointerId === event.pointerId) {
      const pan = panRef.current;
      const rect = event.currentTarget.getBoundingClientRect();
      const dx = (event.clientX - pan.clientX) * (width / Math.max(rect.width, 1));
      const dy = (event.clientY - pan.clientY) * (height / Math.max(rect.height, 1));
      setViewport((previous) => ({ ...previous, x: pan.x + dx, y: pan.y + dy }));
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    if (panRef.current?.pointerId === event.pointerId) panRef.current = null;
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    const rect = event.currentTarget.getBoundingClientRect();
    const cursor = { x: (event.clientX - rect.left) / rect.width * width, y: (event.clientY - rect.top) / rect.height * height };
    setViewport((previous) => {
      const scale = Math.max(0.45, Math.min(3.5, previous.scale * factor));
      const ratio = scale / previous.scale;
      return { x: cursor.x - (cursor.x - previous.x) * ratio, y: cursor.y - (cursor.y - previous.y) * ratio, scale };
    });
  };

  const zoomBy = (factor: number) => setViewport((previous) => {
    const scale = Math.max(0.45, Math.min(3.5, previous.scale * factor));
    const ratio = scale / previous.scale;
    return { x: center.x - (center.x - previous.x) * ratio, y: center.y - (center.y - previous.y) * ratio, scale };
  });
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
        viewBox={`0 0 ${width} ${height}`}
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
        <rect width={width} height={height} fill="transparent" />
        <g className="lv-gv-stars" pointerEvents="none">
          <ellipse cx={center.x} cy={center.y} rx={width * .53} ry={height * .55} fill="url(#lv-gv-nebula)" />
          {stars.map((star, index) => <circle key={index} cx={star.x} cy={star.y} r={star.radius} fill={index % 4 === 0 ? "#dcb977" : "#bad4de"} opacity={star.opacity} />)}
        </g>
        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          {showClusters ? (
            <g className="lv-gv-scaffold" pointerEvents="none">
              {!hasActualCore ? clusters.map((cluster) => <line key={`spoke:${cluster.type}`} x1={center.x} y1={center.y} x2={cluster.x} y2={cluster.y} stroke={cluster.color} strokeOpacity=".13" strokeWidth="1" strokeDasharray="2 7" />) : null}
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
            <g className="lv-gv-visual-core" pointerEvents="none" transform={`translate(${center.x} ${center.y})`}>
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
                <NodeGlyph type={node.type} core={node.core} radius={node.r} />
                {labelVisible && node.label.length <= 22 ? <text y={node.r + 13} textAnchor="middle" className={node.core ? "lv-gv-label is-core" : "lv-gv-label"}>{node.label}</text> : null}
                <title>{`${node.label} · ${node.type}`}</title>
              </g>
            );
          })}
        </g>
      </svg>
      {hovered ? <div className="lv-gv-hover-card" role="tooltip" style={{ left: `${((hovered.x * viewport.scale + viewport.x) / width) * 100}%`, top: `${((hovered.y * viewport.scale + viewport.y) / height) * 100}%` }}><strong>{hovered.label}</strong><span>{prettyType(hovered.type)}</span></div> : null}
      <div className="lv-gv-legend" aria-hidden="true">
        {[...new Map(nodes.map((node) => [node.type, colorForType(node.type)])).entries()].slice(0, 10).map(([type, color]) => <span key={type}><i style={{ background: color }} />{prettyType(type)}</span>)}
      </div>
    </div>
  );
}
