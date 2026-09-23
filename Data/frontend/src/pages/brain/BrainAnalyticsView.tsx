import { useMemo, useState } from "react";
import { buildAnalytics, colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Donut, Heatmap, LineChart, Panel, Spark } from "./brain-shared";

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function pretty(value: string): string {
  return value.split(/[._-]+/g).filter(Boolean).map((part) => part.length <= 3 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`).join(" ");
}

function numericMeta(node: LiveBrainNode, keys: string[]): number | null {
  for (const key of keys) {
    const raw = node.meta?.[key];
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    if (typeof raw === "string" && raw.trim() && Number.isFinite(Number(raw))) return Number(raw);
  }
  return null;
}

function movingSpark(values: readonly number[]): number[] {
  if (values.length >= 8) return values.slice(-12);
  if (values.length > 1) return values.slice();
  return [];
}

export function BrainAnalyticsView({ nodes, edges, stats }: { nodes: LiveBrainNode[]; edges: LiveBrainEdge[]; stats?: Record<string, unknown> | null; onToast?: (msg: string) => void }) {
  const analytics = useMemo(() => buildAnalytics(nodes, edges, stats ?? null), [nodes, edges, stats]);
  const [growthRange, setGrowthRange] = useState("30D");

  const degree = useMemo(() => {
    const map = new Map<string, number>();
    for (const edge of edges) {
      map.set(edge.source, (map.get(edge.source) ?? 0) + 1);
      map.set(edge.target, (map.get(edge.target) ?? 0) + 1);
    }
    return map;
  }, [edges]);

  const connectedNodes = useMemo(() => [...degree.values()].filter((value) => value > 0).length, [degree]);
  const averageDegree = nodes.length ? (edges.length * 2) / nodes.length : 0;
  const density = nodes.length > 1 ? (edges.length / ((nodes.length * (nodes.length - 1)) / 2)) * 100 : 0;
  const connectedPercent = nodes.length ? (connectedNodes / nodes.length) * 100 : 0;

  const datedSeries = useMemo(() => {
    const bucket = new Map<string, number>();
    for (const node of nodes) {
      if (!node.created_at) continue;
      const key = String(node.created_at).slice(0, 10);
      bucket.set(key, (bucket.get(key) ?? 0) + 1);
    }
    const labels = [...bucket.keys()].sort();
    let running = 0;
    const cumulative = labels.map((label) => { running += bucket.get(label) ?? 0; return running; });
    const daily = labels.map((label) => bucket.get(label) ?? 0);
    return { labels, cumulative, daily };
  }, [nodes]);

  const rangeSize = growthRange === "7D" ? 7 : growthRange === "30D" ? 30 : growthRange === "90D" ? 90 : Number.POSITIVE_INFINITY;
  const growth = useMemo(() => {
    const start = Number.isFinite(rangeSize) ? Math.max(0, datedSeries.labels.length - rangeSize) : 0;
    return { labels: datedSeries.labels.slice(start), cumulative: datedSeries.cumulative.slice(start), daily: datedSeries.daily.slice(start) };
  }, [datedSeries, rangeSize]);

  const confidenceValues = useMemo(() => nodes.map((node) => numericMeta(node, ["confidence", "confidence_score", "score"])).filter((value): value is number => value != null).map((value) => value > 1 ? Math.min(1, value / 100) : Math.max(0, value)), [nodes]);
  const latencyValues = useMemo(() => nodes.map((node) => numericMeta(node, ["latency_ms", "query_latency_ms", "duration_ms"])).filter((value): value is number => value != null && value >= 0), [nodes]);
  const averageConfidence = confidenceValues.length ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length : null;
  const averageLatency = latencyValues.length ? latencyValues.reduce((sum, value) => sum + value, 0) / latencyValues.length : null;

  const memoryNodes = useMemo(() => nodes.filter((node) => node.type === "memory"), [nodes]);
  const memoryGrowth = useMemo(() => {
    const now = Date.now();
    const recent = memoryNodes.filter((node) => node.created_at && now - new Date(node.created_at).getTime() <= 30 * 86400000).length;
    const previous = memoryNodes.filter((node) => node.created_at && now - new Date(node.created_at).getTime() > 30 * 86400000 && now - new Date(node.created_at).getTime() <= 60 * 86400000).length;
    if (!memoryNodes.length) return null;
    if (!previous) return recent ? 100 : 0;
    return ((recent - previous) / previous) * 100;
  }, [memoryNodes]);

  const typeRows = useMemo(() => analytics.typeEntries.slice(0, 12), [analytics.typeEntries]);
  const composition = useMemo(() => analytics.composition.map((slice) => ({ ...slice, label: pretty(slice.label) })), [analytics.composition]);

  const confidenceHistogram = useMemo(() => {
    const bins = Array.from({ length: 10 }, () => 0);
    for (const value of confidenceValues) bins[Math.min(9, Math.floor(value * 10))] += 1;
    return bins;
  }, [confidenceValues]);

  const heatmapData = useMemo(() => {
    const types = typeRows.slice(0, 8).map(([type]) => type);
    const index = new Map(types.map((type, i) => [type, i]));
    const nodeType = new Map(nodes.map((node) => [node.id, node.type]));
    const raw = types.map(() => types.map(() => 0));
    let max = 1;
    for (const edge of edges) {
      const a = index.get(nodeType.get(edge.source) ?? "");
      const b = index.get(nodeType.get(edge.target) ?? "");
      if (a == null || b == null) continue;
      raw[a][b] += 1;
      if (a !== b) raw[b][a] += 1;
      max = Math.max(max, raw[a][b], raw[b][a]);
    }
    return { types, grid: raw.map((row) => row.map((value) => value / max)) };
  }, [edges, nodes, typeRows]);

  const emergingTopics = useMemo(() => {
    const stop = new Set(["the", "and", "for", "with", "from", "this", "that", "into", "node", "data", "live"]);
    const recent = [...nodes].filter((node) => node.created_at).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, Math.max(10, Math.ceil(nodes.length * 0.35)));
    const counts = new Map<string, number>();
    for (const node of recent) {
      for (const word of node.label.toLowerCase().split(/[^a-z0-9]+/g)) {
        if (word.length < 4 || stop.has(word)) continue;
        counts.set(word, (counts.get(word) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6);
  }, [nodes]);

  const kpis = [
    { label: "Total Nodes", value: formatCount(analytics.nodeCount), note: `${formatCount(datedSeries.daily.slice(-30).reduce((sum, value) => sum + value, 0))} dated nodes (30d)`, spark: movingSpark(datedSeries.cumulative), delta: null },
    { label: "Relationship Density", value: density < 0.01 ? density.toFixed(4) : density.toFixed(2), suffix: "%", note: `${formatCount(analytics.edgeCount)} total connections`, spark: [], delta: null },
    { label: "Retrieval Quality", value: "—", note: "No retrieval telemetry in graph projection", spark: [], delta: null },
    { label: "Memory Growth", value: memoryGrowth == null ? "—" : `${memoryGrowth >= 0 ? "+" : ""}${memoryGrowth.toFixed(1)}%`, note: memoryNodes.length ? `${formatCount(memoryNodes.length)} memory nodes` : "No memory nodes in projection", spark: [], delta: null },
    { label: "Avg. Query Latency", value: averageLatency == null ? "—" : Math.round(averageLatency).toLocaleString(), suffix: averageLatency == null ? undefined : " ms", note: averageLatency == null ? "No latency telemetry in graph projection" : `${latencyValues.length} measured nodes`, spark: movingSpark(latencyValues), delta: null },
    { label: "Confidence Score", value: averageConfidence == null ? "—" : `${(averageConfidence * 100).toFixed(1)}%`, note: averageConfidence == null ? "No confidence telemetry in graph projection" : `${confidenceValues.length} scored nodes`, spark: movingSpark(confidenceValues), delta: null },
  ];

  const maxTypeCount = Math.max(1, ...typeRows.map(([, count]) => count));
  const maxHist = Math.max(1, ...confidenceHistogram);

  return (
    <div className="lv-ba lv-ba-ref">
      <div className="lv-ba-kpi">
        {kpis.map((kpi, index) => (
          <article key={kpi.label} className="lv-ba-kpi-card">
            <div className="lv-ba-kpi-top"><span className="lv-ba-kpi-icon">{["⌘", "⌁", "◎", "▤", "ϟ", "◇"][index]}</span><span>{kpi.label}</span></div>
            <div className="lv-ba-kpi-value"><strong>{kpi.value}</strong>{kpi.suffix ? <span>{kpi.suffix}</span> : null}</div>
            {kpi.spark.length > 1 ? <Spark points={kpi.spark} width={150} height={24} /> : <div className="lv-ba-kpi-spark-empty" />}
            <div className="lv-ba-kpi-foot"><span>{kpi.note}</span></div>
          </article>
        ))}
      </div>

      <div className="lv-ba-mid lv-ba-reference-grid">
        <Panel title="Knowledge Growth" className="lv-ba-growth" action={<div className="lv-ba-range">{["7D", "30D", "90D", "ALL"].map((range) => <button key={range} type="button" className={`lv-br-chip${growthRange === range ? " is-active" : ""}`} onClick={() => setGrowthRange(range)}>{range}</button>)}</div>}>
          {growth.labels.length ? <LineChart series={[{ name: "Total Nodes", color: "#F0C875", values: growth.cumulative }, { name: "New Nodes", color: "#22C9D6", values: growth.daily }]} labels={growth.labels.filter((_, index) => index === 0 || index === growth.labels.length - 1 || index % Math.max(1, Math.floor(growth.labels.length / 4)) === 0)} height={185} /> : <div className="lv-ba-empty-chart">No dated nodes in the current bounded projection.</div>}
        </Panel>

        <Panel title="Source Composition" className="lv-ba-composition">
          <div className="lv-ba-donut-wrap"><Donut slices={composition.map((slice) => ({ value: slice.count, color: slice.color }))} center={formatCount(analytics.nodeCount)} size={170} /><ul className="lv-ba-legend">{composition.map((slice) => <li key={slice.label}><span className="lv-bc-dot" style={{ background: slice.color }} /><span>{slice.label}</span><em>{slice.value}%</em></li>)}</ul></div>
        </Panel>

        <Panel title="Node Type Distribution" className="lv-ba-types">
          <div className="lv-ba-count-toggle"><button type="button" className="is-active">Count</button><button type="button">Percentage</button></div>
          <ul className="lv-ba-bars">{typeRows.map(([type, count]) => <li key={type}><span><i className="lv-bc-dot" style={{ background: colorForType(type) }} />{pretty(type)}</span><em>{formatCount(count)}</em><div className="lv-ba-bar-track"><i style={{ width: `${Math.max(3, (count / maxTypeCount) * 100)}%`, background: colorForType(type) }} /></div><small>{analytics.nodeCount ? ((count / analytics.nodeCount) * 100).toFixed(1) : "0.0"}%</small></li>)}</ul>
        </Panel>

        <Panel title="Latency Trends" className="lv-ba-latency">
          {latencyValues.length > 1 ? <LineChart series={[{ name: "Measured", color: "#22C9D6", values: latencyValues.slice(-24) }]} height={145} /> : <div className="lv-ba-empty-chart">Latency telemetry is not exposed by /api/brain/graph.</div>}
        </Panel>

        <Panel title="Confidence Distribution" className="lv-ba-confidence">
          {confidenceValues.length ? <><div className="lv-ba-hist">{confidenceHistogram.map((count, index) => <div key={index} className="lv-ba-hist-col"><div className="lv-ba-hist-bar" style={{ height: `${Math.max(count ? 5 : 0, (count / maxHist) * 100)}%`, background: index >= 8 ? "#8DE8A3" : index >= 6 ? "#22C9D6" : "#4285E8" }} /></div>)}</div><div className="lv-ba-hist-meta"><span>0.0</span><span>{averageConfidence == null ? "" : `Avg: ${averageConfidence.toFixed(3)}`}</span><span>1.0</span></div></> : <div className="lv-ba-empty-chart">Confidence telemetry is not exposed by the current Brain sources.</div>}
        </Panel>

        <Panel title="Semantic Heatmap" className="lv-ba-heatmap">
          {heatmapData.types.length ? <Heatmap grid={heatmapData.grid} rowLabels={heatmapData.types.map((type) => pretty(type).slice(0, 11))} colLabels={heatmapData.types.map((type) => pretty(type).slice(0, 3))} /> : <div className="lv-ba-empty-chart">No semantic types available.</div>}
        </Panel>
      </div>

      <div className="lv-ba-footer">
        <section className="lv-ba-insights"><strong>Insights</strong><div className="lv-ba-insight-grid"><div><b>{connectedPercent.toFixed(1)}%</b><span>Nodes connected</span></div><div><b>{averageDegree.toFixed(2)}</b><span>Average degree</span></div><div><b>{analytics.typeCount}</b><span>Knowledge domains</span></div><div><b>{analytics.relations.length}</b><span>Relation types</span></div></div></section>
        <section className="lv-ba-emerging"><strong>Top Emerging Topics</strong>{emergingTopics.length ? <ol>{emergingTopics.map(([topic, count], index) => <li key={topic}><span><b>{index + 1}</b>{pretty(topic)}</span><em>{count} recent</em></li>)}</ol> : <p className="lv-br-muted">Not enough dated node labels to derive emerging topics.</p>}</section>
        <div className="lv-ba-footer-action"><button type="button" className="lv-br-btn is-gold">View All Analytics →</button></div>
      </div>
    </div>
  );
}
