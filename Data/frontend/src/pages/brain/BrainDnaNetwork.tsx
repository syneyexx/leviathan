/**
 * SVG DNA knowledge network — Screen 1 double-helix, data-driven, stable.
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
  if (zoom < 0.8) return node.degree >= 4;
  if (!/^Node \d+$/i.test(node.label) && node.label.length <= 20) {
    // Bound labeled nodes so helix stays readable
    return node.degree >= 2 || node.r >= 7;
  }
  return node.degree >= 4 || node.r >= 10;
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
  const stageRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 720, height: 300 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragOrigin = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const motionOff = reducedMotion ?? prefersReducedMotion();

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const apply = () => {
      const rect = el.getBoundingClientRect();
      const width = Math.max(280, rect.width || 720);
      const height = Math.max(220, rect.height || 300);
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
        maxPrimary: 36,
        turns: 2.15,
      }),
    [filteredNodes, filteredEdges, size.width, size.height, preferredFocalId],
  );

  const pos = useMemo(() => new Map(layout.nodes.map((n) => [n.id, n])), [layout.nodes]);

  // Cap simultaneous labels for Screen 1 density
  const labeledIds = useMemo(() => {
    const ranked = [...layout.nodes]
      .filter((n) => !n.focal)
      .sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id));
    const keep = new Set<string>();
    keep.add(layout.focalId ?? "");
    for (const n of ranked) {
      if (keep.size >= 14) break;
      if (!/^Node \d+$/i.test(n.label)) keep.add(n.id);
    }
    if (selectedId) keep.add(selectedId);
    if (hoverId) keep.add(hoverId);
    return keep;
  }, [layout.nodes, layout.focalId, selectedId, hoverId]);

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
      // non-fatal
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

  const cx = size.width / 2;
  const cy = size.height / 2;

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
        ref={stageRef}
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
          className="lv-v2-dna__svg"
          width="100%"
          height="100%"
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="img"
          aria-label="DNA kennisnetwerk"
        >
          <defs>
            <radialGradient id="lv2-dna-focal-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#67e8f9" stopOpacity="0.7" />
              <stop offset="45%" stopColor="#22d3ee" stopOpacity="0.28" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
            </radialGradient>
            <linearGradient id="lv2-dna-strand-grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.15" />
              <stop offset="50%" stopColor="#67e8f9" stopOpacity="0.85" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.15" />
            </linearGradient>
            <filter id="lv2-dna-soft-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="2.4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="lv2-dna-strand-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g
            transform={`translate(${cx} ${cy}) scale(${zoom}) translate(${-cx + pan.x / zoom} ${-cy + pan.y / zoom})`}
          >
            {/* Ambient particles along helix (decorative, non-interactive) */}
            {Array.from({ length: 18 }, (_, i) => {
              const t = (i + 0.5) / 18;
              const x = size.width * 0.08 + t * size.width * 0.84;
              const y = cy + Math.sin(t * Math.PI * 2 * 2.15 + i) * (size.height * 0.28);
              return (
                <circle
                  key={`dust-${i}`}
                  className="lv-v2-dna__dust"
                  cx={x}
                  cy={y}
                  r={i % 3 === 0 ? 1.6 : 1.1}
                />
              );
            })}

            {/* DNA backbone strands — Screen 1 silhouette (glow + core) */}
            {layout.helix.strand0 ? (
              <>
                <path
                  className="lv-v2-dna__helix lv-v2-dna__helix--glow"
                  d={layout.helix.strand0}
                  fill="none"
                />
                <path
                  className="lv-v2-dna__helix lv-v2-dna__helix--a"
                  d={layout.helix.strand0}
                  fill="none"
                  filter="url(#lv2-dna-strand-glow)"
                />
              </>
            ) : null}
            {layout.helix.strand1 ? (
              <>
                <path
                  className="lv-v2-dna__helix lv-v2-dna__helix--glow"
                  d={layout.helix.strand1}
                  fill="none"
                />
                <path
                  className="lv-v2-dna__helix lv-v2-dna__helix--b"
                  d={layout.helix.strand1}
                  fill="none"
                  filter="url(#lv2-dna-strand-glow)"
                />
              </>
            ) : null}

            {/* Edges: rungs (+ Screen 1 beads), then strand, then faint secondary */}
            {layout.edges.map((edge) => {
              const a = pos.get(edge.source);
              const b = pos.get(edge.target);
              if (!a || !b) return null;
              if (edge.kind === "rung") {
                const beads = [0.22, 0.4, 0.5, 0.6, 0.78].map((t, i) => {
                  const bx = a.x + (b.x - a.x) * t;
                  const by = a.y + (b.y - a.y) * t;
                  const palette = ["#a78bfa", "#22d3ee", "#67e8f9", "#fbbf24", "#34d399"];
                  return (
                    <circle
                      key={`${edge.id}:bead:${i}`}
                      className="lv-v2-dna__bead"
                      cx={bx}
                      cy={by}
                      r={i === 2 ? 2.2 : 1.55}
                      fill={palette[i % palette.length]}
                    />
                  );
                });
                return (
                  <g key={edge.id}>
                    <line
                      className="lv-v2-dna__edge lv-v2-dna__edge--rung"
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      opacity={edge.opacity}
                    />
                    {beads}
                  </g>
                );
              }
              const midX = (a.x + b.x) / 2;
              const midY = (a.y + b.y) / 2 + (edge.kind === "strand" ? (a.strand === 0 ? -6 : 6) : 0);
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
              const showLabel =
                labeledIds.has(node.id) || labelWorthy(node, selectedId, hoverId, zoom);
              // Screen 1: focal hub is luminous cyan regardless of category
              const color = node.focal ? "#22d3ee" : BRAIN_CATEGORY_HEX[node.category];
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
                    <circle
                      className="lv-v2-dna-node__halo"
                      r={node.r + (node.focal ? 18 : 12)}
                      fill="url(#lv2-dna-focal-glow)"
                    />
                  ) : null}
                  <circle
                    className="lv-v2-dna-node__core"
                    r={node.r}
                    fill={color}
                    filter={node.focal || selected ? "url(#lv2-dna-soft-glow)" : undefined}
                  />
                  {node.focal ? (
                    <circle
                      className="lv-v2-dna-node__ring"
                      r={node.r + 4}
                      fill="none"
                      stroke="#67e8f9"
                      strokeWidth="1.4"
                      opacity="0.85"
                    />
                  ) : null}
                  {showLabel ? (
                    <text
                      className="lv-v2-dna-node__label"
                      y={node.focal ? -(node.r + 14) : node.strand === 0 ? -(node.r + 8) : node.r + 14}
                      textAnchor="middle"
                    >
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
