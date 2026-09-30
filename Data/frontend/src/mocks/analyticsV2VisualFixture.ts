/**
 * TEST-ONLY Screen 1 Analytics / Statistieken visual fixture.
 * Production must never import these values as API fallbacks.
 * Gated by window.__LV_V2_VISUAL_FIXTURE__ === 'analytics'.
 */

import type { AnalyticsDashboard } from "../types/api";

export const ANALYTICS_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:38:12.000Z";

function spark(seed: number, n = 14): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    out.push(Math.round(20 + ((seed * (i + 3)) % 40) + i * 1.5));
  }
  return out;
}

function days(n: number): string[] {
  const out: string[] = [];
  const base = new Date("2025-05-25T00:00:00.000Z");
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(base);
    d.setUTCDate(d.getUTCDate() - i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

const d30 = days(30);

function kpi(
  value: number,
  delta: number,
  direction: "improved" | "regressed" | "flat",
  sparkVals: number[],
  lowerIsBetter = false,
) {
  return {
    value,
    measured: true,
    deltaPercent: delta,
    deltaDirection: direction,
    lowerIsBetter,
    previousValue: value,
    spark: sparkVals,
    status: "OK" as const,
  };
}

export const ANALYTICS_V2_VISUAL_FIXTURE: AnalyticsDashboard = {
  collectedAt: ANALYTICS_V2_VISUAL_FROZEN_ISO,
  chartRange: "30d",
  rankingRange: "7d",
  activityLimit: 10,
  kpis: {
    knowledgeItems: kpi(128400, 12.5, "improved", spark(3)),
    datasets: kpi(342, 6.2, "improved", spark(5)),
    documents: kpi(96100, 18.3, "improved", spark(7)),
    researchJobs: kpi(2847, 24.1, "improved", spark(9)),
    avgProcessingSeconds: kpi(12.4, -32.5, "improved", spark(4), true),
    systemUsagePercent: kpi(67, 11.2, "regressed", spark(8), true),
  },
  knowledgeGrowth: {
    range: "30d",
    subtitle: "Totale kennis items in de tijd",
    points: d30.map((t, i) => ({
      t,
      value: Math.round(80000 + i * 1600 + (i % 5) * 400),
      known: true,
    })),
  },
  datasetGrowth: {
    range: "30d",
    subtitle: "Aantal datasets en totale grootte",
    sizeSemantics: "on_disk_artifact_byte_size",
    coverage: { measuredCount: 300, unknownCount: 42, totalCount: 342, coveragePercent: 87.7 },
    points: d30.map((t, i) => ({
      t,
      count: Math.round(200 + i * 4.7),
      sizeGb: Math.round((20 + i * 1.8) * 10) / 10,
      known: true,
    })),
  },
  researchActivity: {
    range: "30d",
    series: [
      {
        key: "web_research",
        label: "Web Research",
        points: d30.map((t, i) => ({ t, value: 8 + (i % 7) })),
      },
      {
        key: "analyse",
        label: "Analyse",
        points: d30.map((t, i) => ({ t, value: 5 + (i % 5) })),
      },
      {
        key: "trading",
        label: "Trading",
        points: d30.map((t, i) => ({ t, value: 2 + (i % 4) })),
      },
      {
        key: "agent_research",
        label: "Agent Research",
        points: d30.map((t, i) => ({ t, value: 4 + (i % 6) })),
      },
    ],
  },
  distributions: {
    itemTypes: {
      total: 128400,
      segments: [
        { key: "document", label: "Documenten", count: 96172, percent: 74.9 },
        { key: "note", label: "Notities", count: 12455, percent: 9.7 },
        { key: "web", label: "Web Content", count: 8603, percent: 6.7 },
        { key: "code", label: "Code Snippets", count: 4237, percent: 3.3 },
        { key: "dataset", label: "Datasets", count: 3082, percent: 2.4 },
        { key: "other", label: "Overig", count: 3851, percent: 3.0 },
      ],
    },
    datasetTypes: {
      total: 342,
      segments: [
        { key: "training", label: "Training Data", count: 124, percent: 36.3 },
        { key: "market", label: "Marktdata", count: 78, percent: 22.8 },
        { key: "research", label: "Onderzoeksdata", count: 62, percent: 18.1 },
        { key: "evaluation", label: "Evaluatie Data", count: 38, percent: 11.1 },
        { key: "synthetic", label: "Synthetische Data", count: 24, percent: 7.0 },
        { key: "other", label: "Overig", count: 16, percent: 4.7 },
      ],
    },
    sources: {
      total: 128400,
      segments: [
        { key: "web_scraping", label: "Web Scraping", count: 42115, percent: 32.8 },
        { key: "manual", label: "Handmatig", count: 28376, percent: 22.1 },
        { key: "agent_research", label: "Agent Research", count: 24653, percent: 19.2 },
        { key: "import", label: "Import", count: 18618, percent: 14.5 },
        { key: "api", label: "API", count: 9245, percent: 7.2 },
        { key: "other", label: "Overig", count: 5393, percent: 4.2 },
      ],
    },
  },
  rankings: {
    range: "7d",
    topAgents: [
      { rank: 1, agentId: "a1", name: "Research Agent Alpha", items: 24800, sizeGb: 12.4, sizeStatus: "MEASURED", successRatePercent: 98.2, successStatus: "MEASURED" },
      { rank: 2, agentId: "a2", name: "Knowledge Curator", items: 18600, sizeGb: 9.1, sizeStatus: "MEASURED", successRatePercent: 97.1, successStatus: "MEASURED" },
      { rank: 3, agentId: "a3", name: "Web Scout", items: 14200, sizeGb: 7.8, sizeStatus: "MEASURED", successRatePercent: 95.4, successStatus: "MEASURED" },
      { rank: 4, agentId: "a4", name: "Dataset Builder", items: 9800, sizeGb: 5.2, sizeStatus: "MEASURED", successRatePercent: 96.8, successStatus: "MEASURED" },
      { rank: 5, agentId: "a5", name: "Trading Analyst", items: 7400, sizeGb: 3.6, sizeStatus: "MEASURED", successRatePercent: 94.9, successStatus: "MEASURED" },
    ],
    topSources: [
      { rank: 1, key: "web_scraping", name: "Websites", items: 42115, sizeGb: 18.2, sizeStatus: "MEASURED", percent: 32.8 },
      { rank: 2, key: "import", name: "PDF/Documenten", items: 28376, sizeGb: 14.1, sizeStatus: "MEASURED", percent: 22.1 },
      { rank: 3, key: "agent_research", name: "Agent Research", items: 24653, sizeGb: 11.4, sizeStatus: "MEASURED", percent: 19.2 },
      { rank: 4, key: "api", name: "API/External", items: 18618, sizeGb: 8.7, sizeStatus: "MEASURED", percent: 14.5 },
      { rank: 5, key: "other", name: "Media/Video", items: 8731, sizeGb: 4.2, sizeStatus: "MEASURED", percent: 6.8 },
    ],
    popularTags: [
      { rank: 1, tag: "trading", count: 4820, trendPercent: 12 },
      { rank: 2, tag: "markt", count: 3610, trendPercent: 8 },
      { rank: 3, tag: "bitcoin", count: 2940, trendPercent: 15 },
      { rank: 4, tag: "research", count: 2510, trendPercent: 6 },
      { rank: 5, tag: "nlp", count: 1980, trendPercent: 4 },
    ],
  },
  processing: {
    range: "30d",
    durationRule: "finished_at - started_at",
    excludesNonTerminal: true,
    tasks: [
      { key: "document_processing", label: "Document Verwerking", avgSeconds: 12.4, minSeconds: 2.1, maxSeconds: 48.0, count: 1842, status: "OK" },
      { key: "web_scraping", label: "Web Scraping", avgSeconds: 18.7, minSeconds: 3.4, maxSeconds: 92.0, count: 1260, status: "OK" },
      { key: "embedding_generation", label: "Embedding Generatie", avgSeconds: 8.2, minSeconds: 1.0, maxSeconds: 31.5, count: 4200, status: "OK" },
      { key: "knowledge_extraction", label: "Kennis Extractie", avgSeconds: 22.1, minSeconds: 5.0, maxSeconds: 110.0, count: 980, status: "OK" },
      { key: "dataset_processing", label: "Dataset Verwerking", avgSeconds: 45.6, minSeconds: 10.0, maxSeconds: 240.0, count: 312, status: "OK" },
    ],
  },
  activity: {
    limit: 10,
    items: [
      { t: "2025-05-25T14:36:00+00:00", kind: "knowledge_added", event: "Kennis item toegevoegd", details: "1,248 items (Web Research)" },
      { t: "2025-05-25T14:32:00+00:00", kind: "dataset_processed", event: "Dataset verwerkt", details: "training-mix-v3 (materialize)" },
      { t: "2025-05-25T14:28:00+00:00", kind: "research_completed", event: "Research afgerond", details: "run-8842 completed" },
      { t: "2025-05-25T14:20:00+00:00", kind: "sync", event: "Automatische sync", details: "knowledge mirror ok" },
      { t: "2025-05-25T14:12:00+00:00", kind: "embeddings", event: "Embeddings gegenereerd", details: "4,200 chunks" },
      { t: "2025-05-25T14:05:00+00:00", kind: "knowledge_added", event: "Kennis item toegevoegd", details: "PDF ingest batch-19" },
      { t: "2025-05-25T13:58:00+00:00", kind: "dataset_processed", event: "Dataset verwerkt", details: "market-ticks validate" },
      { t: "2025-05-25T13:50:00+00:00", kind: "research_completed", event: "Research afgerond", details: "run-8839 completed" },
      { t: "2025-05-25T13:42:00+00:00", kind: "embeddings", event: "Embeddings gegenereerd", details: "860 chunks" },
      { t: "2025-05-25T13:30:00+00:00", kind: "sync", event: "Automatische sync", details: "dataset catalog refresh" },
    ],
  },
  resources: {
    collectedAt: ANALYTICS_V2_VISUAL_FROZEN_ISO,
    cpu: { pct: 42, status: "OK" },
    ram: { pct: 39, usedBytes: 6.2 * 1024 ** 3, totalBytes: 16 * 1024 ** 3, status: "OK" },
    gpu: { pct: 76, status: "OK", devices: [], aggregate: "dashboard_gpuPct_or_max_device" },
    disk: {
      pct: 32,
      usedBytes: 320 * 1024 ** 3,
      totalBytes: 1000 * 1024 ** 3,
      status: "OK",
      metric: "leviathan_data_volume",
    },
    truth: { measured: true, synthetic: false },
  },
  sourceStatus: {
    kpis: "OK",
    knowledgeGrowth: "OK",
    datasetGrowth: "OK",
    researchActivity: "OK",
    distributions: "OK",
    rankings: "OK",
    processing: "OK",
    activity: "OK",
    resources: "OK",
  },
  partial: false,
  truth: {
    server_side_aggregation: true,
    no_invented_cost: true,
    no_fake_trends: true,
    no_synthetic_history: true,
    unknown_is_not_zero: true,
    visual_fixture: true,
  },
};

export function isAnalyticsVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  return (window as Window & { __LV_V2_VISUAL_FIXTURE__?: string }).__LV_V2_VISUAL_FIXTURE__ === "analytics";
}
