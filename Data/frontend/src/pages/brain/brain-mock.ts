/** Mock data for Brain Tree / Timeline / Clusters / Analytics views. */

export const BRAIN_VIEWS = ["Graph", "Tree", "Timeline", "Clusters", "Analytics"] as const;
export type BrainView = (typeof BRAIN_VIEWS)[number];

export const BRAIN_STATS = [
  { label: "Nodes", value: "124,532", icon: "nodes" },
  { label: "Connections", value: "342,681", icon: "links" },
  { label: "Knowledge Domains", value: "18", icon: "domains" },
  { label: "Last Updated", value: "2 minutes ago", icon: "clock" },
] as const;

/* ── Tree ─────────────────────────────────────────────────── */

export type TreeNode = {
  id: string;
  label: string;
  count: number;
  color: string;
  children?: TreeNode[];
  description?: string;
  tags?: string[];
};

export const TREE_ROOT: TreeNode = {
  id: "leviathan",
  label: "LEVIATHAN",
  count: 1842,
  color: "#D4AF37",
  description: "Root of the Leviathan knowledge hierarchy.",
  children: [
    {
      id: "core",
      label: "Core Concepts",
      count: 248,
      color: "#E8B84A",
      description:
        "Fundamental concepts and first principles that define intelligence, cognition, and knowledge representation across LEVIATHAN.",
      tags: ["foundation", "theory", "cognition", "intelligence", "philosophy"],
      children: [
        { id: "intelligence", label: "Intelligence", count: 42, color: "#E8B84A" },
        { id: "consciousness", label: "Consciousness", count: 18, color: "#E8B84A" },
        { id: "learning", label: "Learning", count: 36, color: "#E8B84A" },
        { id: "reasoning", label: "Reasoning", count: 24, color: "#E8B84A" },
        { id: "memory", label: "Memory", count: 18, color: "#E8B84A" },
      ],
    },
    {
      id: "models",
      label: "AI Models",
      count: 312,
      color: "#A78BFA",
      description: "Model families, fine-tunes, and inference stacks.",
      tags: ["models", "llm", "training"],
      children: [
        { id: "llms", label: "LLMs", count: 86, color: "#A78BFA" },
        { id: "agents", label: "Agents", count: 54, color: "#A78BFA" },
        { id: "finetune", label: "Fine-tuning", count: 48, color: "#A78BFA" },
        { id: "embeddings", label: "Embeddings", count: 62, color: "#A78BFA" },
        { id: "eval", label: "Evaluation", count: 32, color: "#A78BFA" },
      ],
    },
    {
      id: "data",
      label: "Data & Information",
      count: 184,
      color: "#22C9D6",
      description: "Datasets, documents, and structured sources.",
      tags: ["data", "ingestion"],
      children: [
        { id: "datasets", label: "Datasets", count: 64, color: "#22C9D6" },
        { id: "documents", label: "Documents", count: 52, color: "#22C9D6" },
        { id: "streams", label: "Streams", count: 28, color: "#22C9D6" },
        { id: "indexes", label: "Indexes", count: 40, color: "#22C9D6" },
      ],
    },
    {
      id: "tools",
      label: "Tools & Systems",
      count: 96,
      color: "#DB8A34",
      description: "Runtime tools, bridges, and system capabilities.",
      tags: ["tools", "mcp", "runtime"],
      children: [
        { id: "mcp", label: "MCP", count: 22, color: "#DB8A34" },
        { id: "browser", label: "Browser", count: 18, color: "#DB8A34" },
        { id: "fs", label: "File System", count: 26, color: "#DB8A34" },
        { id: "search", label: "Web Search", count: 30, color: "#DB8A34" },
      ],
    },
    {
      id: "research",
      label: "Research",
      count: 259,
      color: "#20DC8C",
      description: "Research threads, evidence, and discoveries.",
      tags: ["research", "evidence"],
      children: [
        { id: "papers", label: "Papers", count: 74, color: "#20DC8C" },
        { id: "experiments", label: "Experiments", count: 48, color: "#20DC8C" },
        { id: "hypotheses", label: "Hypotheses", count: 36, color: "#20DC8C" },
        { id: "evidence", label: "Evidence", count: 58, color: "#20DC8C" },
        { id: "reviews", label: "Reviews", count: 43, color: "#20DC8C" },
      ],
    },
  ],
};

export const TREE_FOOTER = {
  total: "1,842",
  branches: "127",
  leaves: "986",
  depth: "5",
} as const;

/* ── Timeline ─────────────────────────────────────────────── */

export type TimelineType =
  | "all"
  | "conversation"
  | "ingestion"
  | "research"
  | "node"
  | "training"
  | "system";

export const TIMELINE_KPI = [
  { label: "Total Events", value: "1,842", delta: "+12% this month", color: "#4285E8", spark: [12, 16, 14, 20, 24, 22, 30, 34] },
  { label: "Knowledge Ingested", value: "284.7 GB", delta: "+18% this month", color: "#20DC8C", spark: [8, 12, 10, 16, 18, 22, 26, 30] },
  { label: "Nodes Created", value: "2,431", delta: "+32% this month", color: "#A78BFA", spark: [10, 14, 18, 22, 28, 32, 36, 42] },
  { label: "Conversations", value: "892", delta: "+8% this month", color: "#F0C875", spark: [18, 16, 20, 18, 22, 20, 24, 26] },
  { label: "Research Discoveries", value: "147", delta: "+41% this month", color: "#22C9D6", spark: [4, 6, 8, 10, 14, 18, 22, 28] },
] as const;

export const TIMELINE_FILTERS: { id: TimelineType; label: string; count: number; color: string }[] = [
  { id: "all", label: "All Events", count: 1842, color: "#4285E8" },
  { id: "conversation", label: "Conversations", count: 892, color: "#22C9D6" },
  { id: "ingestion", label: "Ingestion", count: 284, color: "#20DC8C" },
  { id: "research", label: "Research", count: 147, color: "#F0C875" },
  { id: "node", label: "Node Creation", count: 431, color: "#A78BFA" },
  { id: "training", label: "Model Training", count: 36, color: "#E45959" },
  { id: "system", label: "System", count: 52, color: "#8A8A84" },
];

export type TimelineEvent = {
  id: string;
  type: Exclude<TimelineType, "all">;
  time: string;
  title: string;
  body: string;
  tags: string[];
  meta: string;
  relevance?: string;
};

export const TIMELINE_EVENTS: TimelineEvent[] = [
  {
    id: "e1",
    type: "conversation",
    time: "SEP 17, 2026 14:22",
    title: "Conversation Memory Checkpoint",
    body: "Persisted multi-turn agent dialogue into long-term memory with 12 linked concept nodes.",
    tags: ["Chat", "Memory", "Agents"],
    meta: "12 nodes linked",
    relevance: "High relevance",
  },
  {
    id: "e2",
    type: "ingestion",
    time: "SEP 17, 2026 11:03",
    title: "Knowledge Ingestion",
    body: "Ingested research paper on agent coordination scaling laws from arXiv into the brain graph.",
    tags: ["Ingestion", "Research", "Agents"],
    meta: "86 nodes created",
    relevance: "High relevance",
  },
  {
    id: "e3",
    type: "research",
    time: "SEP 16, 2026 19:41",
    title: "Research Discovery",
    body: "Emergent cluster detected around RAG optimization patterns across 14 source documents.",
    tags: ["Research", "RAG"],
    meta: "3 clusters touched",
  },
  {
    id: "e4",
    type: "node",
    time: "SEP 16, 2026 16:18",
    title: "Node Creation Burst",
    body: "Batch creation of concept nodes from dataset materialization pipeline.",
    tags: ["Nodes", "Datasets"],
    meta: "214 nodes created",
  },
  {
    id: "e5",
    type: "training",
    time: "SEP 15, 2026 22:05",
    title: "Model Training Checkpoint",
    body: "LoRA adapter checkpoint registered and linked to parent foundation model node.",
    tags: ["Training", "Models"],
    meta: "1 model linked",
  },
  {
    id: "e6",
    type: "system",
    time: "SEP 15, 2026 09:12",
    title: "Graph Compaction",
    body: "Nightly compaction merged duplicate edges and refreshed cluster centroids.",
    tags: ["System"],
    meta: "1,842 edges touched",
  },
];

export const TIMELINE_TREND = {
  labels: ["Aug 18", "Aug 25", "Sep 1", "Sep 8", "Sep 15"],
  series: [
    { name: "Conversations", color: "#22C9D6", values: [42, 58, 64, 78, 92] },
    { name: "Ingestion", color: "#20DC8C", values: [18, 24, 30, 28, 36] },
    { name: "Nodes", color: "#A78BFA", values: [30, 44, 52, 70, 88] },
    { name: "Research", color: "#F0C875", values: [8, 12, 16, 22, 28] },
  ],
} as const;

export const TIMELINE_DETAIL = {
  type: "Ingestion",
  source: "arXiv.org",
  title: "Scaling Laws for Agent Coordination",
  size: "12.4 MB",
  documents: "1",
  nodes: "86",
  clusters: "2",
  domain: "Agents, Research",
  status: "Completed",
  by: "Research Agent",
  description:
    "Ingested a research paper analyzing coordination scaling across multi-agent systems. Extracted 86 concept and evidence nodes into the Agents and Research clusters.",
  related: [
    { title: "Research Discovery", when: "2 hours before" },
    { title: "Conversation Reference", when: "5 hours after" },
  ],
} as const;

/* ── Clusters ─────────────────────────────────────────────── */

export type ClusterItem = {
  id: string;
  label: string;
  nodes: number;
  color: string;
  x: number;
  y: number;
  r: number;
  description: string;
  connections: number;
  subclusters: number;
  concepts: { label: string; count: number }[];
  related: { label: string; strength: number; color: string }[];
};

export const CLUSTERS: ClusterItem[] = [
  {
    id: "core",
    label: "Core Intelligence",
    nodes: 24318,
    color: "#4285E8",
    x: 50,
    y: 48,
    r: 52,
    description:
      "Central cluster containing foundational AI concepts, reasoning, cognition, and meta-knowledge that connects across all domains.",
    connections: 68421,
    subclusters: 19,
    concepts: [
      { label: "Artificial Intelligence", count: 4231 },
      { label: "Machine Learning", count: 3942 },
      { label: "Reasoning", count: 3681 },
      { label: "Knowledge Representation", count: 2913 },
      { label: "Cognitive Architecture", count: 2441 },
    ],
    related: [
      { label: "Technology & Engineering", strength: 0.87, color: "#A78BFA" },
      { label: "Science & Research", strength: 0.83, color: "#20DC8C" },
      { label: "Operations & Systems", strength: 0.71, color: "#DB8A34" },
      { label: "Human Knowledge", strength: 0.68, color: "#D4AF37" },
      { label: "Business & Strategy", strength: 0.62, color: "#22C9D6" },
    ],
  },
  {
    id: "science",
    label: "Science & Research",
    nodes: 18742,
    color: "#20DC8C",
    x: 22,
    y: 22,
    r: 40,
    description: "Scientific methods, experiments, and research evidence.",
    connections: 42100,
    subclusters: 14,
    concepts: [
      { label: "Experiments", count: 2104 },
      { label: "Papers", count: 1890 },
      { label: "Hypotheses", count: 1204 },
    ],
    related: [
      { label: "Core Intelligence", strength: 0.83, color: "#4285E8" },
      { label: "Technology & Engineering", strength: 0.74, color: "#A78BFA" },
    ],
  },
  {
    id: "tech",
    label: "Technology & Engineering",
    nodes: 16893,
    color: "#A78BFA",
    x: 72,
    y: 20,
    r: 38,
    description: "Engineering systems, platforms, and technical stacks.",
    connections: 38920,
    subclusters: 12,
    concepts: [
      { label: "Systems", count: 1802 },
      { label: "APIs", count: 1402 },
      { label: "Infrastructure", count: 980 },
    ],
    related: [
      { label: "Core Intelligence", strength: 0.87, color: "#4285E8" },
      { label: "Operations & Systems", strength: 0.76, color: "#DB8A34" },
    ],
  },
  {
    id: "human",
    label: "Human Knowledge",
    nodes: 12448,
    color: "#D4AF37",
    x: 84,
    y: 48,
    r: 34,
    description: "Culture, history, and human-centric knowledge domains.",
    connections: 28110,
    subclusters: 11,
    concepts: [
      { label: "History", count: 1200 },
      { label: "Language", count: 980 },
    ],
    related: [{ label: "Core Intelligence", strength: 0.68, color: "#4285E8" }],
  },
  {
    id: "creative",
    label: "Creative & Media",
    nodes: 9721,
    color: "#E459A8",
    x: 78,
    y: 76,
    r: 30,
    description: "Media production, creative assets, and narrative systems.",
    connections: 19440,
    subclusters: 9,
    concepts: [{ label: "Media", count: 840 }],
    related: [{ label: "Business & Strategy", strength: 0.55, color: "#22C9D6" }],
  },
  {
    id: "ops",
    label: "Operations & Systems",
    nodes: 8640,
    color: "#DB8A34",
    x: 18,
    y: 70,
    r: 28,
    description: "Runtime operations, monitoring, and system control.",
    connections: 17220,
    subclusters: 8,
    concepts: [{ label: "Runtime", count: 720 }],
    related: [{ label: "Technology & Engineering", strength: 0.76, color: "#A78BFA" }],
  },
  {
    id: "business",
    label: "Business & Strategy",
    nodes: 7410,
    color: "#22C9D6",
    x: 58,
    y: 82,
    r: 26,
    description: "Markets, strategy, and operational planning.",
    connections: 15100,
    subclusters: 7,
    concepts: [{ label: "Strategy", count: 610 }],
    related: [{ label: "Core Intelligence", strength: 0.62, color: "#4285E8" }],
  },
  {
    id: "society",
    label: "Society & Humanities",
    nodes: 6120,
    color: "#E45959",
    x: 34,
    y: 88,
    r: 24,
    description: "Social systems and humanities knowledge.",
    connections: 12100,
    subclusters: 6,
    concepts: [{ label: "Society", count: 480 }],
    related: [{ label: "Human Knowledge", strength: 0.71, color: "#D4AF37" }],
  },
];

export const CLUSTER_DISTRIBUTION = [
  { label: "Core Intelligence", value: 19.5, color: "#4285E8" },
  { label: "Science & Research", value: 15.1, color: "#20DC8C" },
  { label: "Technology", value: 13.6, color: "#A78BFA" },
  { label: "Human Knowledge", value: 10.0, color: "#D4AF37" },
  { label: "Other", value: 41.8, color: "#5A5A56" },
] as const;

export const CLUSTER_HEAT = [
  [1.0, 0.83, 0.87, 0.68, 0.42, 0.71],
  [0.83, 1.0, 0.74, 0.55, 0.38, 0.48],
  [0.87, 0.74, 1.0, 0.5, 0.45, 0.76],
  [0.68, 0.55, 0.5, 1.0, 0.62, 0.4],
  [0.42, 0.38, 0.45, 0.62, 1.0, 0.35],
  [0.71, 0.48, 0.76, 0.4, 0.35, 1.0],
] as const;

export const CLUSTER_HEAT_LABELS = ["Core", "Sci", "Tech", "Hum", "Creat", "Ops"] as const;

/* ── Analytics ────────────────────────────────────────────── */

export const ANALYTICS_KPI = [
  { label: "Total Nodes", value: "124,532", delta: "+12.4%", good: true, sub: "+13,682 new nodes (30d)", spark: [80, 86, 90, 95, 100, 108, 115, 124] },
  { label: "Relationship Density", value: "2.75", delta: "+8.1%", good: true, sub: "342,681 total connections", spark: [2.1, 2.2, 2.3, 2.4, 2.5, 2.55, 2.65, 2.75] },
  { label: "Retrieval Quality", value: "94.2%", delta: "+2.6%", good: true, sub: "Top-5 relevant results", spark: [88, 89, 90, 91, 92, 93, 93.5, 94.2] },
  { label: "Memory Growth", value: "48.7 GB", delta: "+15.3%", good: true, sub: "+6.5 GB (30d)", spark: [30, 33, 36, 39, 42, 44, 46, 48.7] },
  { label: "Avg. Query Latency", value: "328 ms", delta: "-18.7%", good: true, sub: "P95: 842 ms", spark: [480, 450, 420, 390, 370, 350, 340, 328] },
  { label: "Confidence Score", value: "91.6%", delta: "+3.2%", good: true, sub: "Across all responses", spark: [84, 86, 87, 88, 89, 90, 91, 91.6] },
] as const;

export const KNOWLEDGE_GROWTH = {
  labels: ["Aug 18", "Aug 25", "Sep 1", "Sep 8", "Sep 15"],
  series: [
    { name: "Total Nodes", color: "#D4AF37", values: [98000, 104000, 110000, 116000, 124532], dashed: false },
    { name: "New Nodes", color: "#22C9D6", values: [2200, 2800, 3100, 3600, 4200], dashed: true },
  ],
} as const;

export const SOURCE_COMPOSITION = [
  { label: "Documents", value: 28.4, color: "#D4AF37" },
  { label: "Web Sources", value: 22.7, color: "#22C9D6" },
  { label: "Datasets", value: 16.7, color: "#A78BFA" },
  { label: "Conversations", value: 12.3, color: "#E459A8" },
  { label: "Code Repositories", value: 8.9, color: "#20DC8C" },
  { label: "APIs", value: 8.1, color: "#4285E8" },
  { label: "Manual Input", value: 6.4, color: "#8A8A84" },
  { label: "Other", value: 7.1, color: "#5A5A56" },
] as const;

export const NODE_TYPES = [
  { label: "Concept", count: "42.1K", pct: 92, color: "#D4AF37" },
  { label: "Memory", count: "18.3K", pct: 58, color: "#DB8A34" },
  { label: "Document", count: "12.7K", pct: 42, color: "#A78BFA" },
  { label: "Code", count: "8.9K", pct: 32, color: "#22C9D6" },
  { label: "Model", count: "11.1K", pct: 36, color: "#4285E8" },
  { label: "Event", count: "6.2K", pct: 24, color: "#9B8CFF" },
  { label: "Task", count: "4.3K", pct: 18, color: "#DB8A34" },
  { label: "Dataset", count: "3.1K", pct: 14, color: "#E459A8" },
  { label: "Tool", count: "2.4K", pct: 12, color: "#F0C875" },
  { label: "Agent", count: "1.2K", pct: 8, color: "#20DC8C" },
  { label: "Project", count: "892", pct: 6, color: "#5AC8FA" },
] as const;

export const LATENCY_TREND = {
  labels: ["Sep 10", "Sep 11", "Sep 12", "Sep 13", "Sep 14", "Sep 15", "Sep 16"],
  series: [
    { name: "Average", color: "#D4AF37", values: [410, 390, 370, 360, 350, 340, 328] },
    { name: "P95", color: "#22C9D6", values: [980, 940, 910, 880, 860, 850, 842] },
  ],
} as const;

export const CONFIDENCE_BINS = [4, 8, 14, 22, 38, 62, 88, 96, 78, 42] as const;

export const SEMANTIC_HEAT = [
  [0.2, 0.35, 0.5, 0.7, 0.85],
  [0.4, 0.55, 0.75, 0.9, 0.95],
  [0.15, 0.3, 0.45, 0.55, 0.65],
  [0.25, 0.4, 0.5, 0.6, 0.7],
  [0.35, 0.5, 0.65, 0.8, 0.88],
  [0.3, 0.45, 0.6, 0.75, 0.82],
  [0.1, 0.2, 0.28, 0.35, 0.4],
  [0.22, 0.32, 0.42, 0.5, 0.58],
  [0.18, 0.28, 0.4, 0.55, 0.62],
  [0.12, 0.18, 0.25, 0.3, 0.35],
] as const;

export const SEMANTIC_ROWS = [
  "Programming",
  "AI/ML",
  "Science",
  "Business",
  "Technology",
  "Research",
  "Humanities",
  "Operations",
  "Creative",
  "Other",
] as const;

export const EMERGING_TOPICS = [
  { rank: 1, label: "Agent Orchestration", delta: "+320%" },
  { rank: 2, label: "RAG Optimization", delta: "+214%" },
  { rank: 3, label: "Synthetic Data", delta: "+142%" },
  { rank: 4, label: "Tool Use Patterns", delta: "+138%" },
  { rank: 5, label: "Multi-Modal Reasoning", delta: "+176%" },
] as const;
