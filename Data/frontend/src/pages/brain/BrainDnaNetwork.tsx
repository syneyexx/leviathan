/**
 * SVG DNA knowledge network — deterministic, data-driven, subdued motion.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  BRAIN_CATEGORY_HEX,
  BRAIN_CATEGORY_META,
  BRAIN_FILTER_TABS,
  filterNodesByCategory,
  type BrainCategoryFilter,
} from "./brain-categories";
import { layoutDnaNetwork, type DnaLaidOutNode } from "./brain-dna-layout";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";

export type BrainDnaNetworkProps = {
  nodes: readonly LiveBrainNode[];
  edges: readonly LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  categoryFilter: BrainCategoryFilter;
  onCategoryFilterChange: (filter: BrainCategoryFilter) => void;
  preferredFocalId?: string | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  reducedMotion?: boolean;
  className?: string;
};

const MIN_ZOOM = 0.55;
const MAX_ZOOM = 2.4;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function labelWorthy(
  node: DnaLaidOutNode,
  selectedId: string | null,
  hoverId: string | null,
  zoom: number,
): boolean {
  if (node.focal) return true;
  if (node.id === selectedId || node.id === hoverId) return true;
  if (zoom < 0.75) return false;
  // Named Screen-1-class labels (non-generic) always show at default zoom.
  if (!/^Node \d+$/i.test(node.label) && node.label.length <= 22) return true;
  return node.degree >= 3 || node.r >= 9;
}

export function BrainDnaNetwork({
  nodes,
  edges,
  selectedId,
  onSelect,
  categoryFilter,
  onCategoryFilterChange,
  preferredFocalId = null,
  loading = false,
  error = null,
  onRetry,
  reducedMotion,
  className = "",
}: BrainDnaNetworkProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 720, height: 340 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragOrigin = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const motionOff = reducedMotion ?? prefersReducedMotion();

  useEffect(() => {
    const el = shellRef.current;
    if (!el) return;
    const apply = () => {
      const rect = el.getBoundingClientRect();
      const width = Math.max(320, rect.width || 720);
      const height = Math.max(280, rect.height || 340);
      setSize((prev) =>
        Math.abs(prev.width - width) < 1 && Math.abs(prev.height - height) < 1
          ? prev
          : { width, height },
      );
    };
    apply();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => apply());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const filteredNodes = useMemo(
    () => filterNodesByCategory(nodes, categoryFilter),
    [nodes, categoryFilter],
  );
  const filteredIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);
  const filteredEdges = useMemo(
    () => edges.filter((e) => filteredIds.has(e.source) && filteredIds.has(e.target)),
    [edges, filteredIds],
  );

  const layout = useMemo(
    () =>
      layoutDnaNetwork(filteredNodes, filteredEdges, {
        width: size.width,
        height: size.height,
        preferredFocalId,
        maxPrimary: 48,
      }),
    [filteredNodes, filteredEdges, size.width, size.height, preferredFocalId],
  );

  const pos = useMemo(() => new Map(layout.nodes.map((n) => [n.id, n])), [layout.nodes]);

  const clampZoom = useCallback((value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value)), []);

  const zoomBy = useCallback(
    (factor: number) => {
      setZoom((z) => clampZoom(z * factor));
    },
    [clampZoom],
  );

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const fitView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const enterFullscreen = useCallback(async () => {
    const el = shellRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await el.requestFullscreen();
    } catch {
      // Fullscreen may be blocked — non-fatal.
    }
  }, []);

  const onPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const target = event.target as Element;
    if (target.closest(".lv-v2-dna-node")) return;
    dragOrigin.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
    setDragging(true);
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent) => {
    if (!dragOrigin.current) return;
    const dx = event.clientX - dragOrigin.current.x;
    const dy = event.clientY - dragOrigin.current.y;
    setPan({ x: dragOrigin.current.panX + dx, y: dragOrigin.current.panY + dy });
  };

  const onPointerUp = () => {
    dragOrigin.current = null;
    setDragging(false);
  };

  const onNodeKeyDown = (event: KeyboardEvent, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id);
    }
  };

  const rootClass = [
    "lv-v2-dna",
    motionOff ? "is-reduced-motion" : "",
    dragging ? "is-dragging" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rootClass} ref={shellRef}>
      <div className="lv-v2-dna__tabs" role="tablist" aria-label="Kennisnetwerk filters">
        {BRAIN_FILTER_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={categoryFilter === tab.id}
            className={`lv-v2-dna__tab${categoryFilter === tab.id ? " is-active" : ""}`}
            onClick={() => onCategoryFilterChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        className="lv-v2-dna__stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {error ? (
          <div className="lv-v2-dna__overlay" role="alert">
            <p>{error}</p>
            {onRetry ? (
              <button type="button" className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm" onClick={onRetry}>
                Opnieuw proberen
              </button>
            ) : null}
          </div>
        ) : null}
        {!error && loading && layout.nodes.length === 0 ? (
          <div className="lv-v2-dna__overlay" aria-busy="true">
            <p>Kennisnetwerk laden…</p>
          </div>
        ) : null}
        {!error && !loading && layout.nodes.length === 0 ? (
          <div className="lv-v2-dna__overlay">
            <p>Geen kennisnodes in deze projectie</p>
            {categoryFilter !== "all" ? (
              <button
                type="button"
                className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
                onClick={() => onCategoryFilterChange("all")}
              >
                Reset filter
              </button>
            ) : null}
          </div>
        ) : null}

        <svg
          ref={svgRef}
          className="lv-v2-dna__svg"
          width="100%"
          height="100%"
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="img"
          aria-label="DNA kennisnetwerk"
        >
          <defs>
            <radialGradient id="lv2-dna-focal-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.55" />
              <stop offset="70%" stopColor="#22d3ee" stopOpacity="0.12" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
            </radialGradient>
            <filter id="lv2-dna-soft-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="2.2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`} style={{ transformOrigin: "center" }}>
            {/* Ambient helix guides */}
            <path
              className="lv-v2-dna__helix"
              d={`M ${size.width * 0.08} ${size.height * 0.5}
                  Q ${size.width * 0.25} ${size.height * 0.18}, ${size.width * 0.42} ${size.height * 0.5}
                  T ${size.width * 0.92} ${size.height * 0.5}`}
              fill="none"
            />
            <path
              className="lv-v2-dna__helix lv-v2-dna__helix--alt"
              d={`M ${size.width * 0.08} ${size.height * 0.5}
                  Q ${size.width * 0.25} ${size.height * 0.82}, ${size.width * 0.42} ${size.height * 0.5}
                  T ${size.width * 0.92} ${size.height * 0.5}`}
              fill="none"
            />

            {layout.edges.map((edge) => {
              const a = pos.get(edge.source);
              const b = pos.get(edge.target);
              if (!a || !b) return null;
              const midX = (a.x + b.x) / 2;
              const midY = (a.y + b.y) / 2 + (edge.kind === "rung" ? 0 : (a.y < b.y ? -12 : 12));
              return (
                <path
                  key={edge.id}
                  className={`lv-v2-dna__edge lv-v2-dna__edge--${edge.kind}`}
                  d={`M ${a.x} ${a.y} Q ${midX} ${midY} ${b.x} ${b.y}`}
                  opacity={edge.opacity}
                />
              );
            })}

            {layout.nodes.map((node) => {
              const selected = node.id === selectedId;
              const showLabel = labelWorthy(node, selectedId, hoverId, zoom);
              const color = BRAIN_CATEGORY_HEX[node.category];
              return (
                <g
                  key={node.id}
                  className={`lv-v2-dna-node${selected ? " is-selected" : ""}${node.focal ? " is-focal" : ""}`}
                  transform={`translate(${node.x} ${node.y})`}
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.label} (${node.category})`}
                  aria-pressed={selected}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(node.id);
                  }}
                  onKeyDown={(event) => onNodeKeyDown(event, node.id)}
                  onMouseEnter={() => setHoverId(node.id)}
                  onMouseLeave={() => setHoverId((id) => (id === node.id ? null : id))}
                >
                  {node.focal || selected ? (
                    <circle className="lv-v2-dna-node__halo" r={node.r + 14} fill="url(#lv2-dna-focal-glow)" />
                  ) : null}
                  <circle
                    className="lv-v2-dna-node__core"
                    r={node.r}
                    fill={color}
                    filter={node.focal || selected ? "url(#lv2-dna-soft-glow)" : undefined}
                  />
                  {showLabel ? (
                    <text className="lv-v2-dna-node__label" y={-(node.r + 8)} textAnchor="middle">
                      {node.label}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>

        <div className="lv-v2-dna__legend" aria-hidden="true">
          {BRAIN_CATEGORY_META.map((row) => (
            <span key={row.id} className="lv-v2-dna__legend-item">
              <i style={{ background: BRAIN_CATEGORY_HEX[row.id] }} />
              {row.label}
            </span>
          ))}
        </div>

        <div className="lv-v2-dna__controls" role="toolbar" aria-label="Netwerk bediening">
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.15)}>
            +
          </button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.15)}>
            −
          </button>
          <button type="button" aria-label="Reset weergave" onClick={resetView} title="Reset">
            ⌖
          </button>
          <button type="button" aria-label="Passend maken" onClick={fitView} title="Fit">
            ⛶
          </button>
          <button type="button" aria-label="Volledig scherm" onClick={() => void enterFullscreen()}>
            ↗
          </button>
        </div>
      </div>
    </div>
  );
}
