/**
 * Workflow canvas editor — DOM/SVG graph (no reactflow).
 * Pan/zoom/fit, minimap, palette drag, node move, edge connect, select/delete.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { WorkflowGraph, WorkflowGraphEdge, WorkflowGraphNode, WorkflowLayoutNode, WorkflowPalette } from "../../types/api";

const NODE_W = 148;
const NODE_H = 56;
const COND_W = 120;
const COND_H = 72;

type Props = {
  graph: WorkflowGraph;
  layout: WorkflowLayoutNode[];
  palette: WorkflowPalette | null;
  readOnly?: boolean;
  onChange: (graph: WorkflowGraph, layout: WorkflowLayoutNode[]) => void;
};

type Cam = { x: number; y: number; scale: number };

function nodeTone(kind: string): string {
  const k = kind.toLowerCase();
  if (k.includes("agent")) return "agent";
  if (k.includes("condition") || k.includes("control")) return "condition";
  if (k.includes("data") || k.includes("transform")) return "data";
  if (k.includes("trigger")) return "trigger";
  if (k.includes("notify")) return "notify";
  return "tool";
}

function layoutMap(layout: WorkflowLayoutNode[]): Record<string, { x: number; y: number }> {
  const m: Record<string, { x: number; y: number }> = {};
  for (const n of layout) m[n.node_id] = { x: n.x, y: n.y };
  return m;
}

function ensureLayout(graph: WorkflowGraph, layout: WorkflowLayoutNode[]): WorkflowLayoutNode[] {
  const map = layoutMap(layout);
  const next = [...layout];
  let i = 0;
  for (const node of graph.nodes) {
    if (!map[node.node_id]) {
      next.push({ node_id: node.node_id, x: 40 + (i % 4) * 180, y: 40 + Math.floor(i / 4) * 100 });
      i += 1;
    }
  }
  return next;
}

function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export function WorkflowsCanvas({ graph, layout, palette, readOnly, onChange }: Props) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [cam, setCam] = useState<Cam>({ x: 20, y: 20, scale: 0.85 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState<Record<string, boolean>>({
    Agents: true,
    Tools: true,
    Data: true,
    Control: true,
  });
  const dragRef = useRef<{
    mode: "pan" | "node";
    nodeId?: string;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    camX: number;
    camY: number;
  } | null>(null);

  const positions = useMemo(() => layoutMap(ensureLayout(graph, layout)), [graph, layout]);

  const fit = useCallback(() => {
    const el = viewportRef.current;
    if (!el || graph.nodes.length === 0) {
      setCam({ x: 20, y: 20, scale: 0.85 });
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of graph.nodes) {
      const p = positions[n.node_id] ?? { x: 0, y: 0 };
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + NODE_H);
    }
    const pad = 48;
    const bw = maxX - minX + pad * 2;
    const bh = maxY - minY + pad * 2;
    const vw = el.clientWidth || 400;
    const vh = el.clientHeight || 280;
    const scale = Math.max(0.4, Math.min(1.2, Math.min(vw / bw, vh / bh)));
    setCam({
      x: (vw - bw * scale) / 2 - (minX - pad) * scale,
      y: (vh - bh * scale) / 2 - (minY - pad) * scale,
      scale,
    });
  }, [graph.nodes, positions]);

  useEffect(() => {
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph.nodes.length]);

  const commitLayout = useCallback(
    (nextLayout: WorkflowLayoutNode[]) => {
      onChange(graph, nextLayout);
    },
    [graph, onChange],
  );

  const commitGraph = useCallback(
    (nextGraph: WorkflowGraph, nextLayout?: WorkflowLayoutNode[]) => {
      onChange(nextGraph, nextLayout ?? ensureLayout(nextGraph, layout));
    },
    [layout, onChange],
  );

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.08 : 0.08;
    setCam((c) => ({ ...c, scale: Math.max(0.35, Math.min(1.8, c.scale + delta)) }));
  }, []);

  const onPointerDownBg = (e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest(".lv-v2-wf-node") || target.closest(".lv-v2-wf-canvas__chrome")) return;
    setSelectedId(null);
    setConnectFrom(null);
    dragRef.current = {
      mode: "pan",
      startX: e.clientX,
      startY: e.clientY,
      origX: 0,
      origY: 0,
      camX: cam.x,
      camY: cam.y,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    if (d.mode === "pan") {
      setCam((c) => ({
        ...c,
        x: d.camX + (e.clientX - d.startX),
        y: d.camY + (e.clientY - d.startY),
      }));
      return;
    }
    if (d.mode === "node" && d.nodeId && !readOnly) {
      const dx = (e.clientX - d.startX) / cam.scale;
      const dy = (e.clientY - d.startY) / cam.scale;
      const next = ensureLayout(graph, layout).map((n) =>
        n.node_id === d.nodeId ? { ...n, x: d.origX + dx, y: d.origY + dy } : n,
      );
      commitLayout(next);
    }
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  const startNodeDrag = (nodeId: string, e: ReactPointerEvent) => {
    if (readOnly) return;
    e.stopPropagation();
    setSelectedId(nodeId);
    const p = positions[nodeId] ?? { x: 0, y: 0 };
    dragRef.current = {
      mode: "node",
      nodeId,
      startX: e.clientX,
      startY: e.clientY,
      origX: p.x,
      origY: p.y,
      camX: cam.x,
      camY: cam.y,
    };
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const addFromPalette = (item: Record<string, unknown>) => {
    if (readOnly) return;
    const kind = String(item.kind || "tool");
    const label = String(item.label || item.id || "Node");
    const nodeId = uid("n");
    const node: WorkflowGraphNode = {
      node_id: nodeId,
      kind,
      label,
      config: {
        capability_id: item.capability_id || item.id,
        ...((item.config as Record<string, unknown>) || {}),
      },
    };
    const nextGraph: WorkflowGraph = { nodes: [...graph.nodes, node], edges: [...graph.edges] };
    const base = ensureLayout(graph, layout);
    const nextLayout = [
      ...base,
      { node_id: nodeId, x: 80 + (base.length % 3) * 160, y: 80 + Math.floor(base.length / 3) * 90 },
    ];
    commitGraph(nextGraph, nextLayout);
    setSelectedId(nodeId);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    if (readOnly) return;
    const raw = e.dataTransfer.getData("application/x-lv-wf-palette");
    if (!raw) return;
    try {
      addFromPalette(JSON.parse(raw) as Record<string, unknown>);
    } catch {
      /* ignore */
    }
  };

  const toggleConnect = (nodeId: string) => {
    if (readOnly) return;
    if (!connectFrom) {
      setConnectFrom(nodeId);
      return;
    }
    if (connectFrom === nodeId) {
      setConnectFrom(null);
      return;
    }
    const edge: WorkflowGraphEdge = {
      edge_id: uid("e"),
      source: connectFrom,
      target: nodeId,
    };
    commitGraph({ nodes: graph.nodes, edges: [...graph.edges, edge] });
    setConnectFrom(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (readOnly) return;
      if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        e.preventDefault();
        const nextNodes = graph.nodes.filter((n) => n.node_id !== selectedId);
        const nextEdges = graph.edges.filter((ed) => ed.source !== selectedId && ed.target !== selectedId);
        const nextLayout = layout.filter((n) => n.node_id !== selectedId);
        commitGraph({ nodes: nextNodes, edges: nextEdges }, nextLayout);
        setSelectedId(null);
      }
      if (e.key === "Escape") {
        setConnectFrom(null);
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commitGraph, graph.edges, graph.nodes, layout, readOnly, selectedId]);

  const edgePaths = useMemo(() => {
    return graph.edges.map((edge) => {
      const s = positions[edge.source] ?? { x: 0, y: 0 };
      const t = positions[edge.target] ?? { x: 0, y: 0 };
      const x1 = s.x + NODE_W;
      const y1 = s.y + NODE_H / 2;
      const x2 = t.x;
      const y2 = t.y + NODE_H / 2;
      const mx = (x1 + x2) / 2;
      const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
      return { edge, d, labelX: mx, labelY: (y1 + y2) / 2 };
    });
  }, [graph.edges, positions]);

  const paletteGroups = useMemo(() => {
    if (!palette) return [] as Array<{ key: string; items: Array<Record<string, unknown>> }>;
    return (["Agents", "Tools", "Data", "Control"] as const).map((key) => ({
      key,
      items: (palette[key] ?? []) as Array<Record<string, unknown>>,
    }));
  }, [palette]);

  // Minimap bounds
  const mini = useMemo(() => {
    let minX = 0;
    let minY = 0;
    let maxX = 400;
    let maxY = 240;
    if (graph.nodes.length) {
      minX = Infinity;
      minY = Infinity;
      maxX = -Infinity;
      maxY = -Infinity;
      for (const n of graph.nodes) {
        const p = positions[n.node_id] ?? { x: 0, y: 0 };
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + NODE_W);
        maxY = Math.max(maxY, p.y + NODE_H);
      }
    }
    return { minX, minY, maxX, maxY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) };
  }, [graph.nodes, positions]);

  return (
    <div className="lv-v2-wf-canvas" aria-label="Workflow canvas">
      <aside className="lv-v2-wf-palette" aria-label="Node palette">
        {paletteGroups.map((group) => (
          <div key={group.key} className="lv-v2-wf-palette__group">
            <button
              type="button"
              className="lv-v2-wf-palette__head"
              onClick={() => setPaletteOpen((p) => ({ ...p, [group.key]: !p[group.key] }))}
            >
              <span>{paletteOpen[group.key] ? "▾" : "▸"}</span> {group.key}
            </button>
            {paletteOpen[group.key] ? (
              <ul className="lv-v2-wf-palette__list">
                {group.items.length === 0 ? (
                  <li className="lv-v2-wf-palette__empty">Geen items</li>
                ) : (
                  group.items.map((item) => {
                    const id = String(item.id || item.label);
                    return (
                      <li key={id}>
                        <button
                          type="button"
                          className="lv-v2-wf-palette__item"
                          draggable={!readOnly}
                          onDragStart={(e) => {
                            e.dataTransfer.setData(
                              "application/x-lv-wf-palette",
                              JSON.stringify(item),
                            );
                            e.dataTransfer.effectAllowed = "copy";
                          }}
                          onClick={() => addFromPalette(item)}
                          disabled={readOnly || item.available === false}
                          title={String(item.reason || item.label || id)}
                        >
                          {String(item.label || id)}
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            ) : null}
          </div>
        ))}
      </aside>

      <div
        ref={viewportRef}
        className="lv-v2-wf-canvas__viewport"
        onWheel={onWheel}
        onPointerDown={onPointerDownBg}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <div
          className="lv-v2-wf-canvas__world"
          style={{
            transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.scale})`,
          }}
        >
          <svg className="lv-v2-wf-canvas__edges" aria-hidden="true">
            {edgePaths.map(({ edge, d, labelX, labelY }) => (
              <g key={edge.edge_id}>
                <path d={d} className="lv-v2-wf-edge" markerEnd="url(#lv-wf-arrow)" />
                {edge.label ? (
                  <text x={labelX} y={labelY - 6} className="lv-v2-wf-edge__label" textAnchor="middle">
                    {edge.label}
                  </text>
                ) : null}
              </g>
            ))}
            <defs>
              <marker
                id="lv-wf-arrow"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
              </marker>
            </defs>
          </svg>

          {graph.nodes.map((node) => {
            const p = positions[node.node_id] ?? { x: 0, y: 0 };
            const tone = nodeTone(node.kind);
            const isCond = tone === "condition";
            const selected = selectedId === node.node_id;
            const connecting = connectFrom === node.node_id;
            return (
              <div
                key={node.node_id}
                className={`lv-v2-wf-node is-${tone}${selected ? " is-selected" : ""}${connecting ? " is-connecting" : ""}`}
                style={{
                  left: p.x,
                  top: p.y,
                  width: isCond ? COND_W : NODE_W,
                  minHeight: isCond ? COND_H : NODE_H,
                }}
                onPointerDown={(e) => startNodeDrag(node.node_id, e)}
                onDoubleClick={() => toggleConnect(node.node_id)}
                role="button"
                tabIndex={0}
                aria-label={node.label || node.node_id}
              >
                <div className="lv-v2-wf-node__head">{node.kind}</div>
                <div className="lv-v2-wf-node__label">{node.label || node.node_id}</div>
                {isCond && node.config?.expression ? (
                  <div className="lv-v2-wf-node__sub">{String(node.config.expression)}</div>
                ) : null}
                <button
                  type="button"
                  className="lv-v2-wf-node__port is-out"
                  title="Verbinden"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleConnect(node.node_id);
                  }}
                  disabled={readOnly}
                />
                <button
                  type="button"
                  className="lv-v2-wf-node__port is-in"
                  title="Verbind hierheen"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleConnect(node.node_id);
                  }}
                  disabled={readOnly}
                />
              </div>
            );
          })}
        </div>

        <div className="lv-v2-wf-canvas__chrome">
          <div className="lv-v2-wf-minimap" aria-hidden="true">
            <svg viewBox={`${mini.minX - 20} ${mini.minY - 20} ${mini.w + 40} ${mini.h + 40}`}>
              {graph.nodes.map((n) => {
                const p = positions[n.node_id] ?? { x: 0, y: 0 };
                return (
                  <rect
                    key={n.node_id}
                    x={p.x}
                    y={p.y}
                    width={40}
                    height={18}
                    rx={2}
                    className={`lv-v2-wf-minimap__node is-${nodeTone(n.kind)}`}
                  />
                );
              })}
            </svg>
          </div>
          <div className="lv-v2-wf-zoom" role="group" aria-label="Zoom">
            <button type="button" onClick={() => setCam((c) => ({ ...c, scale: Math.min(1.8, c.scale + 0.1) }))}>
              +
            </button>
            <button type="button" onClick={() => setCam((c) => ({ ...c, scale: Math.max(0.35, c.scale - 0.1) }))}>
              −
            </button>
            <button type="button" onClick={fit} title="Passend">
              ⤢
            </button>
          </div>
        </div>

        {connectFrom ? (
          <p className="lv-v2-wf-canvas__hint" role="status">
            Selecteer een doelnode om te verbinden (Esc annuleert)
          </p>
        ) : null}
      </div>
    </div>
  );
}
