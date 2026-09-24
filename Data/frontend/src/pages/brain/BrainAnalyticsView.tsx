import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { buildAnalytics, colorForType, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Donut, Heatmap, LineChart, Panel, Spark } from "./brain-shared";

type AnalyticsKpi = {
  label: string;
  value: string;
  note: string;
  spark: number[];
  suffix?: string;
};

type DistributionMode = "count" | "percentage";

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function pretty(value: string): string {
  return value.split(/[._-]+/g).filter(Boolean).map((part) => part.length <= 3 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`).join(" ");
}

function movingSpark(values: readonly number[]): number[] {
  if (values.length >= 8) return values.slice(-12);
  if (values.length > 1) return values.slice();
  return [];
}

export function BrainAnalyticsView({ nodes, edges, stats, onToast }: { nodes: LiveBrainNode[]; edges: LiveBrainEdge[]; stats?: Record<string, unknown> | null; onToast?: (msg: string) => void }) {
  const analytics = useMemo(() => buildAnalytics(nodes, edges, stats ?? null), [nodes, edges, stats]);
  const [growthRange, setGrowthRange] = useState("30D");
  const [distributionMode, setDistributionMode] = useState<DistributionMode>("count");
  const [httpLatency, setHttpLatency] = useState<Array<{ ts_ms: number; value: number }>>([]);
  const [atlasConfidence, setAtlasConfidence] = useState<number[]>([]);
  const [atlasAvailable, setAtlasAvailable] = useState(false);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      api.performanceSeries("http.request.latency_ms", { limit: 120 }),
      api.brainAtlasConfidence(100),
    ]).then(([latency, atlas]) => {
      if (!active) return;
      if (latency.status === "fulfilled") setHttpLatency(latency.value.points.filter((p) => Number.isFinite(p.value) && p.value >= 0));
      if (atlas.status === "fulfilled") {
        setAtlasAvailable(atlas.value.available);
        setAtlasConfidence(atlas.value.records.map((r) => r.confidence).filter((v) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1));
      }
    });
    return () => { active = false; };
  }, []);

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

  const confidenceValues = atlasConfidence;
  const latencyValues = useMemo(() => httpLatency.map((sample) => sample.value), [httpLatency]);
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
    const dated = nodes.map((node) => ({ node, time: Date.parse(node.created_at ?? "") })).filter(({ node, time }) => index.has(node.type) && Number.isFinite(time));
    if (!dated.length) return { types, grid: [], labels: [] as string[], sampleCount: 0 };
    const latest = Math.max(...dated.map(({ time }) => time));
    const day = 86_400_000;
    const start = Date.UTC(new Date(latest).getUTCFullYear(), new Date(latest).getUTCMonth(), new Date(latest).getUTCDate()) - 27 * day;
    const raw = types.map(() => Array.from({ length: 28 }, () => 0));
    for (const { node, time } of dated) {
      const column = Math.floor((time - start) / day);
      if (column >= 0 && column < 28) raw[index.get(node.type)!][column] += 1;
    }
    const max = Math.max(1, ...raw.flat());
    const labels = Array.from({ length: 28 }, (_, i) => i % 7 === 0 || i === 27 ? new Date(start + i * day).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");
    return { types, grid: raw.map((row) => row.map((value) => value / max)), labels, sampleCount: dated.length };
  }, [nodes, typeRows]);

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

  const kpis: AnalyticsKpi[] = [
    { label: "Total Nodes", value: formatCount(analytics.nodeCount), note: `${formatCount(datedSeries.daily.slice(-30).reduce((sum, value) => sum + value, 0))} dated nodes (30d)`, spark: movingSpark(datedSeries.cumulative) },
    { label: "Relationship Density", value: density < 0.01 ? density.toFixed(4) : density.toFixed(2), suffix: "%", note: `${formatCount(analytics.edgeCount)} total connections`, spark: [] },
    { label: "Retrieval Quality", value: "—", note: "No retrieval telemetry in graph projection", spark: [] },
    { label: "Memory Growth", value: memoryGrowth == null ? "—" : `${memoryGrowth >= 0 ? "+" : ""}${memoryGrowth.toFixed(1)}%`, note: memoryNodes.length ? `${formatCount(memoryNodes.length)} memory nodes` : "No memory nodes in projection", spark: [] },
    { label: "Avg. HTTP Latency", value: averageLatency == null ? "—" : Math.round(averageLatency).toLocaleString(), suffix: averageLatency == null ? undefined : " ms", note: averageLatency == null ? "No HTTP requests measured in this server process" : `${latencyValues.length} measured HTTP requests`, spark: movingSpark(latencyValues) },
    { label: "Atlas Confidence", value: averageConfidence == null ? "—" : `${(averageConfidence * 100).toFixed(1)}%`, note: averageConfidence == null ? "No scored Atlas records available" : `${confidenceValues.length} scored Atlas records`, spark: movingSpark(confidenceValues) },
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
          <div className="lv-ba-count-toggle">
            <button type="button" className={distributionMode === "count" ? "is-active" : ""} aria-pressed={distributionMode === "count"} onClick={() => setDistributionMode("count")}>Count</button>
            <button type="button" className={distributionMode === "percentage" ? "is-active" : ""} aria-pressed={distributionMode === "percentage"} onClick={() => setDistributionMode("percentage")}>Percentage</button>
          </div>
          <ul className="lv-ba-bars">{typeRows.map(([type, count]) => {
            const percentage = analytics.nodeCount ? (count / analytics.nodeCount) * 100 : 0;
            return <li key={type}><span><i className="lv-bc-dot" style={{ background: colorForType(type) }} />{pretty(type)}</span><em>{distributionMode === "count" ? formatCount(count) : `${percentage.toFixed(1)}%`}</em><div className="lv-ba-bar-track"><i style={{ width: `${Math.max(3, (count / maxTypeCount) * 100)}%`, background: colorForType(type) }} /></div><small>{distributionMode === "count" ? `${percentage.toFixed(1)}%` : `${formatCount(count)} nodes`}</small></li>;
          })}</ul>
        </Panel>

        <Panel title="Latency Trends" className="lv-ba-latency">
          {latencyValues.length > 1 ? <><LineChart series={[{ name: "HTTP requests (ms)", color: "#22C9D6", values: latencyValues.slice(-24) }]} height={145} /><div className="lv-ba-chart-caption">Actual server HTTP latency · last {Math.min(24, latencyValues.length)} requests · resets on restart</div></> : <div className="lv-ba-empty-chart">Waiting for measured HTTP requests in this server process.</div>}
        </Panel>

        <Panel title="Confidence Distribution" className="lv-ba-confidence">
          {confidenceValues.length ? <><div className="lv-ba-hist">{confidenceHistogram.map((count, index) => <div key={index} className="lv-ba-hist-col"><div className="lv-ba-hist-bar" style={{ height: `${Math.max(count ? 5 : 0, (count / maxHist) * 100)}%`, background: index >= 8 ? "#8DE8A3" : index >= 6 ? "#22C9D6" : "#4285E8" }} /></div>)}</div><div className="lv-ba-hist-meta"><span>0.0</span><span>{averageConfidence == null ? "" : `Atlas avg: ${averageConfidence.toFixed(3)}`}</span><span>1.0</span></div></> : <div className="lv-ba-empty-chart">{atlasAvailable ? "No scored Atlas records yet." : "Atlas confidence is unavailable or disabled."}</div>}
        </Panel>

        <Panel title="Semantic Heatmap" className="lv-ba-heatmap">
          {heatmapData.grid.length ? <><Heatmap grid={heatmapData.grid} rowLabels={heatmapData.types.map((type) => pretty(type).slice(0, 11))} colLabels={heatmapData.labels} labelWidth={68} compact /><div className="lv-ba-chart-caption">Node activity by type and creation date · {heatmapData.sampleCount} dated nodes in this projection · darker cells mean fewer nodes</div></> : <div className="lv-ba-empty-chart">No dated nodes available for the activity heatmap.</div>}
        </Panel>
      </div>

      <div className="lv-ba-footer">
        <section className="lv-ba-insights"><strong>Insights</strong><div className="lv-ba-insight-grid"><div><b>{connectedPercent.toFixed(1)}%</b><span>Nodes connected</span></div><div><b>{averageDegree.toFixed(2)}</b><span>Average degree</span></div><div><b>{analytics.typeCount}</b><span>Knowledge domains</span></div><div><b>{analytics.relations.length}</b><span>Relation types</span></div></div></section>
        <section className="lv-ba-emerging"><strong>Top Emerging Topics</strong>{emergingTopics.length ? <ol>{emergingTopics.map(([topic, count], index) => <li key={topic}><span><b>{index + 1}</b>{pretty(topic)}</span><em>{count} recent</em></li>)}</ol> : <p className="lv-br-muted">Not enough dated node labels to derive emerging topics.</p>}</section>
        <div className="lv-ba-footer-action"><button type="button" className="lv-br-btn is-gold" onClick={() => { setGrowthRange("ALL"); onToast?.("Showing the full bounded analytics projection."); }}>View All Analytics →</button></div>
      </div>
    </div>
  );
}
