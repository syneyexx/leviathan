import { useState } from "react";
import {
  ANALYTICS_KPI,
  CONFIDENCE_BINS,
  EMERGING_TOPICS,
  KNOWLEDGE_GROWTH,
  LATENCY_TREND,
  NODE_TYPES,
  SEMANTIC_HEAT,
  SEMANTIC_ROWS,
  SOURCE_COMPOSITION,
} from "./brain-mock";
import { Donut, Heatmap, LineChart, Panel, Spark } from "./brain-shared";

export function BrainAnalyticsView({ onToast }: { onToast: (msg: string) => void }) {
  const [growthRange, setGrowthRange] = useState("30D");
  const [latencyRange, setLatencyRange] = useState("7D");

  return (
    <div className="lv-ba">
      <div className="lv-ba-kpi">
        {ANALYTICS_KPI.map((kpi) => (
          <article key={kpi.label} className="lv-ba-kpi-card">
            <div className="lv-ba-kpi-top">
              <span>{kpi.label}</span>
              <Spark points={kpi.spark} color={kpi.good ? "#20DC8C" : "#E45959"} width={64} height={20} />
            </div>
            <strong>{kpi.value}</strong>
            <div className="lv-ba-kpi-foot">
              <em className={kpi.good ? "is-good" : "is-bad"}>{kpi.delta}</em>
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
              {["7D", "30D", "90D", "1Y", "ALL"].map((range) => (
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
          <LineChart series={[...KNOWLEDGE_GROWTH.series]} labels={[...KNOWLEDGE_GROWTH.labels]} height={170} />
        </Panel>

        <Panel title="Source Composition">
          <div className="lv-ba-donut-wrap">
            <Donut slices={[...SOURCE_COMPOSITION]} center="124,532" size={156} />
            <ul className="lv-ba-legend">
              {SOURCE_COMPOSITION.map((slice) => (
                <li key={slice.label}>
                  <span className="lv-bc-dot" style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <em>{slice.value}%</em>
                </li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel
          title="Node Type Distribution"
          action={
            <div className="lv-ba-range">
              <button type="button" className="lv-br-chip is-active">
                Count
              </button>
              <button type="button" className="lv-br-chip">
                Percentage
              </button>
            </div>
          }
        >
          <ul className="lv-ba-bars">
            {NODE_TYPES.map((row) => (
              <li key={row.label}>
                <span>{row.label}</span>
                <div className="lv-br-bar">
                  <span style={{ width: `${row.pct}%`, background: row.color }} />
                </div>
                <em>{row.count}</em>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="lv-ba-low">
        <Panel
          title="Latency Trends"
          action={
            <div className="lv-ba-range">
              {["1H", "24H", "7D", "30D"].map((range) => (
                <button
                  key={range}
                  type="button"
                  className={`lv-br-chip${latencyRange === range ? " is-active" : ""}`}
                  onClick={() => setLatencyRange(range)}
                >
                  {range}
                </button>
              ))}
            </div>
          }
        >
          <LineChart series={[...LATENCY_TREND.series]} labels={[...LATENCY_TREND.labels]} height={150} />
        </Panel>

        <Panel title="Confidence Distribution">
          <div className="lv-ba-hist">
            {CONFIDENCE_BINS.map((value, i) => (
              <div key={i} className="lv-ba-hist-col">
                <div
                  className="lv-ba-hist-bar"
                  style={{
                    height: `${value}%`,
                    background: `linear-gradient(180deg, #F0C875, #20DC8C)`,
                    opacity: 0.45 + i * 0.05,
                  }}
                />
              </div>
            ))}
          </div>
          <div className="lv-ba-hist-meta">
            <span>0.0</span>
            <strong>Avg: 0.916</strong>
            <span>1.0</span>
          </div>
        </Panel>

        <Panel title="Semantic Heatmap">
          <Heatmap
            grid={SEMANTIC_HEAT}
            rowLabels={SEMANTIC_ROWS}
            colLabels={["Aug 18", "Aug 25", "Sep 1", "Sep 8", "Sep 15"]}
          />
        </Panel>
      </div>

      <footer className="lv-ba-footer">
        <div className="lv-ba-insights">
          <div className="lv-br-panel-title">Insights</div>
          <p className="is-good">↑ +12.4% Node growth accelerating</p>
          <p className="is-good">✓ 94.2% Retrieval quality stable</p>
          <p className="is-good">↓ −18.7% Latency improved</p>
        </div>
        <div className="lv-ba-emerging">
          <div className="lv-br-panel-title">Top Emerging Topics</div>
          <ol>
            {EMERGING_TOPICS.map((topic) => (
              <li key={topic.label}>
                <span>
                  {topic.rank}. {topic.label}
                </span>
                <em className="is-good">{topic.delta}</em>
              </li>
            ))}
          </ol>
        </div>
        <button type="button" className="lv-br-btn is-gold" onClick={() => onToast("View All Analytics")}>
          View All Analytics →
        </button>
      </footer>
    </div>
  );
}
