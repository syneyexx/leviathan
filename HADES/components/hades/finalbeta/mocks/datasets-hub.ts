/** FINALBETA Research Datasets hub — mock data (UI-only). */

export type DatasetsHubTypeTone = "cyan" | "purple" | "orange";
export type DatasetsHubStatus = "processed" | "indexed" | "processing" | "generated";

export type DatasetsHubRow = {
  id: string;
  name: string;
  meta: string;
  type: string;
  typeTone: DatasetsHubTypeTone;
  size: string;
  samples: string;
  status: DatasetsHubStatus;
  statusLabel: string;
  updated: string;
  icon: string;
};

export const DSH_PAGE_COPY = {
  title: "DATASETS",
  subtitle: "FUEL INTELLIGENCE.",
  quote: "Better data. A more intelligent tomorrow.",
  pillars: ["COLLECT", "PROCESS", "CURATE", "INTEGRATE", "EMPOWER"],
  footerQuote: "Data is the foundation of real intelligence.",
  footerAttribution: "LEVIATHAN",
} as const;

export const DSH_ACTIONS = [
  {
    id: "browse",
    title: "Browse Hub",
    subtitle: "Explore public datasets",
    icon: "globe",
    toast: "Browse Hub",
  },
  {
    id: "upload",
    title: "Upload Dataset",
    subtitle: "Add your own data",
    icon: "upload",
    toast: "Upload Dataset",
  },
  {
    id: "import",
    title: "Import from Source",
    subtitle: "HuggingFace, GitHub, URLs...",
    icon: "database",
    toast: "Import from Source",
  },
  {
    id: "process",
    title: "Process & Clean",
    subtitle: "Prepare for training",
    icon: "settings",
    toast: "Process & Clean",
  },
  {
    id: "create",
    title: "Create Dataset",
    subtitle: "Build synthetic data",
    icon: "plus",
    toast: "Create Dataset",
  },
] as const;

export const DSH_TABS = [
  "My Datasets",
  "HuggingFace",
  "Local Files",
  "GitHub",
  "Web Sources",
  "Synthetic",
  "Favorites",
] as const;

export type DatasetsHubTab = (typeof DSH_TABS)[number];

export const DSH_TYPE_FILTERS = ["All Types", "Text", "Image", "Time Series", "Multimodal"] as const;
export const DSH_SIZE_FILTERS = ["All Sizes", "< 10 GB", "10–50 GB", "> 50 GB"] as const;
export const DSH_STATUS_FILTERS = ["All Status", "Processed", "Indexed", "Processing", "Generated"] as const;
export const DSH_SORT_OPTIONS = ["Sort: Updated", "Sort: Name", "Sort: Size", "Sort: Samples"] as const;

export const DSH_TABLE_ROWS: DatasetsHubRow[] = [
  {
    id: "hades_code_instruction",
    name: "HADES-Code-Instruction",
    meta: "High quality coding instruction data",
    type: "Text",
    typeTone: "cyan",
    size: "12.4 GB",
    samples: "1.2M",
    status: "processed",
    statusLabel: "Processed",
    updated: "Sep 17, 2026",
    icon: "code",
  },
  {
    id: "trading_market_data",
    name: "Trading_Market_Data_2000_2024",
    meta: "Historical market data (OHLCV)",
    type: "Time Series",
    typeTone: "purple",
    size: "38.7 GB",
    samples: "24.3M",
    status: "indexed",
    statusLabel: "Indexed",
    updated: "Sep 16, 2026",
    icon: "chart",
  },
  {
    id: "technical_documentation",
    name: "Technical_Documentation",
    meta: "Software and system documentation",
    type: "Text",
    typeTone: "cyan",
    size: "4.1 GB",
    samples: "320K",
    status: "processed",
    statusLabel: "Processed",
    updated: "Sep 15, 2026",
    icon: "book",
  },
  {
    id: "multimodal_images",
    name: "Multimodal_Images",
    meta: "Images, diagrams, screenshots",
    type: "Image",
    typeTone: "orange",
    size: "27.9 GB",
    samples: "1.8M",
    status: "processing",
    statusLabel: "Processing",
    updated: "Sep 15, 2026",
    icon: "image",
  },
  {
    id: "research_papers_ai",
    name: "Research_Papers_AI",
    meta: "arXiv papers on AI/ML",
    type: "Text",
    typeTone: "cyan",
    size: "6.8 GB",
    samples: "450K",
    status: "processed",
    statusLabel: "Processed",
    updated: "Sep 14, 2026",
    icon: "file",
  },
  {
    id: "web_crawl_knowledge",
    name: "Web_Crawl_Knowledge",
    meta: "General web knowledge corpus",
    type: "Text",
    typeTone: "cyan",
    size: "92.1 GB",
    samples: "12.4M",
    status: "indexed",
    statusLabel: "Indexed",
    updated: "Sep 13, 2026",
    icon: "globe",
  },
  {
    id: "synthetic_reasoning",
    name: "Synthetic_Reasoning",
    meta: "AI generated reasoning data",
    type: "Text",
    typeTone: "cyan",
    size: "3.6 GB",
    samples: "210K",
    status: "generated",
    statusLabel: "Generated",
    updated: "Sep 12, 2026",
    icon: "brain",
  },
  {
    id: "vision_datasets",
    name: "Vision_Datasets",
    meta: "Objects, OCR, charts, UI elements",
    type: "Image",
    typeTone: "orange",
    size: "18.3 GB",
    samples: "980K",
    status: "processed",
    statusLabel: "Processed",
    updated: "Sep 10, 2026",
    icon: "image",
  },
];

export const DSH_FOOTER_STATS = [
  { id: "total", value: "24", label: "Total Datasets" },
  { id: "samples", value: "128M", label: "Total Samples" },
  { id: "storage", value: "342 GB", label: "Storage Used" },
  { id: "index", value: "98%", label: "Index Coverage" },
] as const;

export const DSH_STORAGE = {
  usedGb: 342,
  totalTb: 2,
  usedPct: 17,
  segments: [
    { label: "Text", pct: 48, color: "#3ac7ee" },
    { label: "Images", pct: 22, color: "#eab94f" },
    { label: "Archives", pct: 12, color: "#9b5cff" },
    { label: "Time Series", pct: 10, color: "#6b8cff" },
    { label: "Other", pct: 8, color: "#758392" },
  ],
} as const;

export const DSH_PIPELINE = [
  {
    id: "ingestion",
    title: "Ingestion Queue",
    detail: "2 tasks running",
    icon: "download",
    tone: "cyan",
  },
  {
    id: "cleaning",
    title: "Data Cleaning",
    detail: "Remove duplicates, filter, normalize",
    icon: "shield",
    tone: "purple",
  },
  {
    id: "format",
    title: "Format Conversion",
    detail: "Convert to training format",
    icon: "refresh",
    tone: "blue",
  },
  {
    id: "chunking",
    title: "Chunking",
    detail: "Split and optimize",
    icon: "list",
    tone: "gold",
  },
  {
    id: "embedding",
    title: "Embedding Generation",
    detail: "Create vector embeddings",
    icon: "brain",
    tone: "pink",
  },
  {
    id: "quality",
    title: "Quality Analysis",
    detail: "Check quality and bias",
    icon: "checkcircle",
    tone: "gold",
  },
] as const;

export const DSH_QUICK_ACTIONS = [
  { id: "upload", label: "Upload Files", icon: "upload" },
  { id: "url", label: "From URL", icon: "link" },
  { id: "hf", label: "HuggingFace", icon: "download" },
  { id: "github", label: "GitHub", icon: "code" },
  { id: "synthetic", label: "Create Synthetic", icon: "squareplus" },
  { id: "process-all", label: "Process All", icon: "refresh" },
  { id: "logs", label: "View Logs", icon: "terminal" },
  { id: "settings", label: "Settings", icon: "settings" },
] as const;

export const DSH_RECENT_ACTIVITY = [
  { id: "a1", icon: "checkcircle", tone: "green", text: "Dataset processed: HADES-Code-Instruction", when: "5m ago" },
  { id: "a2", icon: "download", tone: "cyan", text: "Downloaded: Qwen/Code-Instruction", when: "12m ago" },
  { id: "a3", icon: "refresh", tone: "gold", text: "Processing: Multimodal_Images", when: "28m ago" },
  { id: "a4", icon: "shield", tone: "purple", text: "Completed: Data cleaning (Trading_Dataset)", when: "1h ago" },
  { id: "a5", icon: "upload", tone: "cyan", text: "Uploaded: research_papers_2024.zip", when: "2h ago" },
] as const;
