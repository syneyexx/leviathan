import { useMemo, useState } from "react";
import { buildAnalytics, colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Donut, LineChart, Panel } from "./brain-shared";

export function BrainAnalyticsView({
  nodes,
  edges,
  stats,
}: {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  stats?: Record<string, unknown> | null;
  onToast?: (msg: string) => void;
}) {
  const analytics = useMemo(() => buildAnalytics(nodes, edges, stats ?? null), [nodes, edges, stats]);
  const [growthRange, setGrowthRange] = useState("ALL");

  const growth = useMemo(() => {
    if (growthRange === "ALL") return analytics.growth;
    const n = growthRange === "7D" ? 7 : growthRange === "30D" ? 30 : 90;
    return {
      labels: analytics.growth.labels.slice(-n),
      series: analytics.growth.series.slice(-n),
    };
  }, [analytics.growth, growthRange]);

  const kpis = [
    { label: "Nodes", value: String(analytics.nodeCount), sub: "projection" },
    { label: "Edges", value: String(analytics.edgeCount), sub: "relations" },
    { label: "Types", value: String(analytics.typeCount), sub: "domains" },
    {
      label: "Relations",
      value: String(analytics.relations.length),
      sub: "distinct",
    },
  ];

  return (
    <div className="lv-ba">
      <div className="lv-ba-kpi">
        {kpis.map((kpi) => (
          <article key={kpi.label} className="lv-ba-kpi-card">
            <div className="lv-ba-kpi-top">
              <span>{kpi.label}</span>
            </div>
            <strong>{kpi.value}</strong>
            <div className="lv-ba-kpi-foot">
              <span>{kpi.sub}</span>
            </div>
          </article>
        ))}
      </div>

      <div className="lv-ba-mid">
        <Panel
          title="Knowledge Growth"
          action={
            <div className="lv-ba-range">
              {["7D", "30D", "90D", "ALL"].map((range) => (
                <button
                  key={range}
                  type="button"
                  className={`lv-br-chip${growthRange === range ? " is-active" : ""}`}
                  onClick={() => setGrowthRange(range)}
                >
                  {range}
                </button>
              ))}
            </div>
          }
        >
          {growth.labels.length === 0 ? (
            <p className="lv-br-muted">No dated nodes for growth series.</p>
          ) : (
            <LineChart
              series={[{ name: "nodes", color: "#22C9D6", values: [...growth.series] }]}
              labels={[...growth.labels]}
              height={170}
            />
          )}
        </Panel>

        <Panel title="Type Composition">
          <div className="lv-ba-donut-wrap">
            <Donut
              slices={analytics.composition.map((c) => ({ value: c.count, color: c.color }))}
              center={String(analytics.nodeCount)}
              size={156}
            />
            <ul className="lv-ba-legend">
              {analytics.composition.map((slice) => (
                <li key={slice.label}>
                  <span className="lv-bc-dot" style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <em>
                    {slice.count} · {slice.value}%
                  </em>
                </li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel title="Node Type Distribution">
          {analytics.typeEntries.length === 0 ? (
            <p className="lv-br-muted">Empty projection.</p>
          ) : (
            <ul className="lv-ba-bars">
              {analytics.typeEntries.map(([type, count]) => (
                <li key={type}>
                  <span>{type}</span>
                  <div className="lv-ba-bar-track">
                    <i
                      style={{
                        width: `${Math.max(4, (count / Math.max(analytics.nodeCount, 1)) * 100)}%`,
                        background: colorForType(type),
                      }}
                    />
                  </div>
                  <em>{count}</em>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Relation counts">
        {analytics.relations.length === 0 ? (
          <p className="lv-br-muted">No edges in this projection.</p>
        ) : (
          <ul className="lv-ba-legend">
            {analytics.relations.map(([rel, count]) => (
              <li key={rel}>
                <span>{rel}</span>
                <em>{count}</em>
              </li>
            ))}
          </ul>
        )}
        <p className="lv-br-muted" style={{ marginTop: 8, fontSize: 11 }}>
          Analytics derived from live /api/brain/graph — not decorative fixtures.
        </p>
      </Panel>
    </div>
  );
}
