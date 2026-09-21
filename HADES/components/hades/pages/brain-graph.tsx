import { useMemo, useRef } from "react";
import { Crosshair, Maximize2, Minus, Plus, ZoomIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrainNodeIcon } from "./brain-node-icon";
import { KIND_LABELS, ZOOM_MAX, ZOOM_MIN, clamp } from "./brain-graph-adapter";
import type { DragState, GraphLink, GraphNode, NodeKind, Viewport } from "./brain-graph-adapter";
import { useBrainNodeDetail } from "./use-brain-node-detail";

type BrainGraphProps = {
  nodes: GraphNode[];
  links: GraphLink[];
  visibleNodes: GraphNode[];
  visibleLinks: GraphLink[];
  selectedId: string;
  hoveredId: string | null;
  viewport: Viewport;
  drag: DragState;
  viewMode: string;
  kindFilter: NodeKind | "all";
  surfaceRef: React.RefObject<HTMLDivElement | null>;
  svgRef: React.RefObject<SVGSVGElement | null>;
  onWheel: React.WheelEventHandler<SVGSVGElement>;
  onSurfacePointerDown: React.PointerEventHandler<SVGSVGElement>;
  onPointerMove: React.PointerEventHandler<SVGSVGElement>;
  onPointerEnd: React.PointerEventHandler<SVGSVGElement>;
  onNodePointerDown: (event: React.PointerEvent<SVGGElement>, node: GraphNode) => void;
  onSelectNode: (id: string) => void;
  onHoverNode: (id: string | null) => void;
  onZoom: (zoom: number) => void;
  onResetView: () => void;
  onFitView: () => void;
  onFullscreen: () => void;
  onLegendFilter: (kind: NodeKind) => void;
};

type NodePointerStart = {
  pointerId: number;
  nodeId: string;
  clientX: number;
  clientY: number;
};

const COSMIC_STARS = Array.from({ length: 150 }, (_, index) => ({
  id: `star-${index}`,
  x: (index * 83 + (index % 7) * 29) % 1000,
  y: (index * 47 + (index % 11) * 31) % 650,
  r: index % 17 === 0 ? 1.8 : index % 5 === 0 ? 1.15 : 0.7,
  opacity: 0.22 + ((index * 13) % 55) / 100,
  delay: `${(index % 12) * 0.23}s`,
}));

const CLUSTER_TONES = ["mint", "blue", "rose", "amber", "violet", "sky", "stone"] as const;
const MAX_DECORATED_NODES = 180;
const NODE_CLICK_TOLERANCE_PX = 6;

export function BrainGraph({
  nodes,
  links,
  visibleNodes,
  visibleLinks,
  selectedId,
  hoveredId,
  viewport,
  drag,
  viewMode,
  kindFilter,
  surfaceRef,
  svgRef,
  onWheel,
  onSurfacePointerDown,
  onPointerMove,
  onPointerEnd,
  onNodePointerDown,
  onSelectNode,
  onHoverNode,
  onZoom,
  onResetView,
  onFitView,
  onFullscreen,
  onLegendFilter,
}: BrainGraphProps) {
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const hoveredNode = hoveredId ? nodeMap.get(hoveredId) : undefined;
  const hoveredConnections = hoveredNode
    ? links.filter((link) => link.source === hoveredNode.id || link.target === hoveredNode.id).length
    : 0;
  const compact = viewMode === "compact";
  const nodePointerStartRef = useRef<NodePointerStart | null>(null);
  const { openNodeDetail, detailDialog } = useBrainNodeDetail();

  const clusterRegions = useMemo(() => {
    const groups = new Map<string, GraphNode[]>();
    for (const node of visibleNodes) {
      const key = node.cluster || "Overig";
      const group = groups.get(key);
      if (group) group.push(node);
      else groups.set(key, [node]);
    }
    return Array.from(groups.entries()).map(([label, group], index) => {
      const xs = group.map((node) => node.x);
      const ys = group.map((node) => node.y);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      return {
        id: `${label}-${index}`,
        label,
        count: group.length,
        cx: (minX + maxX) / 2,
        cy: (minY + maxY) / 2,
        rx: Math.max(82, (maxX - minX) / 2 + 72),
        ry: Math.max(62, (maxY - minY) / 2 + 58),
        tone: CLUSTER_TONES[index % CLUSTER_TONES.length],
      };
    });
  }, [visibleNodes]);

  const satellites = useMemo(() => {
    if (compact) return [];
    return visibleNodes.slice(0, MAX_DECORATED_NODES).flatMap((node, nodeIndex) => {
      if (node.kind === "core") return [];
      const count = nodeIndex % 3 === 0 ? 4 : 3;
      return Array.from({ length: count }, (_, satelliteIndex) => {
        const angle = ((satelliteIndex / count) * Math.PI * 2) + nodeIndex * 0.61;
        const distance = 49 + ((nodeIndex + satelliteIndex) % 3) * 9;
        return {
          id: `${node.id}-sat-${satelliteIndex}`,
          kind: node.kind,
          x: node.x + Math.cos(angle) * distance,
          y: node.y + Math.sin(angle) * distance,
          parentX: node.x,
          parentY: node.y,
        };
      });
    });
  }, [compact, visibleNodes]);

  const handleNodePointerDown = (event: React.PointerEvent<SVGGElement>, node: GraphNode) => {
    nodePointerStartRef.current = {
      pointerId: event.pointerId,
      nodeId: node.id,
      clientX: event.clientX,
      clientY: event.clientY,
    };
    onNodePointerDown(event, node);
  };

  const handlePointerEnd: React.PointerEventHandler<SVGSVGElement> = (event) => {
    const start = nodePointerStartRef.current;
    if (event.type === "pointerup" && start?.pointerId === event.pointerId) {
      const distance = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY);
      if (distance <= NODE_CLICK_TOLERANCE_PX) {
        const node = nodeMap.get(start.nodeId);
        if (node) {
          onSelectNode(node.id);
          void openNodeDetail(node);
        }
      }
    }
    nodePointerStartRef.current = null;
    onPointerEnd(event);
  };

  return (
    <section ref={surfaceRef} className={`b2-graph-panel view-${viewMode}`}>
      <div className="b2-cosmic-vignette" aria-hidden="true" />
      <div className="b2-graph-controls" aria-label="Graph navigatie">
        <Button variant="outline" size="icon" onClick={() => onZoom(clamp(viewport.zoom + 0.12, ZOOM_MIN, ZOOM_MAX))} aria-label="Inzoomen"><Plus /></Button>
        <Button variant="outline" size="icon" onClick={() => onZoom(clamp(viewport.zoom - 0.12, ZOOM_MIN, ZOOM_MAX))} aria-label="Uitzoomen"><Minus /></Button>
        <Button variant="outline" size="icon" onClick={onResetView} aria-label="Centreren"><Crosshair /></Button>
        <Button variant="outline" size="icon" onClick={onFitView} aria-label="Alles passend maken"><ZoomIn /></Button>
        <Button variant="outline" size="icon" onClick={onFullscreen} aria-label="Volledig scherm"><Maximize2 /></Button>
      </div>

      <svg
        ref={svgRef}
        className={`b2-graph-svg ${drag?.mode === "pan" ? "is-panning" : ""}`}
        viewBox="0 0 1000 650"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Interactieve HADES Brain kennisgraaf"
        onWheel={onWheel}
        onPointerDown={onSurfacePointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={handlePointerEnd}
        onPointerCancel={handlePointerEnd}
      >
        <defs>
          <radialGradient id="b2-core-gradient" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#ffe7a3" />
            <stop offset="26%" stopColor="#d6a642" />
            <stop offset="72%" stopColor="#8f5e16" />
            <stop offset="100%" stopColor="#4c2f0b" />
          </radialGradient>
          <filter id="b2-core-glow" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="11" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="b2-soft-shadow" x="-90%" y="-90%" width="280%" height="280%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="b2-star-glow" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="1.7" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <g className="b2-starfield" aria-hidden="true">
          {COSMIC_STARS.map((star) => (
            <circle key={star.id} cx={star.x} cy={star.y} r={star.r} opacity={star.opacity} style={{ animationDelay: star.delay }} />
          ))}
        </g>

        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.zoom})`}>
          {viewMode === "clusters" ? (
            <g className="b2-clusters" aria-hidden="true">
              {clusterRegions.map((cluster) => (
                <g key={cluster.id} className={`b2-cluster cluster-${cluster.tone}`}>
                  <ellipse cx={cluster.cx} cy={cluster.cy} rx={cluster.rx} ry={cluster.ry} />
                  <text
                    className="b2-cluster-label"
                    x={cluster.cx}
                    y={cluster.cy - cluster.ry + 22}
                    textAnchor="middle"
                    fill="#b8cbe6"
                    fontSize="11"
                    fontWeight="700"
                  >
                    {cluster.label} · {cluster.count}
                  </text>
                </g>
              ))}
            </g>
          ) : null}

          {!compact ? (
            <g className="b2-satellites" aria-hidden="true">
              {satellites.map((satellite) => (
                <g key={satellite.id} className={`b2-satellite kind-${satellite.kind}`}>
                  <line x1={satellite.parentX} y1={satellite.parentY} x2={satellite.x} y2={satellite.y} />
                  <circle cx={satellite.x} cy={satellite.y} r="3.2" />
                  <circle className="b2-satellite-halo" cx={satellite.x} cy={satellite.y} r="7" />
                </g>
              ))}
            </g>
          ) : null}

          <g className="b2-links">
            {viewMode !== "clusters" && visibleLinks.map((link) => {
              const source = nodeMap.get(link.source);
              const target = nodeMap.get(link.target);
              if (!source || !target) return null;
              const active = link.source === selectedId || link.target === selectedId;
              const dx = target.x - source.x;
              const dy = target.y - source.y;
              const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
              const bend = compact ? 0 : Math.min(58, distance * 0.14);
              const mx = (source.x + target.x) / 2 - (dy / distance) * bend;
              const my = (source.y + target.y) / 2 + (dx / distance) * bend;
              const path = `M ${source.x} ${source.y} Q ${mx} ${my} ${target.x} ${target.y}`;
              return (
                <g key={link.id} className={active ? "is-active" : ""}>
                  <path className="b2-link" d={path}><title>{link.relation}</title></path>
                  {!compact ? <path className="b2-link-flow" d={path} /> : null}
                </g>
              );
            })}
          </g>

          <g className="b2-nodes">
            {visibleNodes.map((node, index) => {
              const selected = node.id === selectedId;
              const hovered = node.id === hoveredId;
              const size = node.kind === "core" ? (compact ? 38 : 46) : (compact ? 22 : 30);
              const maxLabel = compact ? 21 : 27;
              return (
                <g
                  key={node.id}
                  className={`b2-node kind-${node.kind} ${selected ? "is-selected" : ""} ${hovered ? "is-hovered" : ""} ${node.pinned ? "is-pinned" : ""} ${drag?.mode === "node" && drag.nodeId === node.id ? "is-dragging" : ""}`}
                  transform={`translate(${node.x} ${node.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.label} openen${node.layoutMovable && !node.pinned ? " of verslepen" : ""}`}
                  onPointerDown={(event) => handleNodePointerDown(event, node)}
                  onPointerEnter={() => onHoverNode(node.id)}
                  onPointerLeave={() => onHoverNode(hoveredId === node.id ? null : hoveredId)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectNode(node.id);
                      void openNodeDetail(node);
                    }
                  }}
                >
                  {!compact ? <circle className="b2-node-orbit orbit-a" r={size + 18} /> : null}
                  {!compact ? <circle className="b2-node-orbit orbit-b" r={size + 27} /> : null}
                  {!compact ? <circle className="b2-node-aura" r={size + 15} style={{ animationDelay: `${index * 90}ms` }} /> : null}
                  <circle className="b2-node-ring" r={size + (compact ? 4 : 7)} />
                  <circle
                    className="b2-node-body"
                    r={size}
                    filter={compact ? undefined : node.kind === "core" ? "url(#b2-core-glow)" : "url(#b2-soft-shadow)"}
                  />
                  <foreignObject x={-13} y={-13} width="26" height="26" className="b2-node-icon"><div><BrainNodeIcon kind={node.icon} /></div></foreignObject>
                  <text className="b2-node-label" textAnchor="middle" y={size + (compact ? 19 : 26)}>
                    {node.label.length > maxLabel ? `${node.label.slice(0, maxLabel - 1)}...` : node.label}
                  </text>
                  {!compact ? (
                    <foreignObject x={-42} y={size + 34} width="84" height="24" className="b2-node-chip"><div>{KIND_LABELS[node.kind]}</div></foreignObject>
                  ) : null}
                  <title>{node.description}</title>
                </g>
              );
            })}
          </g>

          {hoveredNode && drag?.mode !== "node" ? (
            <foreignObject
              className="b2-hover-card-fo"
              x={clamp(hoveredNode.x + 40, 24, 744)}
              y={clamp(hoveredNode.y - 112, 18, 490)}
              width="238"
              height="148"
            >
              <div className={`b2-hover-card kind-${hoveredNode.kind}`}>
                <div className="b2-hover-card-head">
                  <span className="b2-hover-dot" />
                  <div><strong>{hoveredNode.label}</strong><small>{KIND_LABELS[hoveredNode.kind]}</small></div>
                </div>
                <p>{hoveredNode.description || "Geen beschrijving beschikbaar."}</p>
                <div className="b2-hover-tags">
                  {(hoveredNode.tags || []).slice(0, 3).map((tag, index) => <span key={`${tag}-${index}`}>#{tag.replace(/^#/, "")}</span>)}
                </div>
                <footer><span>{hoveredConnections} koppelingen</span><span>Bijgewerkt {hoveredNode.updatedAt}</span></footer>
              </div>
            </foreignObject>
          ) : null}
        </g>
      </svg>

      <div className="b2-legend" aria-label="Node types">
        {(["core", "memory", "knowledge", "chat", "task", "agent", "tech", "note"] as NodeKind[]).map((kind) => (
          <button key={kind} type="button" className={kindFilter === kind ? "active" : ""} onClick={() => onLegendFilter(kind)}><i className={`kind-${kind}`} />{KIND_LABELS[kind]}</button>
        ))}
      </div>

      <div className="b2-graph-help">Klik voor volledige inhoud <span>•</span> Sleep nodes om te verplaatsen <span>•</span> Scroll om te zoomen</div>

      <div className="b2-minimap">
        <button type="button" className="b2-minimap-map" aria-label="Minimap: klik om graph te centreren" onClick={onResetView}>
          <svg viewBox="0 0 1000 650" aria-hidden="true">
            {visibleLinks.map((link) => {
              const a = nodeMap.get(link.source);
              const b = nodeMap.get(link.target);
              return a && b ? <line key={link.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} /> : null;
            })}
            {visibleNodes.map((node) => <circle key={node.id} cx={node.x} cy={node.y} r={node.kind === "core" ? 12 : 7} className={`kind-${node.kind}`} />)}
            <rect x={(-viewport.x / viewport.zoom)} y={(-viewport.y / viewport.zoom)} width={1000 / viewport.zoom} height={650 / viewport.zoom} />
          </svg>
        </button>
        <div className="b2-minimap-controls"><button type="button" onClick={() => onZoom(clamp(viewport.zoom - 0.12, ZOOM_MIN, ZOOM_MAX))} aria-label="Uitzoomen via minimap"><Minus /></button><strong>{Math.round(viewport.zoom * 100)}%</strong><button type="button" onClick={() => onZoom(clamp(viewport.zoom + 0.12, ZOOM_MIN, ZOOM_MAX))} aria-label="Inzoomen via minimap"><Plus /></button></div>
      </div>

      {detailDialog}
    </section>
  );
}
