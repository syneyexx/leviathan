/**
 * TEST-ONLY Screen 1 Datasets (Onderzoek & Kennis) visual fixture.
 *
 * Activated solely via Playwright route mocking + window.__LV_V2_FROZEN_NOW__ /
 * __LV_V2_VISUAL_FIXTURE__ === "datasets". Production Datasets pages and hooks
 * must NEVER import these values as fallbacks or defaults.
 */

export const DATASETS_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26.000Z";

const now = DATASETS_V2_VISUAL_FROZEN_ISO;
const GB = 1024 ** 3;

function ds(
  id: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    datasetId: id,
    name: id,
    displayName: overrides.displayName ?? id,
    sourceType: "local_upload",
    status: "ready",
    description: "Fixture dataset",
    originalFilename: `${id}.csv`,
    schemaVersion: 1,
    byteSize: 2.4 * GB,
    rowCount: 12_482_301,
    detectedFormat: "csv",
    metadata: {},
    rawPath: `/data/datasets/${id}`,
    createdAt: now,
    updatedAt: now,
    semanticTags: ["fixture"],
    ...overrides,
  };
}

export const DATASETS_V2_VISUAL_FIXTURE = {
  health: { status: "ok" },
  overview: {
    totalDatasets: 8,
    totalSamples: 20_000_000,
    samplesMeasuredDatasets: 7,
    samplesUnmeasuredDatasets: 1,
    totalKnownBytes: 48 * GB,
    attributableBytes: 48 * GB,
    bytesMeasuredDatasets: 7,
    bytesUnmeasuredDatasets: 1,
    capacityBytes: 200 * GB,
    freeBytes: 152 * GB,
    usedBytes: 48 * GB,
    measurementStatus: "measured",
    activeImports: 1,
    runningImports: 1,
    queuedImports: 0,
    validationIssues: 0,
    criticalValidationIssues: 0,
    warningValidationIssues: 0,
    versionsWithValidation: 3,
    exportVersionCount: 0,
    byStatus: { ready: 5, processing: 2, offline: 1 },
    bySourceType: { local_upload: 3, huggingface: 4, curated: 1 },
    tagCounts: [{ tag: "nlp", count: 3 }],
    storageBreakdown: [
      { id: "local", label: "Local Datasets", bytes: 18 * GB, pct: 38 },
      { id: "external", label: "External datasets", bytes: 16 * GB, pct: 33 },
      { id: "indexed", label: "Indexed data", bytes: 8 * GB, pct: 17 },
      { id: "cache", label: "Cache & temporary", bytes: 6 * GB, pct: 12 },
    ],
    catalogStatus: {
      state: "healthy",
      label: "Healthy",
      valid: true,
      lastCatalogReconcileAt: now,
      entryCount: 8,
      path: "/data/catalog/datasets.json",
    },
    services: [
      {
        id: "hf",
        name: "Hugging Face",
        source: "huggingface",
        state: "ready",
        label: "Actief",
        measured: true,
      },
      {
        id: "local",
        name: "Local filesystem",
        source: "local",
        state: "ready",
        label: "Actief",
        measured: true,
      },
      {
        id: "arxiv",
        name: "arXiv",
        source: "arxiv",
        state: "ready",
        label: "Actief",
        measured: true,
      },
    ],
  },
  datasets: [
    ds("BTC_USD_Historical_2010_2024", {
      displayName: "BTC_USD_Historical_2010_2024.csv",
      description: "Bitcoin historical OHLCV price data",
      sourceType: "curated",
      detectedFormat: "csv",
      semanticTags: ["crypto", "bitcoin", "price-data"],
      byteSize: 2.4 * GB,
      rowCount: 12_482_301,
      metadata: { embeddings: "indexed" },
    }),
    ds("AI_Research_Papers_2024", {
      displayName: "AI_Research_Papers_2024.zip",
      description: "arXiv AI paper corpus subset",
      sourceType: "huggingface",
      detectedFormat: "pdf",
      byteSize: 8.7 * GB,
      rowCount: 4218,
      status: "ready",
      metadata: { embeddings: "indexed" },
    }),
    ds("Earnings_Calls_Transcripts", {
      displayName: "Earnings_Calls_Transcripts",
      description: "Corporate earnings call transcripts",
      sourceType: "local_upload",
      detectedFormat: "jsonl",
      status: "processing",
      byteSize: 1.2 * GB,
      rowCount: 840_112,
    }),
    ds("Company_Filings_10K_10Q", {
      displayName: "Company_Filings_10K_10Q",
      description: "SEC filings corpus",
      sourceType: "huggingface",
      detectedFormat: "pdf",
      status: "processing",
      byteSize: 5.1 * GB,
      rowCount: 92_440,
    }),
    ds("local_lab_notes", {
      displayName: "Lab Instrumentation Logs",
      description: "Offline-ready local telemetry",
      sourceType: "local_path",
      status: "offline",
      detectedFormat: "csv",
      byteSize: 640 * 1024 * 1024,
      rowCount: 12_100_000,
    }),
    ds("wikitext_fixture", {
      displayName: "wikitext",
      description: "Language modeling corpus",
      sourceType: "huggingface",
      detectedFormat: "text",
      byteSize: 3.1 * GB,
      rowCount: 1_200_000,
      metadata: { embeddings: "indexed" },
    }),
    ds("curated_bench", {
      displayName: "Curated Bench Mix",
      description: "Curated evaluation mix",
      sourceType: "curated",
      detectedFormat: "jsonl",
      byteSize: 420 * 1024 * 1024,
      rowCount: 88_000,
      metadata: { embeddings: "indexed" },
    }),
    ds("code_corpus", {
      displayName: "Open Source Code Corpus",
      description: "Multi-language source repos",
      sourceType: "huggingface",
      detectedFormat: "code",
      byteSize: 18.2 * GB,
      rowCount: 6_400_000,
      metadata: { embeddings: "indexed" },
    }),
  ],
  jobs: [
    {
      jobId: "job-index-1",
      datasetId: "Company_Filings_10K_10Q",
      jobType: "INDEX",
      status: "running",
      phase: "indexing",
      progress: 0.42,
      createdAt: now,
      updatedAt: now,
      startedAt: now,
      backend: "python_streaming",
    },
    {
      jobId: "job-import-1",
      datasetId: "Earnings_Calls_Transcripts",
      jobType: "IMPORT_LOCAL",
      status: "running",
      phase: "materializing",
      progress: 0.78,
      createdAt: now,
      updatedAt: now,
      startedAt: now,
      backend: "rust_native",
      peakRssBytes: "UNMEASURED",
    },
  ],
  versions: [
    {
      versionId: "ver-btc-1",
      datasetId: "BTC_USD_Historical_2010_2024",
      versionLabel: "v1",
      status: "ready",
      kind: "raw",
      rowCount: 12_482_301,
      byteSize: 2.4 * GB,
      storagePath: "/data/datasets/BTC_USD_Historical_2010_2024/v1",
      createdAt: now,
      updatedAt: now,
    },
  ],
  previewRows: [
    { date: "2024-01-01", open: 42000, high: 43100, low: 41800, close: 42850, volume: 12001 },
    { date: "2024-01-02", open: 42850, high: 44010, low: 42500, close: 43920, volume: 15440 },
  ],
} as const;

export function isDatasetsVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  const flag = (window as Window & { __LV_V2_VISUAL_FIXTURE__?: unknown }).__LV_V2_VISUAL_FIXTURE__;
  return flag === "datasets";
}
