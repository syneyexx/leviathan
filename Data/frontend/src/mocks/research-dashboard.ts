/** Research dashboard — decorative mock rows when no live project data yet. */

export const RD_HERO = {
  title: "RESEARCH",
  tagline: "Deeper answers. Broader context. Higher conviction.",
  description:
    "Search, analyze, and synthesize information from across the web, your files, and trusted sources — powered by advanced AI research agents.",
  quote: "ALL KNOWLEDGE CONVERGES IN DEEPER WATERS. — LEVIATHAN",
} as const;

export const RD_INPUT_TABS = ["Query", "Files", "URLs", "Datasets", "Code", "Images"] as const;
export type RdInputTab = (typeof RD_INPUT_TABS)[number];

export const RD_MODELS = [
  "Claude 3.5 Sonnet",
  "Claude 3 Opus",
  "GPT-4o",
  "Leviathan Local",
] as const;

export const RD_CONTEXT_CHIPS = [
  { id: "web", label: "Web", icon: "globe" },
  { id: "files", label: "Files", icon: "file" },
  { id: "datasets", label: "Datasets", icon: "database" },
  { id: "code", label: "Code", icon: "code" },
  { id: "images", label: "Images", icon: "image" },
] as const;

export const RD_TEMPLATES = [
  { id: "deep", label: "Deep Research Report", depth: "deep", prompt: "Produce a deep research report with citations and coverage gaps." },
  { id: "competitive", label: "Competitive Analysis", depth: "standard", prompt: "Compare competitors, positioning, and evidence-backed differentiators." },
  { id: "market", label: "Market Research", depth: "standard", prompt: "Map market size, segments, trends, and primary sources." },
  { id: "technical", label: "Technical Exploration", depth: "deep", prompt: "Explore the technical landscape, trade-offs, and implementation risks." },
  { id: "academic", label: "Academic Review", depth: "expert", prompt: "Synthesize peer-reviewed literature with citation integrity." },
  { id: "custom", label: "Custom Prompt", depth: "standard", prompt: "" },
] as const;

export type RdTimelineStepStatus = "done" | "active" | "pending" | "queued";

export type RdTimelineStep = {
  id: string;
  label: string;
  status: RdTimelineStepStatus;
  meta?: string;
  duration?: string;
};

export const RD_DEMO_TIMELINE: RdTimelineStep[] = [
  { id: "understand", label: "Understanding your query", status: "done", duration: "2s" },
  { id: "search", label: "Searching the web", status: "active", meta: "12 sources", duration: "18s" },
  { id: "analyze", label: "Analyzing sources", status: "pending", meta: "In progress...", duration: "1m" },
  { id: "insights", label: "Extracting insights", status: "queued", meta: "Queued" },
  { id: "report", label: "Building structured report", status: "queued", meta: "Queued" },
];

export type RdEvidenceItem = {
  id: string;
  title: string;
  domain: string;
  ago: string;
  /** Null = unmeasured / no evidence-backed score (Round 9). */
  confidence: number | null;
  favicon: string;
  url?: string;
  /** Decorative mock rows are fixtures — never operational confidence. */
  fixture?: boolean;
};

export const RD_DEMO_EVIDENCE: RdEvidenceItem[] = [
  {
    id: "e1",
    title: "The Future of AI in Scientific Discovery",
    domain: "nature.com",
    ago: "2 hours ago",
    confidence: null,
    favicon: "N",
    url: "https://nature.com",
    fixture: true,
  },
  {
    id: "e2",
    title: "Scaling Laws and Multimodal Reasoning",
    domain: "arxiv.org",
    ago: "5 hours ago",
    confidence: null,
    favicon: "χ",
    url: "https://arxiv.org",
    fixture: true,
  },
  {
    id: "e3",
    title: "OpenAI Research: Agents and Tool Use",
    domain: "openai.com",
    ago: "1 day ago",
    confidence: null,
    favicon: "O",
    url: "https://openai.com",
    fixture: true,
  },
  {
    id: "e4",
    title: "Evidence Graphs for Verifiable Synthesis",
    domain: "mit.edu",
    ago: "2 days ago",
    confidence: null,
    favicon: "M",
    url: "https://mit.edu",
    fixture: true,
  },
  {
    id: "e5",
    title: "Retrieval-Augmented Generation Benchmarks",
    domain: "aclweb.org",
    ago: "3 days ago",
    confidence: null,
    favicon: "A",
    url: "https://aclweb.org",
    fixture: true,
  },
];

export type RdWebResult = {
  id: string;
  rank: number;
  title: string;
  domain: string;
  snippet: string;
  thumb?: string;
};

export const RD_DEMO_WEB: RdWebResult[] = [
  {
    id: "w1",
    rank: 1,
    title: "How AI agents transform research workflows",
    domain: "technologyreview.com",
    snippet:
      "Autonomous research agents can plan queries, gather sources, and draft structured briefs — with human oversight on citations.",
  },
  {
    id: "w2",
    rank: 2,
    title: "Building trustworthy evidence pipelines",
    domain: "deepmind.google",
    snippet:
      "Traceable provenance and conflict detection are becoming table stakes for enterprise research systems.",
  },
  {
    id: "w3",
    rank: 3,
    title: "Citation integrity in generative research",
    domain: "stanford.edu",
    snippet:
      "Systems that refuse invented citations outperform unconstrained summarizers on factual grounding metrics.",
  },
];

export type RdInsight = {
  id: string;
  title: string;
  body: string;
  confidence: number | null;
  icon: "bot" | "brain" | "bulb";
  fixture?: boolean;
};

export const RD_DEMO_INSIGHTS: RdInsight[] = [
  {
    id: "i1",
    title: "Agentic retrieval improves coverage",
    body: "Multi-hop search with scoped budgets surfaces more diverse primary sources than single-shot queries.",
    confidence: null,
    icon: "bot",
    fixture: true,
  },
  {
    id: "i2",
    title: "Evidence graphs reduce hallucination",
    body: "Linking claims to span-level evidence cuts unsupported assertions in synthesized reports.",
    confidence: null,
    icon: "brain",
    fixture: true,
  },
  {
    id: "i3",
    title: "Human review still gates conviction",
    body: "Highest-confidence outputs still benefit from analyst review before downstream decisions.",
    confidence: null,
    icon: "bulb",
    fixture: true,
  },
];

export const RD_IDLE_TIMELINE: RdTimelineStep[] = [
  { id: "understand", label: "Understanding your query", status: "queued", meta: "Waiting" },
  { id: "search", label: "Searching the web", status: "queued", meta: "Waiting" },
  { id: "analyze", label: "Analyzing sources", status: "queued", meta: "Waiting" },
  { id: "insights", label: "Extracting insights", status: "queued", meta: "Waiting" },
  { id: "report", label: "Building structured report", status: "queued", meta: "Waiting" },
];
