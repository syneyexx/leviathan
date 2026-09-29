/**
 * TEST-ONLY deterministic Screen 1 Brain fixture for visual regression.
 * Activated solely via Playwright route mocking + window.__LV_V2_VISUAL_FIXTURE__.
 * Never imported into production BrainPage data paths as defaults.
 */

export const BRAIN_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26";

type FixtureNode = {
  id: string;
  type: string;
  label: string;
  created_at: string;
  meta?: Record<string, unknown>;
};

type FixtureEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

const FIXTURE_NODES: FixtureNode[] = [
  {
    id: "agent:ai-agents",
    type: "agent",
    label: "AI Agents",
    created_at: "2025-05-20T09:00:00",
    meta: { description: "Centrale agent-runtime en orchestratiehub." },
  },
  {
    id: "concept:bitcoin",
    type: "concept",
    label: "Bitcoin",
    created_at: "2025-05-25T10:24:17",
    meta: {
      description: "Primaire cryptocurrency en digitaal asset",
      confidence: 0.92,
      updated_at: "2025-05-25T10:24:17",
      summary:
        "Gedecentraliseerd digitaal asset met netwerkconsensus. Kernentiteit in trading- en research-kennis.",
    },
  },
  {
    id: "concept:markt-analyse",
    type: "concept",
    label: "Markt Analyse",
    created_at: "2025-05-24T12:00:00",
  },
  {
    id: "concept:trading-strategie",
    type: "concept",
    label: "Trading Strategie",
    created_at: "2025-05-24T11:00:00",
  },
  {
    id: "concept:ethereum",
    type: "concept",
    label: "Ethereum",
    created_at: "2025-05-23T10:00:00",
  },
  {
    id: "concept:macro",
    type: "concept",
    label: "Macro Economie",
    created_at: "2025-05-22T10:00:00",
  },
  {
    id: "concept:regulatie",
    type: "concept",
    label: "Regulatie",
    created_at: "2025-05-21T10:00:00",
  },
  {
    id: "concept:defi",
    type: "concept",
    label: "DeFi",
    created_at: "2025-05-20T10:00:00",
  },
  {
    id: "concept:ta",
    type: "concept",
    label: "Technische Analyse",
    created_at: "2025-05-19T10:00:00",
  },
  {
    id: "concept:ml",
    type: "concept",
    label: "Machine Learning",
    created_at: "2025-05-18T10:00:00",
  },
  {
    id: "entity:web3",
    type: "research.project",
    label: "Web3",
    created_at: "2025-05-17T10:00:00",
  },
  {
    id: "concept:risico",
    type: "concept",
    label: "Risico Management",
    created_at: "2025-05-16T10:00:00",
  },
  {
    id: "doc:market-report",
    type: "knowledge.document",
    label: "Market Report Q2",
    created_at: "2025-05-25T14:22:00",
  },
  {
    id: "memory:cluster-markt",
    type: "memory",
    label: "Markt geheugen",
    created_at: "2025-05-25T14:10:00",
  },
  {
    id: "evidence:btc-1",
    type: "evidence",
    label: "BTC on-chain proof",
    created_at: "2025-05-25T13:55:00",
  },
  {
    id: "agent:trader",
    type: "agent",
    label: "Trader Agent",
    created_at: "2025-05-15T10:00:00",
  },
  {
    id: "entity:person-satoshi",
    type: "research.project",
    label: "Satoshi Research",
    created_at: "2025-05-14T10:00:00",
  },
  {
    id: "doc:reg-note",
    type: "knowledge.document",
    label: "Regulatory Note",
    created_at: "2025-05-13T10:00:00",
  },
];

function buildDenseNodes(): FixtureNode[] {
  const extra: FixtureNode[] = [];
  for (let i = 0; i < 40; i += 1) {
    const types = ["concept", "research.project", "knowledge.document", "agent", "memory", "evidence"] as const;
    const type = types[i % types.length];
    extra.push({
      id: `extra:${i}`,
      type,
      label: `Node ${i}`,
      created_at: `2025-05-${String(10 + (i % 15)).padStart(2, "0")}T10:00:00`,
    });
  }
  return [...FIXTURE_NODES, ...extra];
}

function buildEdges(nodes: FixtureNode[]): FixtureEdge[] {
  const edges: FixtureEdge[] = [];
  const focal = "agent:ai-agents";
  const btc = "concept:bitcoin";
  const hubs = [
    "concept:markt-analyse",
    "concept:trading-strategie",
    "concept:ethereum",
    "concept:macro",
    "concept:regulatie",
    "concept:defi",
    "concept:ta",
    "concept:ml",
    "entity:web3",
    "concept:risico",
    "doc:market-report",
    "memory:cluster-markt",
    "evidence:btc-1",
    "agent:trader",
  ];
  let i = 0;
  for (const h of hubs) {
    edges.push({ id: `e-focal-${i}`, source: focal, target: h, relation: "related" });
    i += 1;
  }
  edges.push(
    { id: "e-btc-markt", source: btc, target: "concept:markt-analyse", relation: "related" },
    { id: "e-btc-eth", source: btc, target: "concept:ethereum", relation: "related" },
    { id: "e-btc-defi", source: btc, target: "concept:defi", relation: "related" },
    { id: "e-btc-risk", source: btc, target: "concept:risico", relation: "related" },
    { id: "e-btc-doc", source: btc, target: "doc:market-report", relation: "evidenced_by" },
    { id: "e-btc-mem", source: btc, target: "memory:cluster-markt", relation: "remembered_as" },
    { id: "e-btc-ev", source: btc, target: "evidence:btc-1", relation: "supported_by" },
    { id: "e-btc-focal", source: focal, target: btc, relation: "tracks" },
  );
  // Dense secondary connections for visual DNA density
  for (let n = 0; n < nodes.length - 1; n += 3) {
    const a = nodes[n];
    const b = nodes[(n + 7) % nodes.length];
    if (!a || !b || a.id === b.id) continue;
    edges.push({
      id: `e-sec-${n}`,
      source: a.id,
      target: b.id,
      relation: "related",
    });
  }
  return edges;
}

const ALL_NODES = buildDenseNodes();
const ALL_EDGES = buildEdges(ALL_NODES);

const BY_TYPE: Record<string, number> = {
  concept: 4128,
  "research.project": 3246,
  agent: 1842,
  "knowledge.document": 2156,
  memory: 892,
  evidence: 578,
};

export const BRAIN_V2_VISUAL_FIXTURE = {
  frozenIso: BRAIN_V2_VISUAL_FROZEN_ISO,
  health: {
    ok: true,
    version: "brain-visual-fixture",
    database: "ok",
    reasoning_enabled: true,
    llm: { available: true, model: "fixture-model", base_url: "http://127.0.0.1:1234" },
    agents: { enabled: true },
    approvals: { pending: 0 },
    jobs: { queued: 18 },
    capabilities: { registered: 12 },
    neuro: {
      enabled: true,
      associative_memory: true,
      memory_tiers: true,
    },
    product_truth: {
      overall: "healthy",
      components: [
        { id: "brain", name: "Brain Service", type: "service", status: "running", measured: true },
        { id: "vector", name: "Vector DB", type: "service", status: "ready", measured: true },
        { id: "graph", name: "Graph Engine", type: "service", status: "ready", measured: true },
        { id: "embedding", name: "Embedding Service", type: "service", status: "ready", measured: true },
        { id: "inference", name: "Inference Engine", type: "service", status: "ready", measured: true },
      ],
    },
  },
  graph: {
    nodes: ALL_NODES,
    edges: ALL_EDGES,
    stats: {
      // Screen 1 KPI fixture values — TEST ONLY
      node_count: 12842,
      edge_count: 48721,
      cluster_count: 128,
      evidence_count: 5274,
      by_type: BY_TYPE,
      by_relation: { related: 40000, evidenced_by: 5000, remembered_as: 3721 },
    },
    truth: {
      visual_fixture: true,
      bounded_projection: true,
      stats_are_fixture_totals: true,
    },
  },
  evidence: {
    evidence: Array.from({ length: 80 }, (_, i) => ({
      evidence_id: `ev-fix-${i}`,
      kind: i % 3 === 0 ? "observation" : i % 3 === 1 ? "artifact" : "claim",
      status: "VERIFIED",
      claim: i === 0 ? "Bitcoin netwerkhashrate bevestigd" : `Evidence claim ${i}`,
      created_at: `2025-05-25T${String(10 + (i % 8)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}:00`,
    })),
  },
  /** KPI “Bewijs Items 5,274” — list is bounded; count comes from fixture stats via graph or dedicated override in helper. */
  evidenceCountOverride: 5274,
  memory: {
    memory: Array.from({ length: 42 }, (_, i) => ({
      memory_id: `mem-fix-${i}`,
      kind: "fact",
      status: "ACTIVE",
      content: i === 0 ? "Bitcoin correlatie met risico-regime" : `Memory ${i}`,
      created_at: "2025-05-20T10:00:00",
      updated_at: `2025-05-25T14:${String(10 + (i % 40)).padStart(2, "0")}:00`,
      source: "fixture",
      trust: "high",
      tags: i < 5 ? ["concept:bitcoin"] : [],
      scope: "project",
    })),
  },
  workersDashboard: {
    generated_at: BRAIN_V2_VISUAL_FROZEN_ISO,
    summary: {
      pools_total: 4,
      pools_enabled: 4,
      desired_workers: 8,
      running_workers: 6,
      busy_workers: 6,
      idle_workers: 2,
      failed_workers: 0,
      queue_depth: 18,
      degraded_pools: 0,
      fabric_status: "healthy",
    },
    supervisor: {},
    pools: [
      {
        pool_id: "brain_compute",
        entrypoint: "brain",
        default_count: 6,
        job_kinds: ["brain.compute.snapshot", "brain.analyze"],
        resource_classes: ["cpu"],
        description: "Brain compute",
        max_count: 8,
        desired: 6,
        instances: 6,
        running: 6,
        ready: 0,
        busy: 6,
        draining: 0,
        degraded: 0,
        queued: 18,
        status: "healthy",
      },
    ],
    workers: [
      {
        worker_id: "brain-w1",
        pool_id: "brain_compute",
        slot: 0,
        pid: 1001,
        state: "busy",
        current_job_id: "job-1",
        restart_count: 0,
        current_capability: "brain.analyze",
        progress_percent: 72,
        elapsed_display: "00:12:04",
        current_job: {
          job_id: "job-1",
          capability_id: "brain.analyze",
          human_title: "Markt trend analyse Q2 2025",
          progress_percent: 72,
          elapsed_display: "00:12:04",
          domain: "brain",
        },
      },
      {
        worker_id: "brain-w2",
        pool_id: "brain_compute",
        slot: 1,
        pid: 1002,
        state: "busy",
        current_job_id: "job-2",
        restart_count: 0,
        current_capability: "brain.enrich",
        progress_percent: 41,
        elapsed_display: "00:04:18",
        current_job: {
          job_id: "job-2",
          capability_id: "brain.enrich",
          human_title: "Relaties vinden",
          progress_percent: 41,
          elapsed_display: "00:04:18",
          domain: "brain",
        },
      },
    ],
    queues: [{ pool_id: "brain_compute", queued: 18 }],
    queued_jobs: [
      {
        job_id: "job-3",
        capability_id: "brain.analyze",
        human_title: "Hypothese evaluatie",
        domain: "brain",
        worker_pool: "brain_compute",
        progress_percent: null,
      },
      {
        job_id: "job-4",
        capability_id: "brain.compute.snapshot",
        human_title: "Concept samenvatten",
        domain: "brain",
        worker_pool: "brain_compute",
        progress_percent: null,
      },
      {
        job_id: "job-5",
        capability_id: "cognition.reason",
        human_title: "Kennis gaps identificeren",
        domain: "cognition",
        worker_pool: "brain_compute",
        progress_percent: null,
      },
    ],
    failures: [],
    truth: { visual_fixture: true },
  },
  cognitionHealth: {
    cognition: { ok: true, status: "ok" },
  },
  /** Cluster count KPI fixture (128) — derived display uses type clusters; KPI override via stats helper. */
  clusterCountOverride: 128,
  reasoningJobsOverride: 24,
} as const;
