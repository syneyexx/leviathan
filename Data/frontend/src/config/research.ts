/** Production Research UI configuration (labels/layout — not live fixture data). */

export const RD_HERO = {
  title: "RESEARCH",
  tagline: "Deeper answers. Broader context. Higher conviction.",
  description:
    "Search, analyze, and synthesize information from across the web, your files, and trusted sources — powered by advanced AI research agents.",
  quote: "ALL KNOWLEDGE CONVERGES IN DEEPER WATERS. — LEVIATHAN",
} as const;

export const RD_INPUT_TABS = ["Query", "Files", "URLs", "Datasets", "Code", "Images"] as const;
export type RdInputTab = (typeof RD_INPUT_TABS)[number];

export const RD_CONTEXT_CHIPS = [
  { id: "web", label: "Web", icon: "globe" },
  { id: "files", label: "Files", icon: "file" },
  { id: "datasets", label: "Datasets", icon: "database" },
  { id: "code", label: "Code", icon: "code", unavailable: "Code analysis is not wired into Research yet" },
  { id: "images", label: "Images", icon: "image", unavailable: "Image research is not available yet" },
] as const;

export const RD_TEMPLATES = [
  {
    id: "deep",
    label: "Deep Research Report",
    depth: "deep",
    executionMode: "normal" as const,
    allowWeb: true,
    prompt: "Produce a deep research report with citations and coverage gaps.",
  },
  {
    id: "competitive",
    label: "Competitive Analysis",
    depth: "standard",
    executionMode: "normal" as const,
    allowWeb: true,
    prompt: "Compare competitors, positioning, and evidence-backed differentiators.",
  },
  {
    id: "market",
    label: "Market Research",
    depth: "standard",
    executionMode: "normal" as const,
    allowWeb: true,
    prompt: "Map market size, segments, trends, and primary sources.",
  },
  {
    id: "technical",
    label: "Technical Exploration",
    depth: "deep",
    executionMode: "custom" as const,
    workers: 3,
    rounds: 8,
    allowWeb: true,
    prompt: "Explore the technical landscape, trade-offs, and implementation risks.",
  },
  {
    id: "academic",
    label: "Academic Review",
    depth: "expert",
    executionMode: "normal" as const,
    allowWeb: true,
    prompt: "Synthesize peer-reviewed literature with citation integrity.",
  },
  {
    id: "custom",
    label: "Custom Prompt",
    depth: "standard",
    executionMode: "custom" as const,
    workers: 2,
    rounds: 10,
    allowWeb: true,
    prompt: "",
  },
] as const;

export type RdTimelineStepStatus = "done" | "active" | "pending" | "queued" | "failed";

export type RdTimelineStep = {
  id: string;
  label: string;
  status: RdTimelineStepStatus;
  meta?: string;
  duration?: string;
};

export const RD_IDLE_TIMELINE: RdTimelineStep[] = [
  { id: "planning", label: "Understanding & planning", status: "queued", meta: "Waiting" },
  { id: "ingestion", label: "Source ingestion", status: "queued", meta: "Waiting" },
  { id: "retrieval", label: "Retrieval", status: "queued", meta: "Waiting" },
  { id: "evidence", label: "Evidence extraction", status: "queued", meta: "Waiting" },
  { id: "claims", label: "Claim analysis", status: "queued", meta: "Waiting" },
  { id: "conflicts", label: "Contradiction verification", status: "queued", meta: "Waiting" },
  { id: "synthesis", label: "Synthesis", status: "queued", meta: "Waiting" },
  { id: "report", label: "Report generation", status: "queued", meta: "Waiting" },
  { id: "brain", label: "Brain synchronization", status: "queued", meta: "Waiting" },
  { id: "complete", label: "Complete", status: "queued", meta: "Waiting" },
];

export type RdEvidenceItem = {
  id: string;
  title: string;
  domain: string;
  ago: string;
  confidence: number | null;
  supportLabel?: string;
  favicon: string;
  url?: string;
};

export type RdWebResult = {
  id: string;
  rank: number;
  title: string;
  domain: string;
  snippet: string;
  thumb?: string;
};

export type RdInsight = {
  id: string;
  title: string;
  body: string;
  confidence: number | null;
  supportLabel?: string;
  icon: "bot" | "brain" | "bulb";
};
