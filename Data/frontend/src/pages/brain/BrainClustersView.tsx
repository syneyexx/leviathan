import { useMemo, useState } from "react";
import {
  CLUSTER_DISTRIBUTION,
  CLUSTER_HEAT,
  CLUSTER_HEAT_LABELS,
  CLUSTERS,
} from "./brain-mock";
import { Donut, Heatmap, Panel } from "./brain-shared";

export function BrainClustersView({ onToast }: { onToast: (msg: string) => void }) {
  const [selectedId, setSelectedId] = useState("core");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"size" | "name">("size");

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = CLUSTERS.filter((c) => !q || c.label.toLowerCase().includes(q));
    return [...rows].sort((a, b) => (sort === "size" ? b.nodes - a.nodes : a.label.localeCompare(b.label)));
  }, [query, sort]);

  const selected = CLUSTERS.find((c) => c.id === selectedId) ?? CLUSTERS[0];

  return (
    <div className="lv-bc">
      <div className="lv-bc-grid">
        <Panel
          title="Cluster Overview"
          className="lv-bc-overview"
          action={
            <div className="lv-bc-overview-stats">
              <span>18 Total Clusters</span>
              <span>124,532 Nodes</span>
              <span>342,681 Connections</span>
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
            <select className="lv-br-select" value={sort} onChange={(e) => setSort(e.target.value as "size" | "name")}>
              <option value="size">Sort by Size</option>
              <option value="name">Sort by Name</option>
            </select>
          </div>
          <ul className="lv-bc-list">
            {list.map((cluster) => (
              <li key={cluster.id}>
                <button
                  type="button"
                  className={`lv-bc-item${selectedId === cluster.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(cluster.id)}
                >
                  <span className="lv-bc-dot" style={{ background: cluster.color }} />
                  <span>{cluster.label}</span>
                  <em>{cluster.nodes.toLocaleString()} nodes</em>
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="Cluster Visualization"
          className="lv-bc-viz"
          action={
            <div className="lv-bc-legend">
              <span>
                <i className="is-strong" /> Strong
              </span>
              <span>
                <i className="is-moderate" /> Moderate
              </span>
              <span>
                <i className="is-weak" /> Weak
              </span>
            </div>
          }
        >
          <div className="lv-bc-map" aria-label="Cluster constellation">
            <svg className="lv-bc-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {CLUSTERS.slice(1).map((c) => (
                <line
                  key={c.id}
                  x1={CLUSTERS[0].x}
                  y1={CLUSTERS[0].y}
                  x2={c.x}
                  y2={c.y}
                  stroke={`${c.color}88`}
                  strokeWidth="0.35"
                />
              ))}
            </svg>
            {CLUSTERS.map((cluster) => (
              <button
                key={cluster.id}
                type="button"
                className={`lv-bc-node${selectedId === cluster.id ? " is-active" : ""}`}
                style={{
                  left: `${cluster.x}%`,
                  top: `${cluster.y}%`,
                  width: cluster.r * 2,
                  height: cluster.r * 2,
                  borderColor: cluster.color,
                  boxShadow: `0 0 24px ${cluster.color}55`,
                  color: cluster.color,
                }}
                onClick={() => setSelectedId(cluster.id)}
              >
                <strong>{cluster.label.split(" ")[0]}</strong>
                <span>{(cluster.nodes / 1000).toFixed(1)}K</span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Cluster Details" className="lv-bc-details">
          <div className="lv-bc-detail-head">
            <span className="lv-bc-detail-icon" style={{ background: `${selected.color}22`, borderColor: selected.color }} />
            <div>
              <h3>{selected.label}</h3>
              <span className="lv-br-badge">Core Cluster</span>
            </div>
          </div>
          <p className="lv-br-desc">{selected.description}</p>
          <div className="lv-bc-metrics">
            <div>
              <strong>{selected.nodes.toLocaleString()}</strong>
              <span>Nodes</span>
            </div>
            <div>
              <strong>{selected.connections.toLocaleString()}</strong>
              <span>Connections</span>
            </div>
            <div>
              <strong>{selected.subclusters}</strong>
              <span>Sub-clusters</span>
            </div>
          </div>
          <div className="lv-bc-section">
            <div className="lv-br-panel-title">Top Concepts</div>
            <ul>
              {selected.concepts.map((concept) => (
                <li key={concept.label}>
                  <span className="lv-bc-dot" style={{ background: selected.color }} />
                  <span>{concept.label}</span>
                  <em>{concept.count.toLocaleString()}</em>
                </li>
              ))}
            </ul>
            <button type="button" className="lv-br-link" onClick={() => onToast("View All Concepts")}>
              View All Concepts →
            </button>
          </div>
          <div className="lv-bc-section">
            <div className="lv-br-panel-title">Related Clusters</div>
            <ul className="lv-bc-related">
              {selected.related.map((rel) => (
                <li key={rel.label}>
                  <div>
                    <span>{rel.label}</span>
                    <em>{rel.strength.toFixed(2)}</em>
                  </div>
                  <div className="lv-br-bar">
                    <span style={{ width: `${rel.strength * 100}%`, background: rel.color }} />
                  </div>
                </li>
              ))}
            </ul>
            <button type="button" className="lv-br-link" onClick={() => onToast("Explore Relationships")}>
              Explore Relationships →
            </button>
          </div>
        </Panel>
      </div>

      <div className="lv-bc-bottom">
        <Panel title="Cluster Distribution">
          <div className="lv-bc-donut-wrap">
            <Donut slices={[...CLUSTER_DISTRIBUTION]} center="124.5K" size={150} />
            <ul className="lv-bc-donut-legend">
              {CLUSTER_DISTRIBUTION.map((slice) => (
                <li key={slice.label}>
                  <span className="lv-bc-dot" style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <em>{slice.value}%</em>
                </li>
              ))}
            </ul>
          </div>
        </Panel>
        <Panel title="Inter-Cluster Relationships">
          <Heatmap grid={CLUSTER_HEAT} rowLabels={CLUSTER_HEAT_LABELS} colLabels={CLUSTER_HEAT_LABELS} />
        </Panel>
        <Panel title="Cluster Size Distribution">
          <div className="lv-bc-bars">
            {[...CLUSTERS]
              .sort((a, b) => b.nodes - a.nodes)
              .slice(0, 8)
              .map((cluster) => (
                <div key={cluster.id} className="lv-bc-bar-col">
                  <div
                    className="lv-bc-bar"
                    style={{
                      height: `${Math.max(12, (cluster.nodes / CLUSTERS[0].nodes) * 100)}%`,
                      background: cluster.color,
                    }}
                    title={`${cluster.label}: ${cluster.nodes.toLocaleString()}`}
                  />
                  <span>{cluster.label.split(" ")[0]}</span>
                </div>
              ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
