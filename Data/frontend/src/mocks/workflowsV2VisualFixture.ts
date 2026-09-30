/**
 * TEST-ONLY Screen Workflows V2 visual fixture.
 * Activated solely when window.__LV_V2_VISUAL_FIXTURE__ === 'workflows'.
 * Never imported by production page defaults — useWorkflowsWorkspace applies it
 * only behind that flag (Playwright / visual regression).
 */

import type {
  WorkflowDefinition,
  WorkflowExecution,
  WorkflowOverview,
  WorkflowPalette,
  WorkflowRecord,
} from "../types/api";

export const WORKFLOWS_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26.000Z";

const FROZEN_MS = Date.parse(WORKFLOWS_V2_VISUAL_FROZEN_ISO);

function ago(ms: number): string {
  return new Date(FROZEN_MS - ms).toISOString();
}

/** Research Pipeline graph matching the reference canvas. */
export const RESEARCH_PIPELINE_GRAPH = {
  nodes: [
    {
      node_id: "n-trigger",
      kind: "trigger",
      label: "Trigger",
      config: { subtype: "schedule", schedule: "0 */6 * * *" },
    },
    {
      node_id: "n-web-search",
      kind: "tool",
      label: "Web Search",
      config: { capability_id: "tool.web_search" },
    },
    {
      node_id: "n-research-agent",
      kind: "agent",
      label: "Research Agent",
      config: { capability_id: "agent.research" },
    },
    {
      node_id: "n-data-transform",
      kind: "data",
      label: "Data Transform",
      config: { capability_id: "data.transform" },
    },
    {
      node_id: "n-condition",
      kind: "condition",
      label: "Condition",
      config: { expression: "Voldoende data?" },
    },
    {
      node_id: "n-generate-report",
      kind: "tool",
      label: "Generate Report",
      config: { capability_id: "tool.generate_report" },
    },
    {
      node_id: "n-save-knowledge",
      kind: "agent",
      label: "Save to Knowledge",
      config: { capability_id: "agent.knowledge_save" },
    },
    {
      node_id: "n-notify",
      kind: "tool",
      label: "Notify",
      config: { capability_id: "tool.notify" },
    },
  ],
  edges: [
    { edge_id: "e1", source: "n-trigger", target: "n-web-search" },
    { edge_id: "e2", source: "n-web-search", target: "n-research-agent" },
    { edge_id: "e3", source: "n-web-search", target: "n-data-transform" },
    { edge_id: "e4", source: "n-research-agent", target: "n-condition" },
    { edge_id: "e5", source: "n-data-transform", target: "n-condition" },
    {
      edge_id: "e6",
      source: "n-condition",
      target: "n-generate-report",
      source_handle: "yes",
      label: "Ja",
    },
    {
      edge_id: "e7",
      source: "n-condition",
      target: "n-notify",
      source_handle: "no",
      label: "Nee",
    },
    { edge_id: "e8", source: "n-generate-report", target: "n-save-knowledge" },
  ],
};

export const RESEARCH_PIPELINE_LAYOUT = [
  { node_id: "n-trigger", x: 40, y: 40 },
  { node_id: "n-web-search", x: 220, y: 40 },
  { node_id: "n-research-agent", x: 400, y: 20 },
  { node_id: "n-data-transform", x: 400, y: 140 },
  { node_id: "n-condition", x: 580, y: 70 },
  { node_id: "n-generate-report", x: 760, y: 20 },
  { node_id: "n-save-knowledge", x: 940, y: 20 },
  { node_id: "n-notify", x: 760, y: 160 },
];

function def(
  id: string,
  name: string,
  status: "ACTIVE" | "INACTIVE" | "TEMPLATE" | "DRAFT",
  overrides: Partial<WorkflowDefinition> = {},
): WorkflowDefinition {
  const isResearch = id === "wf-research-pipeline";
  return {
    workflow_id: id,
    name,
    description:
      overrides.description ??
      (isResearch
        ? "Zoekt actuele informatie, analyseert deze met AI agents en genereert research rapporten."
        : `${name} automatisering`),
    category: overrides.category ?? (status === "TEMPLATE" ? "Templates" : "Research"),
    tags: overrides.tags ?? ["automation"],
    status,
    definition_status: status,
    current_version: overrides.current_version ?? 3,
    graph: overrides.graph ?? (isResearch ? RESEARCH_PIPELINE_GRAPH : { nodes: [], edges: [] }),
    variables: overrides.variables ?? [
      { name: "query", type: "string", default: "", required: true, description: "Zoekquery" },
      { name: "max_results", type: "number", default: 10, required: false },
    ],
    layout: overrides.layout ?? (isResearch ? RESEARCH_PIPELINE_LAYOUT : []),
    config: overrides.config ?? {},
    trigger_bindings: overrides.trigger_bindings ?? [{ type: "schedule", cron: "0 */6 * * *" }],
    triggers: overrides.triggers ?? [{ type: "schedule", label: "Schedule" }],
    revision: overrides.revision ?? 3,
    created_at: overrides.created_at ?? ago(14 * 86400_000),
    updated_at: overrides.updated_at ?? ago(120_000),
    metadata: overrides.metadata ?? {},
    tools: overrides.tools ?? (isResearch ? 3 : 1),
    agents: overrides.agents ?? (isResearch ? 2 : 0),
    mcp_servers: overrides.mcp_servers ?? (isResearch ? 1 : 0),
    execution_count: overrides.execution_count ?? (isResearch ? 342 : 40),
    avg_duration_ms: overrides.avg_duration_ms ?? (isResearch ? 138_000 : 90_000),
    running_executions: overrides.running_executions ?? 0,
  };
}

const ACTIVE_NAMES = [
  ["wf-research-pipeline", "Research Pipeline"],
  ["wf-market-analysis", "Market Analysis"],
  ["wf-news-digest", "News Digest"],
  ["wf-data-sync", "Data Sync"],
  ["wf-risk-scan", "Risk Scanner"],
  ["wf-report-gen", "Report Generator"],
  ["wf-agent-brief", "Agent Briefing"],
  ["wf-corpus-index", "Corpus Indexer"],
] as const;

const INACTIVE_NAMES = [
  ["wf-legacy-etl", "Legacy ETL"],
  ["wf-old-alerts", "Old Alerts"],
  ["wf-draft-trade", "Trade Draft"],
  ["wf-pause-monitor", "Pause Monitor"],
  ["wf-archive-nightly", "Nightly Archive"],
  ["wf-stale-enrich", "Stale Enrichment"],
  ["wf-beta-router", "Beta Router"],
  ["wf-idle-cleanup", "Idle Cleanup"],
  ["wf-shadow-eval", "Shadow Eval"],
  ["wf-tmp-batch", "Tmp Batch"],
  ["wf-hold-notify", "Hold Notify"],
  ["wf-cold-reindex", "Cold Reindex"],
] as const;

const DRAFT_NAMES = [
  ["wf-draft-alpha", "Draft Alpha"],
  ["wf-draft-beta", "Draft Beta"],
  ["wf-draft-gamma", "Draft Gamma"],
  ["wf-draft-delta", "Draft Delta"],
] as const;

const TEMPLATE_NAMES = [
  ["wf-tpl-research", "Research Template"],
  ["wf-tpl-ingest", "Ingest Template"],
  ["wf-tpl-notify", "Notify Template"],
  ["wf-tpl-agent", "Agent Chain Template"],
  ["wf-tpl-etl", "ETL Template"],
  ["wf-tpl-report", "Report Template"],
] as const;

export const WORKFLOWS_V2_DEFINITIONS: WorkflowDefinition[] = [
  ...ACTIVE_NAMES.map(([id, name], i) =>
    def(id, name, "ACTIVE", {
      updated_at: ago((i + 1) * 120_000),
      category: i % 2 === 0 ? "Research" : "Trading",
      running_executions: i < 4 ? 1 : 0,
      execution_count: id === "wf-research-pipeline" ? 342 : 80 - i * 7,
    }),
  ),
  ...INACTIVE_NAMES.map(([id, name], i) =>
    def(id, name, "INACTIVE", {
      updated_at: ago((i + 5) * 3600_000),
      category: i % 3 === 0 ? "Data" : "Ops",
      execution_count: 12 + i,
    }),
  ),
  ...DRAFT_NAMES.map(([id, name], i) =>
    def(id, name, "DRAFT", {
      updated_at: ago((i + 1) * 7200_000),
      category: "Research",
      execution_count: 0,
    }),
  ),
  ...TEMPLATE_NAMES.map(([id, name], i) =>
    def(id, name, "TEMPLATE", {
      updated_at: ago((i + 2) * 86400_000),
      category: "Templates",
      execution_count: 0,
      agents: 1,
      tools: 2,
    }),
  ),
];

export const WORKFLOWS_V2_PALETTE: WorkflowPalette = {
  Agents: [
    { id: "agent.research", kind: "agent", label: "Research Agent", category: "Agents", available: true },
    { id: "agent.analysis", kind: "agent", label: "Analysis Agent", category: "Agents", available: true },
    { id: "agent.knowledge_save", kind: "agent", label: "Knowledge Agent", category: "Agents", available: true },
  ],
  Tools: [
    { id: "tool.web_search", kind: "tool", label: "Web Search", category: "Tools", available: true },
    { id: "tool.file_processor", kind: "tool", label: "File Processor", category: "Tools", available: true },
    { id: "tool.api_request", kind: "tool", label: "API Request", category: "Tools", available: true },
    { id: "tool.generate_report", kind: "tool", label: "Generate Report", category: "Tools", available: true },
    { id: "tool.notify", kind: "tool", label: "Notify", category: "Tools", available: true },
  ],
  Data: [
    { id: "data.dataset_loader", kind: "data", label: "Dataset Loader", category: "Data", available: true },
    { id: "data.vector_search", kind: "data", label: "Vector Search", category: "Data", available: true },
    { id: "data.transform", kind: "data", label: "Data Transform", category: "Data", available: true },
  ],
  Control: [
    { id: "control.condition", kind: "condition", label: "Condition", category: "Control", available: true },
    { id: "control.loop", kind: "loop", label: "Loop", category: "Control", available: true },
    { id: "control.delay", kind: "delay", label: "Delay", category: "Control", available: true },
    {
      id: "control.trigger.schedule",
      kind: "trigger",
      label: "Schedule Trigger",
      category: "Control",
      available: true,
    },
  ],
};

function execution(
  id: string,
  workflowId: string,
  name: string,
  state: string,
  startedAgoMs: number,
  durationMs: number | null,
): WorkflowExecution {
  const started = ago(startedAgoMs);
  return {
    execution_id: id,
    workflow_id: workflowId,
    workflow_version: 3,
    state,
    trigger_source: "schedule",
    created_at: started,
    updated_at: durationMs != null ? ago(startedAgoMs - durationMs) : started,
    started_at: started,
    ended_at: durationMs != null ? ago(startedAgoMs - durationMs) : null,
    duration_ms: durationMs,
    name,
    error: state === "FAILED" ? "Timeout waiting for agent" : null,
  };
}

export const WORKFLOWS_V2_RECENT_EXECUTIONS: WorkflowExecution[] = [
  execution("ex-1", "wf-research-pipeline", "Research Pipeline", "COMPLETED", 15 * 60_000, 126_000),
  execution("ex-2", "wf-market-analysis", "Market Analysis", "COMPLETED", 28 * 60_000, 98_000),
  execution("ex-3", "wf-news-digest", "News Digest", "FAILED", 42 * 60_000, 45_000),
  execution("ex-4", "wf-research-pipeline", "Research Pipeline", "COMPLETED", 55 * 60_000, 132_000),
  execution("ex-5", "wf-data-sync", "Data Sync", "COMPLETED", 70 * 60_000, 61_000),
  execution("ex-6", "wf-risk-scan", "Risk Scanner", "CANCELLED", 95 * 60_000, 12_000),
  execution("ex-7", "wf-report-gen", "Report Generator", "COMPLETED", 110 * 60_000, 210_000),
  execution("ex-8", "wf-agent-brief", "Agent Briefing", "FAILED", 140 * 60_000, 33_000),
];

export const WORKFLOWS_V2_OVERVIEW: WorkflowOverview = {
  generated_at: WORKFLOWS_V2_VISUAL_FROZEN_ISO,
  counts: {
    total_definitions: 24,
    active_definitions: 8,
    inactive_definitions: 12,
    draft_definitions: 4,
    templates: 6,
    running_executions: 4,
  },
  kpis: [
    {
      id: "total_workflows",
      label: "Totale Workflows",
      value: 24,
      secondary: "+3 deze week",
      change: { value: 3, display: "+3 deze week", direction: "up" },
      sparkline: [18, 19, 20, 20, 21, 22, 23, 24],
    },
    {
      id: "active_workflows",
      label: "Actieve Workflows",
      value: 8,
      secondary: "4 draaien",
      change: { value: null, display: "4 draaien", direction: "flat" },
      sparkline: [5, 6, 6, 7, 7, 8, 8, 8],
    },
    {
      id: "success_rate",
      label: "Succes Rate",
      value: 92.4,
      unit: "%",
      secondary: null,
      change: { value: 2.1, display: "+2.1%", direction: "up" },
      sparkline: [88, 89, 90, 90, 91, 91, 92, 92.4],
    },
    {
      id: "avg_duration",
      label: "Gem. Uitvoeringstijd",
      value: 2.3,
      unit: "min",
      secondary: null,
      change: { value: -18, display: "-18%", direction: "down" },
      sparkline: [3.1, 2.9, 2.8, 2.6, 2.5, 2.4, 2.35, 2.3],
    },
    {
      id: "total_executions",
      label: "Totaal Executies",
      value: 1842,
      secondary: null,
      change: { value: 12, display: "+12% t.o.v. vorige week", direction: "up" },
      sparkline: [120, 140, 135, 150, 160, 155, 170, 180],
    },
  ],
  chart: {
    period: "last_24h",
    buckets: Array.from({ length: 12 }, (_, i) => ({
      bucket_start: ago((11 - i) * 3600_000),
      succeeded: [2, 3, 4, 5, 3, 6, 4, 5, 3, 4, 2, 1][i] ?? 2,
      failed: [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1][i] ?? 0,
      cancelled: i === 5 || i === 9 ? 1 : 0,
    })),
    series: { succeeded: 42, failed: 6, cancelled: 2 },
  },
  top_workflows: {
    period: "last_7d",
    items: [
      { workflow_id: "wf-research-pipeline", name: "Research Pipeline", execution_count: 128, rank: 1, relative: 1 },
      { workflow_id: "wf-market-analysis", name: "Market Analysis", execution_count: 96, rank: 2, relative: 0.75 },
      { workflow_id: "wf-news-digest", name: "News Digest", execution_count: 72, rank: 3, relative: 0.56 },
      { workflow_id: "wf-data-sync", name: "Data Sync", execution_count: 54, rank: 4, relative: 0.42 },
      { workflow_id: "wf-risk-scan", name: "Risk Scanner", execution_count: 41, rank: 5, relative: 0.32 },
    ],
  },
  recent_executions: WORKFLOWS_V2_RECENT_EXECUTIONS,
  resources: {
    cpu: { available: true, utilization_pct: 42, display: "42%" },
    memory: {
      available: true,
      used_bytes: 6.8 * 1024 ** 3,
      total_bytes: 16 * 1024 ** 3,
      display: "6.8 GB van 16 GB",
    },
    workers: {
      available: true,
      busy: 3,
      capacity: 4,
      display: "3 van 4",
      semantics: "BUSY workers / desired capacity for workflow pool",
    },
  },
};

export const WORKFLOWS_V2_VERSIONS = [
  {
    version: 3,
    created_at: ago(2 * 86400_000),
    change_summary: "Condition branching + Notify path",
    created_by: "operator",
  },
  {
    version: 2,
    created_at: ago(7 * 86400_000),
    change_summary: "Added Data Transform node",
    created_by: "operator",
  },
  {
    version: 1,
    created_at: ago(14 * 86400_000),
    change_summary: "Initial Research Pipeline",
    created_by: "system",
  },
];

export const WORKFLOWS_V2_LOGS = [
  { ts: ago(15 * 60_000), level: "INFO", message: "Execution started (schedule)" },
  { ts: ago(14 * 60_000), level: "INFO", message: "Node Trigger completed" },
  { ts: ago(13 * 60_000), level: "INFO", message: "Web Search: 12 results" },
  { ts: ago(12 * 60_000), level: "INFO", message: "Research Agent: analysis complete" },
  { ts: ago(11 * 60_000), level: "INFO", message: "Condition: Ja — generating report" },
  { ts: ago(10 * 60_000), level: "INFO", message: "Saved to Knowledge base" },
  { ts: ago(9 * 60_000), level: "INFO", message: "Execution COMPLETED (2.1 min)" },
];

export const WORKFLOWS_V2_VISUAL_FIXTURE = {
  selectedWorkflowId: "wf-research-pipeline",
  definitions: WORKFLOWS_V2_DEFINITIONS,
  overview: WORKFLOWS_V2_OVERVIEW,
  palette: WORKFLOWS_V2_PALETTE,
  templates: WORKFLOWS_V2_DEFINITIONS.filter((d) => d.status === "TEMPLATE") as unknown as WorkflowRecord[],
  versions: WORKFLOWS_V2_VERSIONS,
  executions: WORKFLOWS_V2_RECENT_EXECUTIONS.filter((e) => e.workflow_id === "wf-research-pipeline"),
  logs: WORKFLOWS_V2_LOGS,
  frozenIso: WORKFLOWS_V2_VISUAL_FROZEN_ISO,
} as const;

export function isWorkflowsVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  const flag = (window as Window & { __LV_V2_VISUAL_FIXTURE__?: unknown }).__LV_V2_VISUAL_FIXTURE__;
  return flag === "workflows";
}
