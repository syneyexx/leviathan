import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type BrainNode = {
  id: string;
  type: string;
  label: string;
  created_at?: string | null;
  meta?: Record<string, unknown>;
};

type BrainEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

const TYPE_COLORS: Record<string, string> = {
  "knowledge.document": "#F0C875",
  evidence: "#22C9D6",
  "research.project": "#D6A957",
  dataset: "#E45959",
  module: "#9B8CFF",
  capability: "#DB8A34",
  "mcp.server": "#4285E8",
  "mcp.tool": "#60A5FA",
  workflow: "#20DC8C",
  atlas: "#F472B6",
  run: "#94A3B8",
};

function colorFor(type: string): string {
  return TYPE_COLORS[type] || "#A1A1AA";
}

function deepLink(node: BrainNode): string | null {
  if (node.type === "knowledge.document") return `/knowledge`;
  if (node.type === "evidence") return `/evidence?evidence=${encodeURIComponent(node.id.replace(/^evidence:/, ""))}`;
  if (node.type === "research.project")
    return `/research?project=${encodeURIComponent(node.id.replace(/^research:project:/, ""))}`;
  if (node.type === "dataset") return `/datasets?dataset=${encodeURIComponent(node.id.replace(/^dataset:/, ""))}`;
  if (node.type === "module") return `/modules?module=${encodeURIComponent(node.id.replace(/^module:/, ""))}`;
  if (node.type.startsWith("mcp.")) return `/mcp`;
  if (node.type === "workflow") return `/workflows`;
  if (node.type === "capability") return `/tools`;
  return null;
}

export function BrainPage() {
  const toast = useAppToast();
  const [nodes, setNodes] = useState<BrainNode[]>([]);
  const [edges, setEdges] = useState<BrainEdge[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "tree" | "timeline" | "analytics">("graph");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.brainGraph({
        limit: 200,
        q: q.trim() || undefined,
        types: typeFilter || undefined,
      });
      setNodes(data.nodes);
      setEdges(data.edges);
      setStats(data.stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Brain graph unavailable");
      setNodes([]);
      setEdges([]);
    } finally {
      setLoading(false);
    }
  }, [q, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(() => nodes.find((n) => n.id === selectedId) ?? null, [nodes, selectedId]);

  const layout = useMemo(() => {
    // Deterministic circular/grid layout — no fake physics loop
    const w = 900;
    const h = 520;
    const cx = w / 2;
    const cy = h / 2;
    const byType = new Map<string, BrainNode[]>();
    for (const n of nodes) {
      const list = byType.get(n.type) ?? [];
      list.push(n);
      byType.set(n.type, list);
    }
    const types = Array.from(byType.keys());
    const positions = new Map<string, { x: number; y: number; r: number; color: string }>();
    types.forEach((type, ti) => {
      const group = byType.get(type) ?? [];
      const ring = 80 + ti * 45;
      group.forEach((n, i) => {
        const angle = (i / Math.max(group.length, 1)) * Math.PI * 2 + ti * 0.3;
        positions.set(n.id, {
          x: cx + Math.cos(angle) * ring,
          y: cy + Math.sin(angle) * ring * 0.72,
          r: 8 + Math.min(10, (n.label?.length || 4) / 6),
          color: colorFor(n.type),
        });
      });
    });
    return { w, h, positions };
  }, [nodes]);

  const typeCounts = (stats?.by_type as Record<string, number> | undefined) ?? {};
  const typeOptions = Object.keys(typeCounts).sort();

  const timeline = useMemo(() => {
    return [...nodes]
      .filter((n) => n.created_at)
      .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
      .slice(-40)
      .reverse();
  }, [nodes]);

  const treeGroups = useMemo(() => {
    const groups: Record<string, BrainNode[]> = {};
    for (const n of nodes) {
      const key = n.type.split(".")[0];
      groups[key] = groups[key] ?? [];
      groups[key].push(n);
    }
    return groups;
  }, [nodes]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Brain Mode"
      searchPlaceholder="Search brain graph…"
      systemItems={["LLM", "Neural", "Memory", "Runtime"]}
      layout="wide"
    >
      <main className="lv-main" style={{ padding: "1.25rem", display: "grid", gap: "1rem" }}>
        <header style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0 }}>Brain</h1>
            <p style={{ opacity: 0.75, margin: "0.35rem 0 0" }}>
              Bounded projection over Knowledge, Evidence, Research, Datasets, and Runtime — not a second database.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter…"
              onKeyDown={(e) => {
                if (e.key === "Enter") void load();
              }}
            />
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {typeOptions.map((t) => (
                <option key={t} value={t}>
                  {t} ({typeCounts[t]})
                </option>
              ))}
            </select>
            <button type="button" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </header>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          {(["graph", "tree", "timeline", "analytics"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              style={{ fontWeight: view === v ? 700 : 400 }}
            >
              {v}
            </button>
          ))}
          <span style={{ marginLeft: "auto", opacity: 0.7 }}>
            {loading ? "Loading…" : `${nodes.length} nodes · ${edges.length} edges`}
          </span>
        </div>

        {error ? <div role="alert">{error}</div> : null}

        {view === "graph" ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: "1rem" }}>
            <svg viewBox={`0 0 ${layout.w} ${layout.h}`} width="100%" style={{ background: "rgba(0,0,0,0.25)", borderRadius: 8 }}>
              {edges.map((e) => {
                const a = layout.positions.get(e.source);
                const b = layout.positions.get(e.target);
                if (!a || !b) return null;
                return (
                  <line
                    key={e.id}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="rgba(255,255,255,0.18)"
                    strokeWidth={1}
                  />
                );
              })}
              {nodes.map((n) => {
                const p = layout.positions.get(n.id);
                if (!p) return null;
                return (
                  <g key={n.id} onClick={() => setSelectedId(n.id)} style={{ cursor: "pointer" }}>
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={p.r}
                      fill={p.color}
                      opacity={selectedId === n.id ? 1 : 0.85}
                      stroke={selectedId === n.id ? "#fff" : "transparent"}
                      strokeWidth={2}
                    />
                    <title>{`${n.label} (${n.type})`}</title>
                  </g>
                );
              })}
            </svg>
            <aside>
              <h3>Node detail</h3>
              {!selected ? (
                <p>Select a node</p>
              ) : (
                <div style={{ display: "grid", gap: "0.4rem" }}>
                  <strong>{selected.label}</strong>
                  <div style={{ fontSize: "0.85rem", opacity: 0.75 }}>{selected.id}</div>
                  <div>Type: {selected.type}</div>
                  <div>Created: {selected.created_at || "—"}</div>
                  <pre style={{ fontSize: "0.75rem", overflow: "auto" }}>
                    {JSON.stringify(selected.meta ?? {}, null, 2)}
                  </pre>
                  {deepLink(selected) ? (
                    <Link to={deepLink(selected)!}>Open authoritative page</Link>
                  ) : null}
                </div>
              )}
              {!loading && nodes.length === 0 ? (
                <p>No entities yet — ingest knowledge, run research, or connect MCP.</p>
              ) : null}
            </aside>
          </div>
        ) : null}

        {view === "tree" ? (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {Object.entries(treeGroups).map(([group, items]) => (
              <details key={group} open>
                <summary>
                  {group} ({items.length})
                </summary>
                <ul>
                  {items.map((n) => (
                    <li key={n.id}>
                      <button type="button" onClick={() => setSelectedId(n.id)}>
                        {n.label} <span style={{ opacity: 0.6 }}>{n.type}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        ) : null}

        {view === "timeline" ? (
          <ul>
            {timeline.length === 0 ? <li>No timestamped entities</li> : null}
            {timeline.map((n) => (
              <li key={n.id}>
                <code>{n.created_at}</code> — {n.label} ({n.type})
              </li>
            ))}
          </ul>
        ) : null}

        {view === "analytics" ? (
          <div>
            <h3>Graph statistics</h3>
            <pre>{JSON.stringify(stats, null, 2)}</pre>
            <p style={{ opacity: 0.7 }}>
              Counts are from the bounded projection response, not invented neuroscience metrics.
            </p>
            <button
              type="button"
              onClick={() => {
                toast("Brain is a read projection — use Knowledge/Research/Datasets to mutate.");
              }}
            >
              Add Node (disabled — use authoritative pages)
            </button>
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}
