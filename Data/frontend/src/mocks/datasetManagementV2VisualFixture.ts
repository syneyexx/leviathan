/**
 * TEST-ONLY Screen 1 Dataset Management visual fixture.
 *
 * Activated solely via Playwright route mocking + window.__LV_V2_FROZEN_NOW__ /
 * __LV_V2_VISUAL_FIXTURE__. Production Dataset Management pages and hooks must
 * NEVER import these values as fallbacks or defaults — real totals always come
 * from DatasetService `/api/datasets/overview` and list endpoints.
 *
 * Numbers approximate `Data/docs/ui_reference/dataset-management-llm-v2-reference.png`
 * (248 datasets · 48.7M samples · storage · 3 active imports · 17 validation issues ·
 * catalog healthy · frozen wall-clock 2025-05-25 14:38:12).
 */

export const DATASET_MGMT_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:38:12.000Z";

const now = DATASET_MGMT_V2_VISUAL_FROZEN_ISO;
const GB = 1024 ** 3;
const TB = 1024 ** 4;

function quality(
  score: number | null,
  overrides: Partial<{
    measured: boolean;
    label: string;
    tone: "good" | "fair" | "poor" | "critical" | "unknown";
  }> = {},
) {
  if (score == null || overrides.measured === false) {
    return {
      measured: false,
      score: null,
      label: "Niet gemeten",
      segments: [false, false, false, false, false],
      tone: "unknown" as const,
      constituents: {},
      truth: { qualityRequiresValidationEvidence: true, fixtureOnly: true },
    };
  }
  const tone =
    overrides.tone ??
    (score >= 80 ? "good" : score >= 55 ? "fair" : score >= 25 ? "poor" : "critical");
  const label =
    overrides.label ??
    (tone === "good" ? "Goed" : tone === "fair" ? "Matig" : tone === "poor" ? "Zwak" : "Kritiek");
  return {
    measured: true,
    score,
    label,
    segments: [0, 1, 2, 3, 4].map((i) => score > i * 20),
    tone,
    constituents: {
      errorCount: tone === "critical" ? 6 : tone === "poor" ? 3 : 0,
      warningCount: tone === "fair" ? 4 : tone === "poor" ? 8 : 1,
      emptyContentCount: 0,
      rowCount: 1000,
      valid: tone !== "critical",
      formula: "clamp(0,100, 100 - 8*errors - 2*warnings - 1*emptyContent)",
    },
    truth: { qualityRequiresValidationEvidence: true, fixtureOnly: true },
  };
}

function ds(
  id: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    datasetId: id,
    name: id,
    displayName: id,
    displayNameSource: "fixture",
    primaryCategory: "GENERAL",
    secondaryCategory: null,
    semanticTags: ["nl"],
    semanticReviewRequired: false,
    semanticProfile: {
      displayName: id,
      displayNameSource: "fixture",
      primaryCategory: "GENERAL",
      secondaryCategory: null,
      categoryPath: ["GENERAL"],
      tags: ["nl"],
      summary: null,
      confidence: 0.9,
      reviewRequired: false,
      classificationMethod: "fixture",
    },
    recoveryState: "READY",
    sourceType: "open_data",
    status: "ready",
    description: "",
    license: "CC BY-SA 3.0",
    schemaVersion: 1,
    contentHash: `hash-${id}`,
    byteSize: 12 * GB,
    rowCount: 1_200_000,
    detectedFormat: "text",
    formatConfidence: 0.95,
    provenance: { fixture: true },
    metadata: { language: "nl", taskType: "language_modeling" },
    rawPath: `/data/datasets/${id}`,
    originalUri: null,
    createdAt: "2025-04-01T10:00:00.000Z",
    updatedAt: now,
    brainStatus: "indexed",
    learned: true,
    sourceMissing: false,
    canonicalState: "LEARNED",
    brain: {
      brainStatus: "indexed",
      label: "Geïndexeerd",
      learned: true,
      canonicalState: "LEARNED",
      chunkCount: 42000,
      documentCount: 18000,
      updatedAt: now,
    },
    learningState: {
      datasetId: id,
      canonicalState: "LEARNED",
      label: "Geleerd",
      brainState: "indexed",
      indexState: "ready",
      validationState: "passed",
      updatedAt: now,
    },
    quality: quality(92),
    ...overrides,
  };
}

const DATASETS = [
  ds("nl_wiki_2024", {
    displayName: "nl_wiki_2024",
    primaryCategory: "EDUCATION_LANGUAGE",
    semanticTags: ["nl", "wiki", "kennis"],
    description:
      "Nederlandse Wikipedia dump (2024) — opgeschoonde artikelen voor kennisverrijking, RAG en instruct-tuning.",
    sourceType: "open_data",
    status: "ready",
    detectedFormat: "text",
    byteSize: 48 * GB,
    rowCount: 12_100_000,
    semanticProfile: {
      displayName: "nl_wiki_2024",
      primaryCategory: "EDUCATION_LANGUAGE",
      tags: ["nl", "wiki", "kennis"],
      summary:
        "Nederlandse encyclopedische tekstcorpus (2024) geschikt voor RAG, LM pretraining en kennisverrijking.",
      confidence: 0.96,
      reviewRequired: false,
      classificationMethod: "fixture",
    },
    quality: quality(94),
    brain: {
      brainStatus: "indexed",
      label: "Geïndexeerd",
      learned: true,
      canonicalState: "LEARNED",
      chunkCount: 890000,
      documentCount: 420000,
      updatedAt: now,
    },
  }),
  ds("code_instructions_v2", {
    primaryCategory: "TECHNOLOGY_SOFTWARE",
    semanticTags: ["code", "instruct"],
    sourceType: "huggingface",
    status: "processed",
    detectedFormat: "code",
    byteSize: 18 * GB,
    rowCount: 8_400_000,
    quality: quality(88),
    learned: true,
  }),
  ds("medical_knowledge", {
    primaryCategory: "HEALTH_MEDICINE",
    semanticTags: ["medisch", "nl"],
    sourceType: "local",
    status: "ready",
    detectedFormat: "text",
    byteSize: 12 * GB,
    rowCount: 3_800_000,
    quality: quality(90),
  }),
  ds("synthetic_dialogues", {
    primaryCategory: "GENERAL",
    semanticTags: ["chat", "nl"],
    sourceType: "synthetic",
    status: "running",
    detectedFormat: "chat",
    byteSize: Math.round(6.2 * GB),
    rowCount: 2_100_000,
    quality: quality(null),
    learned: false,
    brainStatus: "indexing",
    canonicalState: "INDEXING",
    brain: {
      brainStatus: "indexing",
      label: "Bezig",
      learned: false,
      canonicalState: "INDEXING",
      progress: 0.64,
      updatedAt: now,
    },
    learningState: {
      datasetId: "synthetic_dialogues",
      canonicalState: "INDEXING",
      label: "Bezig",
      progress: 0.64,
      updatedAt: now,
    },
  }),
  ds("eu_legal_corpus", {
    primaryCategory: "RESEARCH_PUBLICATIONS",
    semanticTags: ["legal", "eu"],
    sourceType: "open_data",
    status: "ready",
    detectedFormat: "text",
    byteSize: 22 * GB,
    rowCount: 5_600_000,
    quality: quality(91),
  }),
  ds("multilingual_news", {
    primaryCategory: "GENERAL",
    semanticTags: ["news", "multi"],
    sourceType: "huggingface",
    status: "ready",
    detectedFormat: "text",
    byteSize: 31 * GB,
    rowCount: 9_200_000,
    quality: quality(86),
  }),
  ds("agent_tool_logs", {
    primaryCategory: "TECHNOLOGY_SOFTWARE",
    semanticTags: ["agents", "logs"],
    sourceType: "local",
    status: "ready",
    detectedFormat: "log",
    byteSize: Math.round(1.8 * GB),
    rowCount: 420_000,
    quality: quality(78, { tone: "fair", label: "Matig" }),
  }),
  ds("research_papers_v3", {
    primaryCategory: "RESEARCH_PUBLICATIONS",
    semanticTags: ["research"],
    sourceType: "local",
    status: "warning",
    detectedFormat: "pdf",
    byteSize: 14 * GB,
    rowCount: 1_200_000,
    quality: quality(42, { tone: "poor", label: "Zwak" }),
    learned: false,
    brainStatus: "stale",
    canonicalState: "NEEDS_REVIEW",
  }),
  ds("finance_tick_snippets", {
    primaryCategory: "FINANCE_TRADING",
    semanticTags: ["finance", "ticks"],
    sourceType: "local",
    status: "ready",
    detectedFormat: "text",
    byteSize: 9 * GB,
    rowCount: 4_100_000,
    quality: quality(83),
  }),
  ds("crypto_onchain_notes", {
    primaryCategory: "CRYPTO_BLOCKCHAIN",
    semanticTags: ["crypto", "onchain"],
    sourceType: "huggingface",
    status: "queued",
    detectedFormat: "text",
    byteSize: 4 * GB,
    rowCount: 980_000,
    quality: quality(null),
    learned: false,
  }),
];

const VERSIONS: Record<string, Array<Record<string, unknown>>> = Object.fromEntries(
  DATASETS.map((row) => {
    const id = String(row.datasetId);
    const versionId = `ver-${id}-v1`;
    return [
      id,
      [
        {
          versionId,
          datasetId: id,
          versionLabel: "v1",
          parentVersionId: null,
          status: "ready",
          kind: "materialized",
          rowCount: row.rowCount,
          byteSize: row.byteSize,
          contentHash: `vhash-${id}`,
          storagePath: `/data/datasets/${id}/v1`,
          split: { train: 0.9, validation: 0.05, test: 0.05 },
          tokenStats: { total_tokens: Number(row.rowCount) * 80 },
          validation: {
            valid: true,
            errorCount: 0,
            warningCount: 2,
            emptyContentCount: 0,
            rowCount: row.rowCount,
          },
          metadata: {},
          createdAt: "2025-04-10T10:00:00.000Z",
          updatedAt: now,
        },
      ],
    ];
  }),
);

const PREVIEW_ROWS = [
  {
    id: "wiki_000001",
    title: "Amsterdam",
    text: "Amsterdam is de hoofdstad en grootste stad van Nederland...",
    source: "nl.wikipedia.org",
    url: "https://nl.wikipedia.org/wiki/Amsterdam",
    length: 4821,
  },
  {
    id: "wiki_000002",
    title: "Rotterdam",
    text: "Rotterdam is een havenstad in Zuid-Holland...",
    source: "nl.wikipedia.org",
    length: 3102,
  },
];

const JOBS = [
  {
    jobId: "job-import-synth-1",
    datasetId: "synthetic_dialogues",
    versionId: "ver-synthetic_dialogues-v1",
    jobType: "import",
    status: "running",
    phase: "download",
    progress: 0.64,
    cancelRequested: false,
    checkpoint: {
      bytesDownloaded: Math.round(4.0 * GB),
      bytesTotal: Math.round(6.2 * GB),
      bytesPerSecond: 12_500_000,
      etaSeconds: 180,
    },
    download: {
      bytesDownloaded: Math.round(4.0 * GB),
      bytesTotal: Math.round(6.2 * GB),
      bytesPerSecond: 12_500_000,
      etaSeconds: 180,
    },
    config: { source: "synthetic" },
    result: null,
    error: null,
    createdAt: "2025-05-25T14:02:00.000Z",
    startedAt: "2025-05-25T14:02:10.000Z",
    updatedAt: now,
    finishedAt: null,
  },
  {
    jobId: "job-validate-papers-1",
    datasetId: "research_papers_v3",
    versionId: "ver-research_papers_v3-v1",
    jobType: "validate",
    status: "queued",
    phase: "queued",
    progress: 0,
    cancelRequested: false,
    config: {},
    result: null,
    error: null,
    createdAt: "2025-05-25T14:20:00.000Z",
    startedAt: null,
    updatedAt: now,
    finishedAt: null,
  },
  {
    jobId: "job-import-crypto-1",
    datasetId: "crypto_onchain_notes",
    versionId: null,
    jobType: "import_huggingface",
    status: "queued",
    phase: "queued",
    progress: 0,
    cancelRequested: false,
    config: { repositoryId: "leviathan/crypto-onchain-notes" },
    result: null,
    error: null,
    createdAt: "2025-05-25T14:30:00.000Z",
    startedAt: null,
    updatedAt: now,
    finishedAt: null,
  },
  {
    jobId: "job-dedupe-wiki-1",
    datasetId: "nl_wiki_2024",
    versionId: "ver-nl_wiki_2024-v1",
    jobType: "dedupe",
    status: "succeeded",
    phase: "complete",
    progress: 1,
    cancelRequested: false,
    config: {},
    result: { duplicatesRemoved: 18420 },
    error: null,
    createdAt: "2025-05-25T12:40:00.000Z",
    startedAt: "2025-05-25T12:40:30.000Z",
    updatedAt: "2025-05-25T14:51:00.000Z",
    finishedAt: "2025-05-25T14:51:00.000Z",
  },
];

const ATTRIBUTABLE = 456 * GB;
const CAPACITY = 1 * TB;
const USED = Math.round(0.46 * CAPACITY);

export const DATASET_MGMT_V2_VISUAL_FIXTURE = {
  health: {
    status: "ok",
    posture: "operational",
    product_truth: { overall: "healthy" },
    services: {
      "LM Studio": { status: "Ready" },
      Ollama: { status: "Ready" },
      Docker: { status: "Running" },
      "Plugin Runtime": { status: "Ready" },
      "MCP Server": { status: "Ready" },
    },
  },
  overview: {
    totalDatasets: 248,
    totalSamples: 48_700_000,
    samplesMeasuredDatasets: 240,
    samplesUnmeasuredDatasets: 8,
    totalKnownBytes: ATTRIBUTABLE,
    attributableBytes: ATTRIBUTABLE,
    bytesMeasuredDatasets: 240,
    bytesUnmeasuredDatasets: 8,
    capacityBytes: CAPACITY,
    freeBytes: CAPACITY - USED,
    usedBytes: USED,
    measurementStatus: "complete",
    activeImports: 3,
    runningImports: 2,
    queuedImports: 1,
    validationIssues: 17,
    criticalValidationIssues: 5,
    warningValidationIssues: 12,
    versionsWithValidation: 196,
    exportVersionCount: 42,
    byStatus: {
      ready: 198,
      processed: 22,
      running: 8,
      queued: 5,
      warning: 10,
      error: 5,
    },
    bySourceType: {
      open_data: 84,
      huggingface: 72,
      local: 58,
      synthetic: 22,
      derived: 12,
    },
    tagCounts: [
      { tag: "kennis", count: 62 },
      { tag: "tekst", count: 46 },
      { tag: "nl", count: 48 },
      { tag: "wiki", count: 42 },
      { tag: "code", count: 31 },
      { tag: "instruct", count: 24 },
      { tag: "chat", count: 19 },
      { tag: "legal", count: 14 },
      { tag: "eu", count: 12 },
      { tag: "research", count: 11 },
      { tag: "finance", count: 9 },
      { tag: "crypto", count: 7 },
    ],
    storageBreakdown: [
      { id: "datasets", label: "Datasets", bytes: Math.round(ATTRIBUTABLE * 0.68), pct: 68 },
      { id: "indexes", label: "Indexen", bytes: Math.round(ATTRIBUTABLE * 0.21), pct: 21 },
      { id: "exports", label: "Exports", bytes: Math.round(ATTRIBUTABLE * 0.07), pct: 7 },
      { id: "other", label: "Overig", bytes: Math.round(ATTRIBUTABLE * 0.04), pct: 4 },
    ],
    catalogStatus: {
      state: "healthy",
      label: "Gezond",
      valid: true,
      lastCatalogReconcileAt: "2025-05-25T14:33:12.000Z",
      entryCount: 248,
      path: "/data/catalog/datasets.json",
      truth: {
        catalogIsDerived: true,
        datasetStoreIsCanonical: true,
        notRemoteSyncOnline: true,
        fixtureOnly: true,
      },
    },
    services: [
      {
        id: "embedding_pipeline",
        name: "Embedding Pipeline",
        source: "embedding worker / Knowledge embedding provider",
        state: "running",
        label: "Running",
        detail: "worker pool embedding · 2 active",
        measured: true,
      },
      {
        id: "indexing_service",
        name: "Indexing Service",
        source: "dataset worker (INDEX) + KnowledgeStore",
        state: "running",
        label: "Running",
        detail: "INDEX jobs accepted",
        measured: true,
      },
      {
        id: "validation_engine",
        name: "Validation Engine",
        source: "dataset worker validate",
        state: "ready",
        label: "Ready",
        detail: "idle · last run ok",
        measured: true,
      },
      {
        id: "semantic_enrichment",
        name: "Semantic Enrichment",
        source: "dataset worker enrich_metadata / semantic profiler",
        state: "busy",
        label: "Busy",
        detail: "enrich_metadata in progress",
        measured: true,
      },
      {
        id: "training_connector",
        name: "Training Connector",
        source: "Training control plane / dataset version refs",
        state: "ready",
        label: "Ready",
        detail: "Training module importable",
        measured: true,
      },
      {
        id: "brain_sync",
        name: "Brain Sync",
        source: "Brain/Knowledge dataset index integration",
        state: "unmeasured",
        label: "Unmeasured",
        detail: "no live brain probe in fixture",
        measured: false,
      },
    ],
    qualityModel: { qualityRequiresValidationEvidence: true },
    truth: {
      nullRowCountIsUnmeasuredNotZero: true,
      pageSizeDoesNotDefineTotals: true,
      fixtureOnly: true,
    },
  },
  datasets: DATASETS,
  total: 248,
  versions: VERSIONS,
  preview: PREVIEW_ROWS,
  jobs: JOBS,
  recovery: {
    datasetId: "nl_wiki_2024",
    recoveryState: "READY",
    state: "READY",
    evidenceSource: "catalog",
    sourcePresent: true,
    metadataRestored: true,
    contentHashOk: true,
    brainLearned: true,
    reindexRequired: false,
    tombstoned: false,
    conflicts: [],
    detail: "Bron aanwezig · metadata intact · Brain geïndexeerd",
    learningCanonicalState: "LEARNED",
    displayName: "nl_wiki_2024",
    truth: { fixtureOnly: true },
  },
} as const;
