import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { buildDnaLayout, type DnaRenderNode } from "./brain-dna-layout";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

type Viewport = { x: number; y: number; scale: number };

type Props = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  colorForType: (type: string) => string;
  className?: string;
  reducedMotion?: boolean;
};

function prettyType(type: string): string {
  return type
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => (part.length <= 3 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`))
    .join(" ");
}

export function BrainDnaCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
  colorForType,
  className,
  reducedMotion = false,
}: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panRef = useRef<{ pointerId: number; startX: number; startY: number; viewport: Viewport } | null>(null);
  const [size, setSize] = useState({ width: 800, height: 480 });
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, scale: 1 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const apply = (width: number, height: number) => {
      setSize({
        width: Math.max(320, Math.floor(width)),
        height: Math.max(240, Math.floor(height)),
      });
    };
    apply(el.clientWidth, el.clientHeight);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      apply(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onFs = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const layout = useMemo(
    () =>
      buildDnaLayout({
        nodes,
        edges,
        width: size.width,
        height: size.height,
        selectedId,
        colorForType,
      }),
    [nodes, edges, size.width, size.height, selectedId, colorForType],
  );

  const byId = useMemo(() => new Map(layout.nodes.map((node) => [node.id, node])), [layout.nodes]);
  const hovered = hoveredId ? byId.get(hoveredId) ?? null : null;

  const zoomBy = useCallback((factor: number) => {
    setViewport((previous) => {
      const scale = Math.max(0.35, Math.min(3.5, previous.scale * factor));
      const ratio = scale / previous.scale;
      const cx = size.width / 2;
      const cy = size.height / 2;
      return {
        x: cx - (cx - previous.x) * ratio,
        y: cy - (cy - previous.y) * ratio,
        scale,
      };
    });
  }, [size.width, size.height]);

  const resetViewport = useCallback(() => {
    setViewport({ x: 0, y: 0, scale: 1 });
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const el = rootRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await el.requestFullscreen();
      }
    } catch {
      // Fullscreen may be blocked by the browser; ignore quietly.
    }
  }, []);

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    panRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      viewport: { ...viewport },
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    const dx = event.clientX - pan.startX;
    const dy = event.clientY - pan.startY;
    setViewport({
      ...pan.viewport,
      x: pan.viewport.x + dx,
      y: pan.viewport.y + dy,
    });
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (panRef.current?.pointerId === event.pointerId) panRef.current = null;
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    zoomBy(event.deltaY > 0 ? 0.9 : 1.1);
  };

  const handleNodeKeyDown = (event: ReactKeyboardEvent<SVGGElement>, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id);
    }
  };

  const selectNode = (id: string) => {
    onSelect(selectedId === id ? null : id);
  };

  const rootClass = ["lv-v2-dna", className, reducedMotion ? "is-reduced-motion" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div ref={rootRef} className={rootClass}>
      <div className="lv-v2-dna-toolbar" aria-label="DNA graph controls">
        <button type="button" className="lv-v2-icon-btn" onClick={() => zoomBy(0.86)} aria-label="Zoom out">
          −
        </button>
        <button type="button" className="lv-v2-icon-btn" onClick={() => zoomBy(1.16)} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="lv-v2-icon-btn" onClick={resetViewport} aria-label="Reset view">
          ⟲
        </button>
        <button
          type="button"
          className="lv-v2-icon-btn"
          onClick={() => void toggleFullscreen()}
          aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        >
          {isFullscreen ? "⤡" : "⤢"}
        </button>
        <span className="lv-v2-dna-zoom-label">{Math.round(viewport.scale * 100)}%</span>
      </div>

      <svg
        ref={svgRef}
        className="lv-v2-dna-svg"
        viewBox={`0 0 ${size.width} ${size.height}`}
        preserveAspectRatio="xMidYMid meet"
        aria-label="LEVIATHAN Brain DNA knowledge graph"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
        onClick={() => onSelect(null)}
      >
        <defs>
          <filter id="lv-v2-dna-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          <g className="lv-v2-dna-scaffold" pointerEvents="none">
            {layout.scaffold.map((segment) => (
              <line
                key={segment.id}
                className={`lv-v2-dna-scaffold__${segment.kind}`}
                x1={segment.x1}
                y1={segment.y1}
                x2={segment.x2}
                y2={segment.y2}
              />
            ))}
          </g>

          <g className="lv-v2-dna-edges">
            {layout.semanticEdges.map((edge) => {
              const source = byId.get(edge.source);
              const target = byId.get(edge.target);
              if (!source || !target) return null;
              const active =
                selectedId != null && (edge.source === selectedId || edge.target === selectedId);
              return (
                <line
                  key={edge.id}
                  className={`lv-v2-dna-edge${active ? " is-active" : ""}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                >
                  <title>{edge.relation}</title>
                </line>
              );
            })}
          </g>

          <g className="lv-v2-dna-nodes">
            {layout.nodes.map((node) => (
              <DnaNode
                key={node.id}
                node={node}
                selected={selectedId === node.id}
                onSelect={selectNode}
                onHover={setHoveredId}
                onKeyDown={handleNodeKeyDown}
              />
            ))}
          </g>
        </g>
      </svg>

      {hovered ? (
        <div className="lv-v2-dna-tooltip" role="tooltip">
          <strong>{hovered.label}</strong>
          <span>{prettyType(hovered.type)}</span>
        </div>
      ) : null}
    </div>
  );
}

function DnaNode({
  node,
  selected,
  onSelect,
  onHover,
  onKeyDown,
}: {
  node: DnaRenderNode;
  selected: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGGElement>, id: string) => void;
}) {
  return (
    <g
      className={`lv-v2-dna-node${selected ? " is-selected" : ""}`}
      transform={`translate(${node.x} ${node.y})`}
      style={{ ["--node-color" as string]: node.color }}
      tabIndex={0}
      role="button"
      aria-label={`${node.label}, ${prettyType(node.type)}`}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
      onFocus={() => onHover(node.id)}
      onBlur={() => onHover(null)}
      onKeyDown={(event) => onKeyDown(event, node.id)}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(node.id);
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      {selected ? <circle className="lv-v2-dna-node__halo" r={node.r + 8} /> : null}
      <circle className="lv-v2-dna-node__glow" r={node.r + 4} />
      <circle className="lv-v2-dna-node__core" r={node.r} filter="url(#lv-v2-dna-glow)" />
      {node.showLabel ? (
        <text className="lv-v2-dna-node__label" y={node.r + 14} textAnchor="middle">
          {node.label.length > 28 ? `${node.label.slice(0, 26)}…` : node.label}
        </text>
      ) : null}
    </g>
  );
}
