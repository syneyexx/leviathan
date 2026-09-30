/**
 * Canvas 2D living helix — frame geometry in refs (no React state per frame).
 */

import {
  useEffect,
  useRef,
} from "react";
import {
  assignStableHelixSlots,
  focusAngleForNode,
  hitTestEdge,
  hitTestNode,
  projectHelix,
  projectNodes,
  shortestAngleDelta,
  type HelixLink,
  type HelixNode,
  type ProjectedEdge,
  type ProjectedNode,
} from "./brain-helix-engine";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import { BRAIN_CATEGORY_HEX, categoryForNode } from "./brain-categories";

export type BrainLivingNetworkCanvasProps = {
  nodes: readonly LiveBrainNode[];
  accessibilityNodes?: readonly LiveBrainNode[];
  edges: readonly LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  selectedEdgeId: string | null;
  onSelectEdge: (id: string | null) => void;
  activeNodeIds?: ReadonlySet<string>;
  gapNodeIds?: ReadonlySet<string>;
  mode: "dna" | "network";
  paused: boolean;
  resetToken?: number;
  speed: number;
  twist: number;
  showLabels: boolean;
  showRelations: boolean;
  reducedMotion?: boolean;
  filterPredicate?: (node: LiveBrainNode) => boolean;
  className?: string;
};

type EngineRefs = {
  angle: number;
  tilt: number;
  zoom: number;
  speed: number;
  twist: number;
  morph: number;
  mode: "dna" | "network";
  paused: boolean;
  targetAngle: number | null;
  selectedId: string | null;
  selectedEdgeId: string | null;
  activeIds: Set<string>;
  gapIds: Set<string>;
  showLabels: boolean;
  showRelations: boolean;
  reduced: boolean;
  nodes: HelixNode[];
  links: HelixLink[];
  filter: (n: HelixNode) => boolean;
  points: ProjectedNode[];
  edgeSegments: ProjectedEdge[];
  seenIds: Set<string>;
  births: Map<string, number>;
  time: number;
  last: number;
  drag: { x: number; y: number; distance: number } | null;
  w: number;
  h: number;
};

export function BrainLivingNetworkCanvas({
  nodes,
  accessibilityNodes,
  edges,
  selectedId,
  onSelect,
  selectedEdgeId,
  onSelectEdge,
  activeNodeIds,
  gapNodeIds,
  mode,
  paused,
  resetToken = 0,
  speed,
  twist,
  showLabels,
  showRelations,
  reducedMotion = false,
  filterPredicate,
  className = "",
}: BrainLivingNetworkCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const engine = useRef<EngineRefs | null>(null);
  const selectRef = useRef(onSelect);
  const selectEdgeRef = useRef(onSelectEdge);
  selectRef.current = onSelect;
  selectEdgeRef.current = onSelectEdge;

  // Bootstrap engine once
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const eng: EngineRefs = {
      angle: 0.6,
      tilt: -0.095,
      zoom: 1,
      speed,
      twist,
      morph: mode === "network" ? 1 : 0,
      mode,
      paused: paused || reducedMotion,
      targetAngle: null,
      selectedId,
      selectedEdgeId,
      activeIds: new Set(activeNodeIds ?? []),
      gapIds: new Set(gapNodeIds ?? []),
      showLabels,
      showRelations,
      reduced: reducedMotion,
      nodes: [],
      links: [],
      filter: () => true,
      points: [],
      edgeSegments: [],
      seenIds: new Set(),
      births: new Map(),
      time: 0,
      last: 0,
      drag: null,
      w: 0,
      h: 0,
    };
    engine.current = eng;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const wrap = wrapRef.current;
      if (!wrap) return;
      const r = wrap.getBoundingClientRect();
      eng.w = Math.max(1, r.width);
      eng.h = Math.max(1, r.height);
      const dpr = Math.min(typeof devicePixelRatio === "number" ? devicePixelRatio : 1, 2);
      canvas.width = Math.round(eng.w * dpr);
      canvas.height = Math.round(eng.h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = () => {
      const w = eng.w;
      const h = eng.h;
      if (!w || !h) return;
      ctx.clearRect(0, 0, w, h);
      ctx.lineCap = "round";

      // Ambient grid
      ctx.strokeStyle = "rgba(80,125,146,0.12)";
      ctx.lineWidth = 0.4;
      for (let x = 25; x < w; x += 45) {
        ctx.beginPath();
        ctx.moveTo(x, 20);
        ctx.lineTo(x, h - 20);
        ctx.stroke();
      }
      for (let y = 20; y < h - 10; y += 45) {
        ctx.beginPath();
        ctx.moveTo(12, y);
        ctx.lineTo(w - 12, y);
        ctx.stroke();
      }

      const cfg = {
        width: w,
        height: h,
        angle: eng.angle,
        tilt: eng.tilt,
        zoom: eng.zoom,
        twist: eng.twist,
        morph: eng.morph,
        range: [0, 1] as const,
        selectedId: eng.selectedId,
        activeIds: eng.activeIds,
        filter: eng.filter,
      };

      // Same sparse particle field and three-pass tube lighting as the V3 reference.
      for (let i = 0; i < 40; i += 1) {
        const x = ((Math.sin(i * 78.233) * 43758.5453) % 1 + 1) % 1 * w;
        const y = ((Math.cos(i * 31.13) * 9758.31) % 1 + 1) % 1 * h;
        ctx.globalAlpha = 0.08 + (i % 5) * 0.025;
        ctx.fillStyle = "#8edce5";
        ctx.beginPath(); ctx.arc(x, y, i % 6 === 0 ? 1.2 : 0.6, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      const samples = 170;
      // Bloom
      for (let s = 0; s < 2; s += 1) {
        ctx.beginPath();
        for (let j = 0; j <= samples; j += 1) {
          const p = projectHelix(j / samples, s as 0 | 1, cfg);
          if (j === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        }
        ctx.strokeStyle = s ? "rgba(131,159,237,0.08)" : "rgba(89,231,208,0.1)";
        ctx.lineWidth = 18 * eng.zoom;
        ctx.globalAlpha = 1 - eng.morph;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      const items: Array<{ kind: string; z: number; draw: () => void }> = [];

      for (let s = 0; s < 2; s += 1) {
        for (let j = 0; j < samples; j += 1) {
          const t0 = j / samples;
          const t1 = (j + 1) / samples;
          const a = projectHelix(t0, s as 0 | 1, cfg);
          const b = projectHelix(t1, s as 0 | 1, cfg);
          const strand = s;
          items.push({
            kind: "tube",
            z: (a.z + b.z) / 2,
            draw: () => {
              const scale = (a.scale + b.scale) / 2;
              const front = ((a.z + b.z) / 2 + 1) / 2;
              const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
              const ux = (b.x - a.x) / len * 0.65, uy = (b.y - a.y) / len * 0.65;
              const ax = a.x - ux, ay = a.y - uy, bx = b.x + ux, by = b.y + uy;
              ctx.globalAlpha = 1 - eng.morph;
              ctx.lineCap = "butt";
              ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by);
              ctx.strokeStyle = strand ? `rgb(${23+front*22},${37+front*31},${62+front*44})` : `rgb(${17+front*12},${48+front*38},${57+front*39})`;
              ctx.lineWidth = 8 * scale; ctx.stroke();
              ctx.strokeStyle = strand ? `rgb(${44+front*44},${61+front*47},${94+front*65})` : `rgb(${31+front*29},${75+front*69},${82+front*62})`;
              ctx.lineWidth = 3.3 * scale; ctx.stroke();
              ctx.beginPath(); ctx.moveTo(ax, ay - 2 * scale); ctx.lineTo(bx, by - 2 * scale);
              ctx.strokeStyle = strand ? `rgb(${70+front*77},${87+front*74},${123+front*70})` : `rgb(${52+front*82},${105+front*83},${114+front*73})`;
              ctx.lineWidth = 0.75 * scale; ctx.stroke();
              ctx.lineCap = "round";
              ctx.globalAlpha = 1;
            },
          });
        }
      }

      eng.points = projectNodes(eng.nodes.filter(eng.filter), eng.links, cfg).sort((a, b) => a.z - b.z);
      eng.edgeSegments = [];
      const pointMap = new Map(eng.points.map((p) => [p.node.id, p]));

      for (const link of eng.showRelations ? eng.links : []) {
        const a = pointMap.get(link.source);
        const b = pointMap.get(link.target);
        if (!a || !b) continue;
        if (!eng.filter(a.node) || !eng.filter(b.node)) continue;
        const seg: ProjectedEdge = { link, a, b, z: (a.z + b.z) / 2 };
        eng.edgeSegments.push(seg);
        const selected = link.id === eng.selectedEdgeId;
        items.push({
          kind: "edge",
          z: seg.z,
          draw: () => {
            const focused = link.source === eng.selectedId || link.target === eng.selectedId;
            const active = eng.activeIds.has(link.source) && eng.activeIds.has(link.target);
            ctx.globalAlpha = selected ? 1 : active ? 0.75 : focused ? 0.45 : 0.08;
            ctx.strokeStyle = selected ? "#fbbf24" : "#67e8f9";
            ctx.lineWidth = selected ? 2.4 : 0.9;
            ctx.setLineDash(link.relation.toUpperCase() === "CONTRADICTS" ? [5, 4] : []);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
          },
        });
      }

      for (const p of eng.points) {
        items.push({
          kind: "node",
          z: p.z,
          draw: () => {
            const selected = p.node.id === eng.selectedId;
            const active = eng.activeIds.has(p.node.id);
            const gap = eng.gapIds.has(p.node.id);
            const birth = eng.births.get(p.node.id);
            let grow = 1;
            if (birth != null && !eng.reduced) {
              grow = Math.min(1, (eng.time - birth) / 0.55);
            }
            const cat = categoryForNode({
              id: p.node.id,
              type: p.node.type,
              label: p.node.label,
            } as LiveBrainNode);
            const color =
              p.node.strandRole === "source"
                ? "#22d3ee"
                : p.node.strandRole === "insight"
                  ? "#a78bfa"
                  : BRAIN_CATEGORY_HEX[cat];
            const r = Math.max(3.5, p.r * p.scale * grow);
            ctx.globalAlpha = Math.max(0.25, 0.45 + (p.z + 1) * 0.28);
            if (active || selected) {
              ctx.beginPath();
              ctx.fillStyle = active ? "rgba(34,211,238,0.28)" : "rgba(103,232,249,0.22)";
              ctx.arc(p.x, p.y, r + (active ? 10 : 7), 0, Math.PI * 2);
              ctx.fill();
            }
            if (gap) {
              ctx.beginPath();
              ctx.strokeStyle = "#f59e0b";
              ctx.lineWidth = 1.5;
              ctx.arc(p.x, p.y, r + 5, 0, Math.PI * 2);
              ctx.stroke();
            }
            ctx.beginPath();
            const gradient = ctx.createRadialGradient(p.x - r * 0.3, p.y - r * 0.35, 0.1, p.x, p.y, r);
            gradient.addColorStop(0, "#ecfff8");
            gradient.addColorStop(0.35, color);
            gradient.addColorStop(1, p.node.strand ? "#405272" : "#236767");
            ctx.fillStyle = gradient;
            ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
            ctx.fill();
            if (selected) {
              ctx.beginPath();
              ctx.strokeStyle = "#e2e8f0";
              ctx.lineWidth = 1.6;
              ctx.arc(p.x, p.y, r + 2.5, 0, Math.PI * 2);
              ctx.stroke();
            }
            ctx.globalAlpha = 1;
          },
        });
      }

      items.sort((a, b) => a.z - b.z);
      for (const item of items) item.draw();

      // Reserve screen space for each label; prioritize focus and retrieved nodes.
      if (eng.showLabels) {
        const boxes: { x: number; y: number; w: number; h: number }[] = [];
        const candidates = [...eng.points].sort((a, b) =>
          Number(b.node.id === eng.selectedId) - Number(a.node.id === eng.selectedId) ||
          Number(eng.activeIds.has(b.node.id)) - Number(eng.activeIds.has(a.node.id)) || b.z - a.z);
        ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "left";
        for (const p of candidates) {
          if (boxes.length >= 12) break;
          if (p.z < -0.35 && p.node.id !== eng.selectedId) continue;
          const label = p.node.label.length > 28 ? `${p.node.label.slice(0, 26)}…` : p.node.label;
          const width = ctx.measureText(label).width + 10;
          const x = Math.max(8, Math.min(w - width - 8, p.x - width / 2));
          const y = p.y - p.r * p.scale - 25;
          const box = { x, y, w: width, h: 18 };
          if (y < 70 || y + 18 > h - 48 || p.x < 0 || p.x > w) continue;
          if (boxes.some((b) => x < b.x + b.w + 5 && x + width + 5 > b.x && y < b.y + b.h + 4 && y + 22 > b.y)) continue;
          boxes.push(box);
          ctx.fillStyle = "rgba(2,6,23,0.88)";
          ctx.fillRect(x, y, width, 18);
          ctx.fillStyle = p.node.id === eng.selectedId ? "#ffffff" : "#cbd5e1";
          ctx.fillText(label, x + 5, y + 12);
        }
      }
    };

    let frame = 0;
    const tick = (now: number) => {
      const dt = Math.min((now - (eng.last || now)) / 1000, 0.04);
      eng.last = now;
      if (typeof document !== "undefined" && document.visibilityState !== "hidden") {
        eng.time += dt;
        const targetMorph = eng.mode === "network" ? 1 : 0;
        eng.morph += (targetMorph - eng.morph) * Math.min(1, dt * 6);
        if (eng.reduced) eng.morph = targetMorph;
        if (!eng.paused && !eng.drag) eng.angle += dt * eng.speed * 0.6;
        if (eng.targetAngle != null && !eng.drag) {
          eng.angle += (eng.targetAngle - eng.angle) * Math.min(1, dt * 5);
          if (Math.abs(eng.targetAngle - eng.angle) < 0.002) eng.targetAngle = null;
        }
        draw();
      }
      frame = requestAnimationFrame(tick);
    };

    resize();
    const ro = new ResizeObserver(() => resize());
    if (wrapRef.current) ro.observe(wrapRef.current);

    const onDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      eng.drag = { x: e.clientX, y: e.clientY, distance: 0 };
      canvas.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      if (eng.drag) {
        const dx = e.clientX - eng.drag.x;
        const dy = e.clientY - eng.drag.y;
        eng.drag.distance += Math.abs(dx) + Math.abs(dy);
        eng.targetAngle = null;
        eng.angle += dx * 0.012;
        eng.tilt = Math.max(-0.45, Math.min(0.45, eng.tilt + dy * 0.002));
        eng.drag.x = e.clientX;
        eng.drag.y = e.clientY;
      } else {
        const hit = hitTestNode(eng.points, x, y, eng.filter);
        const edge = !hit ? hitTestEdge(eng.edgeSegments, x, y) : null;
        canvas.style.cursor = hit || edge ? "pointer" : "grab";
      }
    };
    const onUp = (e: PointerEvent) => {
      if (eng.drag && eng.drag.distance < 7) {
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left;
        const y = e.clientY - r.top;
        const hit = hitTestNode(eng.points, x, y, eng.filter);
        if (hit) {
          selectRef.current(hit.node.id);
        } else {
          const edge = hitTestEdge(eng.edgeSegments, x, y);
          if (edge) selectEdgeRef.current(edge.id);
        }
      }
      eng.drag = null;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      eng.zoom = Math.max(0.7, Math.min(1.6, eng.zoom - e.deltaY * 0.0008));
    };

    const onCancel = () => { eng.drag = null; };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onCancel);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("pointercancel", onCancel);
      engine.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only engine
  }, []);

  // Sync props → engine refs (no React re-render storm)
  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    const helixNodes = assignStableHelixSlots(nodes);
    const links: HelixLink[] = edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      relation: e.relation,
    }));
    if (!eng.reduced) {
      for (const n of helixNodes) {
        if (!eng.seenIds.has(n.id)) eng.births.set(n.id, eng.time);
        eng.seenIds.add(n.id);
      }
    } else {
      for (const n of helixNodes) eng.seenIds.add(n.id);
    }
    eng.nodes = helixNodes;
    eng.links = links;
    const rawById = new Map(nodes.map((n) => [n.id, n]));
    eng.filter = (n) => {
      const raw = rawById.get(n.id);
      if (!raw) return false;
      return filterPredicate ? filterPredicate(raw) : true;
    };
  }, [nodes, edges, filterPredicate]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    const changed = eng.selectedId !== selectedId;
    eng.selectedId = selectedId;
    eng.targetAngle = null;
    if (changed && selectedId && paused) {
      const n = eng.nodes.find((x) => x.id === selectedId);
      if (n) {
        const desired = focusAngleForNode(n, twist);
        const diff = shortestAngleDelta(eng.angle, desired);
        eng.targetAngle = eng.angle + diff;
        if (eng.reduced) {
          eng.angle = eng.targetAngle;
          eng.targetAngle = null;
        }
      }
    }
  }, [selectedId, paused, twist]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.selectedEdgeId = selectedEdgeId;
  }, [selectedEdgeId]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.activeIds = new Set(activeNodeIds ?? []);
  }, [activeNodeIds]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.gapIds = new Set(gapNodeIds ?? []);
  }, [gapNodeIds]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.mode = mode;
    if (eng.reduced) eng.morph = mode === "network" ? 1 : 0;
  }, [mode]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.paused = paused || reducedMotion;
  }, [paused, reducedMotion]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.speed = speed;
    eng.twist = twist;
    eng.showLabels = showLabels;
    eng.showRelations = showRelations;
    if (!showRelations) eng.edgeSegments = [];
    eng.reduced = reducedMotion;
  }, [speed, twist, showLabels, showRelations, reducedMotion]);

  useEffect(() => {
    const eng = engine.current;
    if (!eng) return;
    eng.angle = 0.6;
    eng.tilt = -0.095;
    eng.zoom = 1;
    eng.targetAngle = null;
  }, [resetToken]);

  const visible = nodes.filter((n) => (filterPredicate ? filterPredicate(n) : true));

  return (
    <div className={`lv-v2-dna-canvas-wrap ${className}`.trim()} ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className="lv-v2-dna-canvas"
        aria-label="Draaiende dubbele DNA-helix. Gebruik de kennisindex voor toetsenbordbediening."
      />
      <ul className="lv-v2-dna-a11y-list" aria-label="Kennisindex">
        {(accessibilityNodes ?? visible).map((n) => (
          <li key={n.id}>
            <button
              type="button"
              className={n.id === selectedId ? "is-selected" : undefined}
              aria-pressed={n.id === selectedId}
              onClick={() => onSelect(n.id)}
            >
              {n.label}
              <span className="lv-v2-muted"> · {n.type}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
