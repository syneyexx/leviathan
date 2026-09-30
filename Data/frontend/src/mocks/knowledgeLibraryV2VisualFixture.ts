/**
 * TEST-ONLY Knowledge Library V2 visual fixture.
 *
 * Activated solely via Playwright route mocking + window.__LV_V2_FROZEN_NOW__ /
 * __LV_V2_VISUAL_FIXTURE__ === "knowledge". Production Knowledge pages and hooks
 * must NEVER import these values as fallbacks or defaults.
 */

export const KNOWLEDGE_LIBRARY_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26.000Z";

const now = KNOWLEDGE_LIBRARY_V2_VISUAL_FROZEN_ISO;
const TB = 1024 ** 4;
const GB = 1024 ** 3;
const MB = 1024 ** 2;

function item(
  id: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id,
    title: overrides.title ?? id,
    source: "fixture",
    status: "READY",
    library_type: "document",
    library_type_label: "Documenten",
    size_bytes: 4.2 * MB,
    size_measured: true,
    created_at: now,
    updated_at: now,
    tags: ["finance", "trading"],
    parser: "pdf",
    content_hash: "abc",
    mime_type: "application/pdf",
    page_count: 342,
    error: null,
    truth: { summary_excludes_content: true, summary_excludes_chunks: true, unmeasured_size_is_not_zero: false },
    ...overrides,
  };
}

export const KNOWLEDGE_LIBRARY_V2_VISUAL_FIXTURE = {
  health: { status: "ok" },
  overview: {
    total_sources: 124_532,
    measured_bytes: Math.round(1.42 * TB),
    measured_sources: 120_000,
    unknown_size_sources: 4_532,
    size_coverage_percent: 96.36,
    source_type_count: 18,
    source_type_counts: [
      { id: "document", label: "Documenten", count: 42_000 },
      { id: "book", label: "Boeken", count: 2_000 },
      { id: "research_paper", label: "Research Papers", count: 18_000 },
      { id: "market_data", label: "Markt Data", count: 8_000 },
      { id: "financial_data", label: "Financiële Data", count: 6_000 },
      { id: "code", label: "Code", count: 9_000 },
      { id: "web", label: "Web Content", count: 7_000 },
      { id: "note", label: "Notities", count: 5_000 },
      { id: "conversation", label: "Gesprekken", count: 3_000 },
      { id: "image", label: "Afbeeldingen", count: 4_000 },
      { id: "table", label: "Tabellen", count: 11_000 },
      { id: "other", label: "Overige", count: 9_532 },
    ],
    top_tags: [
      { tag: "finance", count: 12_000 },
      { tag: "trading", count: 11_000 },
      { tag: "ai", count: 8_000 },
      { tag: "economy", count: 6_500 },
      { tag: "markets", count: 6_000 },
      { tag: "strategy", count: 5_200 },
      { tag: "blockchain", count: 4_100 },
      { tag: "technical", count: 3_800 },
      { tag: "fundamental", count: 3_200 },
      { tag: "risk", count: 2_900 },
    ],
    tag_vocabulary_size: 48,
    embedding: {
      status: "OK",
      coverage_percent: 100,
      chunks_total: 500_000,
      chunks_embedded: 500_000,
      chunks_missing: 0,
      provider_id: "fixture",
      provider_configured: true,
      provider_available: true,
    },
    latest_ingestion: {
      title: "market_data_2024_Q1.parquet",
      created_at: "2025-05-25T14:22:11.000Z",
      updated_at: "2025-05-25T14:22:11.000Z",
      status: "completed",
      source: "source_ingestion",
      size_bytes: 1.8 * GB,
      kind: "source_ingestion",
      progress_pct: 100,
      measured: true,
    },
    // Deterministic visual-only history — never used as production fallback.
    sparks: {
      total_sources: [82, 90, 95, 98, 104, 110, 118, 124],
      measured_bytes: [70, 78, 85, 92, 100, 112, 125, 142],
    },
    truth: {
      total_sources_are_knowledge_documents: true,
      does_not_count_chunks_as_sources: true,
      fixture_only: true,
    },
  },
  library: {
    items: [
      item("opts-handbook", {
        title: "Options Trading Strategies Handbook",
        library_type: "document",
        library_type_label: "Documenten",
        size_bytes: 4.2 * MB,
        page_count: 342,
        tags: ["finance", "options", "strategy"],
      }),
      item("btc-parquet", {
        title: "BTC_USDT_1m_2018_2024.parquet",
        library_type: "table",
        library_type_label: "Tabellen",
        size_bytes: 1.8 * GB,
        mime_type: "application/x-parquet",
        parser: "parquet",
        page_count: null,
        tags: ["markets", "crypto"],
      }),
      item("vol-guide", {
        title: "Volatility Trading Guide",
        library_type: "document",
        library_type_label: "Documenten",
        size_bytes: 2.1 * MB,
        tags: ["trading", "risk"],
      }),
      item("adv-options", {
        title: "Advanced Options Strategies",
        library_type: "document",
        library_type_label: "Documenten",
        size_bytes: 3.4 * MB,
        tags: ["finance", "strategy"],
      }),
      item("macro-notes", {
        title: "Macro Regime Notes 2024",
        library_type: "note",
        library_type_label: "Notities",
        mime_type: "text/markdown",
        parser: "text",
        size_bytes: 128 * 1024,
        page_count: null,
        tags: ["economy", "fundamental"],
      }),
      item("exec-engine", {
        title: "execution_engine.py",
        library_type: "code",
        library_type_label: "Code",
        mime_type: "text/x-python",
        parser: "code",
        size_bytes: 86 * 1024,
        page_count: null,
        tags: ["trading", "technical"],
      }),
      item("fed-paper", {
        title: "Federal Reserve Working Paper 2023-18",
        library_type: "research_paper",
        library_type_label: "Research Papers",
        size_bytes: 1.1 * MB,
        page_count: 48,
        tags: ["economy", "markets"],
      }),
      item("orderbook-csv", {
        title: "orderbook_snapshots_may.csv",
        library_type: "market_data",
        library_type_label: "Markt Data",
        mime_type: "text/csv",
        size_bytes: 420 * MB,
        page_count: null,
        tags: ["markets", "trading"],
      }),
    ],
    total: 124_532,
    limit: 50,
    offset: 0,
    has_more: true,
    next_offset: 50,
    next_cursor: "50",
    sort: "updated_desc",
  },
  recentIngestions: {
    items: [
      {
        source_id: "ing-active",
        filename: "market_data_2024_Q1.parquet",
        created_at: "2025-05-25T14:30:00.000Z",
        size_bytes: 1.8 * GB,
        status: "parsing",
        phase: "parsing",
        progress_pct: 67,
        measured: true,
      },
      {
        source_id: "ing-1",
        filename: "Options Trading Strategies Handbook.pdf",
        created_at: "2025-05-25T14:22:11.000Z",
        size_bytes: 4.2 * MB,
        status: "completed",
        phase: "completed",
        progress_pct: 100,
        measured: true,
      },
      {
        source_id: "ing-2",
        filename: "BTC_USDT_1m_2018_2024.parquet",
        created_at: "2025-05-25T13:10:00.000Z",
        size_bytes: 1.8 * GB,
        status: "completed",
        phase: "completed",
        progress_pct: 100,
        measured: true,
      },
      {
        source_id: "ing-3",
        filename: "Volatility Trading Guide.pdf",
        created_at: "2025-05-25T12:05:00.000Z",
        size_bytes: 2.1 * MB,
        status: "completed",
        phase: "completed",
        progress_pct: 100,
        measured: true,
      },
      {
        source_id: "ing-4",
        filename: "execution_engine.py",
        created_at: "2025-05-25T11:40:00.000Z",
        size_bytes: 86 * 1024,
        status: "completed",
        phase: "completed",
        progress_pct: 100,
        measured: true,
      },
    ],
    limit: 12,
    offset: 0,
  },
  activeProgress: {
    source_id: "ing-active",
    filename: "market_data_2024_Q1.parquet",
    phase: "parsing",
    status: "parsing",
    progress_pct: 67,
    measured: true,
    bytes_processed: 1.2 * GB,
    bytes_total: 1.8 * GB,
    eta_seconds: 120,
  },
  related: [
    item("adv-options", {
      title: "Advanced Options Strategies",
      size_bytes: 3.4 * MB,
      relationship_kind: "semantic",
    }),
    item("vol-guide", {
      title: "Volatility Trading Guide",
      size_bytes: 2.1 * MB,
      relationship_kind: "semantic",
    }),
    item("fed-paper", {
      title: "Federal Reserve Working Paper 2023-18",
      library_type: "research_paper",
      library_type_label: "Research Papers",
      size_bytes: 1.1 * MB,
      relationship_kind: "metadata",
    }),
  ],
  previewHtml: `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;height:100%;background:#0b1220;font-family:Georgia,serif;color:#f5f7fb}
    .cover{height:100%;display:flex;align-items:center;justify-content:center;padding:18px;box-sizing:border-box}
    .book{width:72%;aspect-ratio:3/4;background:linear-gradient(160deg,#102a43,#243b53 55%,#0b1d33);
      border:1px solid rgba(125,211,252,.35);box-shadow:0 10px 30px rgba(0,0,0,.55);padding:28px 22px;box-sizing:border-box}
      display:flex;flex-direction:column;justify-content:space-between}
    .eyebrow{font:11px/1.2 ui-sans-serif,system-ui;letter-spacing:.14em;text-transform:uppercase;color:#7dd3fc}
    h1{margin:18px 0 0;font-size:22px;line-height:1.2}
    .sub{margin-top:10px;font:12px/1.4 ui-sans-serif,system-ui;color:#cbd5e1}
    .footer{font:10px/1.2 ui-sans-serif,system-ui;color:#94a3b8;border-top:1px solid rgba(148,163,184,.25);padding-top:10px}
  </style></head><body><div class="cover"><div class="book">
    <div><div class="eyebrow">Knowledge Library</div>
    <h1>Options Trading Strategies Handbook</h1>
    <div class="sub">342 pagina's · PDF Document · 4.2 MB</div></div>
    <div class="footer">Fixture preview — not production content</div>
  </div></div></body></html>`,
};
