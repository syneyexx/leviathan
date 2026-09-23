import { useMemo, useState } from "react";
import { buildClusters, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Donut, Panel } from "./brain-shared";

export function BrainClustersView({
  nodes,
  edges,
}: {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  onToast?: (msg: string) => void;
}) {
  const clusters = useMemo(() => buildClusters(nodes, edges), [nodes, edges]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"size" | "name">("size");

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = clusters.filter((c) => !q || c.label.toLowerCase().includes(q));
    return [...rows].sort((a, b) => (sort === "size" ? b.nodes - a.nodes : a.label.localeCompare(b.label)));
  }, [clusters, query, sort]);

  const selected = clusters.find((c) => c.id === selectedId) ?? clusters[0] ?? null;
  const donut = clusters.slice(0, 8).map((c) => ({ value: c.nodes, color: c.color, label: c.label }));

  return (
    <div className="lv-bc">
      <div className="lv-bc-grid">
        <Panel
          title="Cluster Overview"
          className="lv-bc-overview"
          action={
            <div className="lv-bc-overview-stats">
              <span>{clusters.length} type clusters</span>
              <span>{nodes.length} nodes</span>
              <span>{edges.length} edges</span>
            </div>
          }
        >
          <div className="lv-bc-overview-tools">
            <input
              className="lv-br-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search clusters..."
              aria-label="Search clusters"
            />
            <select
              className="lv-br-select"
              value={sort}
              onChange={(e) => setSort(e.target.value as "size" | "name")}
            >
              <option value="size">Sort by Size</option>
              <option value="name">Sort by Name</option>
            </select>
          </div>
          {list.length === 0 ? (
            <p className="lv-br-muted">No clusters — empty projection.</p>
          ) : (
            <ul className="lv-bc-list">
              {list.map((cluster) => (
                <li key={cluster.id}>
                  <button
                    type="button"
                    className={`lv-bc-item${selected?.id === cluster.id ? " is-active" : ""}`}
                    onClick={() => setSelectedId(cluster.id)}
                  >
                    <span className="lv-bc-dot" style={{ background: cluster.color }} />
                    <span>{cluster.label}</span>
                    <em>{cluster.nodes.toLocaleString()} nodes</em>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Cluster Visualization" className="lv-bc-viz">
          {donut.length === 0 ? (
            <p className="lv-br-muted">Nothing to visualize.</p>
          ) : (
            <div className="lv-bc-viz-body">
              <Donut slices={donut} center={String(nodes.length)} size={180} />
              <ul className="lv-bc-bubbles">
                {list.slice(0, 12).map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="lv-bc-bubble"
                      style={{
                        background: `${c.color}33`,
                        borderColor: c.color,
                        width: 48 + Math.min(80, c.nodes * 4),
                        height: 48 + Math.min(80, c.nodes * 4),
                      }}
                      onClick={() => setSelectedId(c.id)}
                    >
                      <strong>{c.nodes}</strong>
                      <span>{c.label.split(".").pop()}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>

        <Panel title="Cluster Detail" className="lv-bc-detail">
          {!selected ? (
            <p className="lv-br-muted">Select a cluster.</p>
          ) : (
            <>
              <h3>{selected.label}</h3>
              <p className="lv-br-muted">{selected.nodes} nodes in this type cluster</p>
              <ul className="lv-bc-sample">
                {selected.sample.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
