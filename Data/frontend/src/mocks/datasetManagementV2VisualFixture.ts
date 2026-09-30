/**
 * TEST-ONLY Screen 1 Dataset Management visual fixture.
 * Activated solely when window.__LV_V2_VISUAL_FIXTURE__ === 'dataset-management'.
 * Never imported by production page defaults as data fallbacks.
 */

export const DATASET_MGMT_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:38:12.000Z";

const now = DATASET_MGMT_V2_VISUAL_FROZEN_ISO;

function quality(score: number | null) {
  if (score == null) {
    return {
      measured: false,
      score: null,
      label: "Niet gemeten",
      bars: null,
      versionId: null,
      constituents: {},
      truth: { unknown_is_not_100: true, decorative_bars_forbidden_without_evidence: true },
    };
  }
  const bars = Math.max(0, Math.min(5, Math.round(score / 20)));
  return {
    measured: true,
    score,
    label: `${score}%`,
    bars,
    versionId: "ver-fixture-1",
    constituents: { errorCount: score < 80 ? 1 : 0, warningCount: score < 90 ? 2 : 0 },
    truth: { unknown_is_not_100: true, score_is_heuristic_not_absolute_truth: true },
  };
}

function ds(
  id: string,
  name: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    datasetId: id,
    name,
    displayName: overrides.displayName ?? name,
    primaryCategory: overrides.primaryCategory ?? "GENERAL",
    semanticTags: overrides.semanticTags ?? ["nl"],
    sourceType: overrides.sourceType ?? "local",
    status: overrides.status ?? "ready",
    description: overrides.description ?? `${name} corpus`,
    license: overrides.license ?? "CC BY-SA 4.0",
    schemaVersion: 1,
    byteSize: overrides.byteSize ?? 12_000_000_000,
    rowCount: overrides.rowCount ?? 1_200_000,
    detectedFormat: overrides.detectedFormat ?? "text",
    rawPath: overrides.rawPath ?? `/data/datasets/${id}`,
    createdAt: "2025-05-01T10:00:00.000Z",
    updatedAt: now,
    brainStatus: overrides.brainStatus ?? "learned",
    learned: overrides.learned ?? true,
    canonicalState: overrides.canonicalState ?? "LEARNED",
    quality: overrides.quality ?? quality(92),
    semanticProfile: {
      displayName: overrides.displayName ?? name,
      primaryCategory: overrides.primaryCategory ?? "GENERAL",
      tags: overrides.semanticTags ?? ["nl"],
      summary:
        overrides.summary ??
        "Gestructureerde corpus voor kennisverrijking, RAG en instruct-tuning.",
      confidence: 0.91,
      reviewRequired: false,
    },
    ...overrides,
  };
}

const DATASETS = [
  ds("nl_wiki_2024", "nl_wiki_2024", {
    displayName: "nl_wiki_2024",
    primaryCategory: "GENERAL",
    sourceType: "open",
    detectedFormat: "text",
    byteSize: 48_000_000_000,
    rowCount: 4_200_000,
    semanticTags: ["nl", "wiki", "kennis"],
    summary:
      "Nederlandse Wikipedia dump (2024) — opgeschoonde artikelen voor kennisverrijking, RAG en instruct-tuning.",
    quality: quality(96),
    license: "CC BY-SA 4.0",
  }),
  ds("code_instructions_v2", "code_instructions_v2", {
    primaryCategory: "TECHNOLOGY_SOFTWARE",
    sourceType: "huggingface",
    detectedFormat: "code",
    byteSize: 18_000_000_000,
    rowCount: 880_000,
    semanticTags: ["code", "instruct"],
    quality: quality(88),
    brainStatus: "idle",
    learned: false,
    canonicalState: "READY",
    status: "processed",
  }),
  ds("medical_knowledge", "medical_knowledge", {
    primaryCategory: "HEALTH_MEDICINE",
    sourceType: "local",
    detectedFormat: "text",
    byteSize: 12_000_000_000,
    rowCount: 420_000,
    semanticTags: ["medisch", "nl"],
    quality: quality(90),
  }),
  ds("synthetic_dialogues", "synthetic_dialogues", {
    primaryCategory: "GENERAL",
    sourceType: "synthetic",
    detectedFormat: "chat",
    byteSize: 6_200_000_000,
    rowCount: 210_000,
    semanticTags: ["chat", "nl"],
    status: "running",
    brainStatus: "indexing",
    learned: false,
    canonicalState: "INDEXING",
    quality: quality(null),
  }),
  ds("eu_legal_corpus", "eu_legal_corpus", {
    primaryCategory: "RESEARCH_PUBLICATIONS",
    sourceType: "open",
    detectedFormat: "text",
    byteSize: 22_000_000_000,
    rowCount: 560_000,
    semanticTags: ["legal", "eu"],
    quality: quality(84),
  }),
  ds("multilingual_news", "multilingual_news", {
    primaryCategory: "GENERAL",
    sourceType: "huggingface",
    detectedFormat: "text",
    byteSize: 31_000_000_000,
    rowCount: 1_100_000,
    semanticTags: ["news", "multi"],
    quality: quality(91),
  }),
  ds("agent_tool_logs", "agent_tool_logs", {
    primaryCategory: "TECHNOLOGY_SOFTWARE",
    sourceType: "local",
    detectedFormat: "log",
    byteSize: 1_800_000_000,
    rowCount: 420_000,
    semanticTags: ["agents", "logs"],
    quality: quality(78),
  }),
  ds("research_papers_v3", "research_papers_v3", {
    primaryCategory: "RESEARCH_PUBLICATIONS",
    sourceType: "local",
    detectedFormat: "pdf",
    byteSize: 14_000_000_000,
    rowCount: 85_000,
    semanticTags: ["research"],
    status: "warning",
    quality: quality(62),
    brainStatus: "failed",
    learned: false,
    canonicalState: "FAILED",
  }),
];

const VERSIONS: Record<string, Array<Record<string, unknown>>> = {
  nl_wiki_2024: [
    {
      versionId: "ver-nl-wiki-v1",
      datasetId: "nl_wiki_2024",
      versionLabel: "v1.0.0",
      status: "ready",
      kind: "materialized",
      rowCount: 4_200_000,
      byteSize: 48_000_000_000,
      split: { train: 1.0 },
      tokenStats: { total_tokens: 12_100_000 },
      validation: { errorCount: 0, warningCount: 2 },
      createdAt: "2025-05-10T10:00:00.000Z",
      updatedAt: now,
    },
  ],
};

for (const row of DATASETS) {
  const id = String(row.datasetId);
  if (!VERSIONS[id]) {
    VERSIONS[id] = [
      {
        versionId: `ver-${id}-v1`,
        datasetId: id,
        versionLabel: "v1.0.0",
        status: "ready",
        kind: "materialized",
        rowCount: row.rowCount,
        byteSize: row.byteSize,
        split: { train: 1.0 },
        tokenStats: { total_tokens: Math.round(Number(row.rowCount) * 2.5) },
        createdAt: "2025-05-10T10:00:00.000Z",
        updatedAt: now,
      },
    ];
  }
}

const PREVIEW_DEFAULT = [
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

export const DATASET_MGMT_V2_VISUAL_FIXTURE = {
  health: {
    ok: true,
    version: "fixture",
    database: "ok",
    reasoning_enabled: true,
    llm: { available: true, model: "fixture", base_url: "http://localhost" },
  },
  overview: {
    totalDatasets: 248,
    totalSamples: 48_700_000,
    samplesMeasuredDatasets: 230,
    samplesUnmeasuredDatasets: 18,
    samplesMeasurementComplete: false,
    samplesMeasurementStatus: "PARTIAL",
    totalKnownBytes: 456 * 1024 ** 3,
    bytesMeasuredDatasets: 240,
    bytesUnmeasuredDatasets: 8,
    storage: {
      usedBytes: 456 * 1024 ** 3,
      capacityBytes: 1024 ** 4,
      freeBytes: (1024 - 456) * 1024 ** 3,
      usedPercent: 46,
      breakdown: [
        { id: "datasets", label: "Datasets", bytes: 320 * 1024 ** 3, provenance: "MEASURED" },
        { id: "indexes", label: "Indexen", bytes: 80 * 1024 ** 3, provenance: "MEASURED" },
        { id: "cache", label: "Cache", bytes: 36 * 1024 ** 3, provenance: "MEASURED" },
        { id: "exports", label: "Exports", bytes: 20 * 1024 ** 3, provenance: "MEASURED" },
      ],
      measurementStatus: "PARTIAL",
      truth: {
        capacity_is_filesystem_disk_usage: true,
        used_is_sum_of_known_dataset_byte_size: true,
      },
    },
    activeImports: 3,
    activeImportsRunning: 2,
    activeImportsQueued: 1,
    validationIssues: 17,
    criticalValidationIssues: 5,
    validationWarnings: 12,
    validationErrors: 5,
    datasetsWithValidation: 180,
    datasetsWithoutValidation: 68,
    catalogStatus: {
      label: "Gezond",
      state: "HEALTHY",
      lastReconcileAt: "2025-05-25T14:33:12.000Z",
      entryCount: 248,
    },
    byStatus: { ready: 200, running: 3, warning: 8, failed: 2 },
    bySource: { open: 80, huggingface: 70, local: 90, synthetic: 8 },
    tagCounts: {
      nl: 48,
      wiki: 48,
      kennis: 41,
      code: 31,
      instruct: 24,
      chat: 19,
      legal: 14,
      eu: 12,
      research: 11,
      news: 9,
    },
    truth: {
      kpis_are_not_page_length: true,
      null_row_count_is_not_zero_samples: true,
      no_hardcoded_screen1_metrics: true,
    },
  },
  datasets: DATASETS,
  selectedDatasetId: "nl_wiki_2024",
  detail: DATASETS[0],
  versions: VERSIONS,
  recovery: {
    nl_wiki_2024: {
      datasetId: "nl_wiki_2024",
      recoveryState: "READY",
      state: "READY",
      sourcePresent: true,
      metadataRestored: false,
      reindexRequired: false,
      detail: "Automatisch",
    },
  } as Record<string, Record<string, unknown>>,
  preview: {
    "ver-nl-wiki-v1": PREVIEW_DEFAULT,
  } as Record<string, Array<Record<string, unknown>>>,
  previewDefault: PREVIEW_DEFAULT,
  jobs: [
    {
      jobId: "job-import-1",
      datasetId: "synthetic_dialogues",
      jobType: "import_huggingface",
      status: "running",
      progress: 0.68,
      phase: "download",
      createdAt: "2025-05-25T14:02:00.000Z",
      updatedAt: now,
      download: {
        bytesDownloaded: 4_200_000_000,
        bytesTotal: 6_200_000_000,
        bytesPerSecond: 324_000_000,
      },
    },
    {
      jobId: "job-validate-1",
      datasetId: "research_papers_v3",
      jobType: "validate",
      status: "queued",
      progress: 0,
      createdAt: now,
      updatedAt: now,
    },
    {
      jobId: "job-semantic-1",
      datasetId: "nl_wiki_2024",
      jobType: "semantic_analyze",
      status: "completed",
      progress: 1,
      createdAt: "2025-05-25T12:40:00.000Z",
      updatedAt: "2025-05-25T12:55:00.000Z",
      result: { ok: true },
    },
    {
      jobId: "job-export-1",
      datasetId: "nl_wiki_2024",
      versionId: "ver-nl-wiki-v1",
      jobType: "export",
      status: "completed",
      progress: 1,
      createdAt: "2025-05-25T13:10:00.000Z",
      updatedAt: "2025-05-25T13:18:00.000Z",
      result: { versionId: "ver-export-nl-wiki", ok: true },
    },
    {
      jobId: "job-export-2",
      datasetId: "code_instructions_v2",
      versionId: "ver-code-v1",
      jobType: "export",
      status: "completed",
      progress: 1,
      createdAt: "2025-05-25T11:00:00.000Z",
      updatedAt: "2025-05-25T11:20:00.000Z",
      result: { versionId: "ver-export-code", ok: true },
    },
    {
      jobId: "job-export-3",
      datasetId: "medical_knowledge",
      jobType: "export",
      status: "completed",
      progress: 1,
      createdAt: "2025-05-25T10:00:00.000Z",
      updatedAt: "2025-05-25T10:12:00.000Z",
      result: { versionId: "ver-export-med", ok: true },
    },
  ],
  exportArtifact: {
    datasetId: "nl_wiki_2024",
    versionId: "ver-export-nl-wiki",
    jobId: "job-export-1",
  },
} as const;

export function isDatasetManagementVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  const flag = (window as Window & { __LV_V2_VISUAL_FIXTURE__?: unknown }).__LV_V2_VISUAL_FIXTURE__;
  return flag === "dataset-management";
}
