/** FINALBETA Models page — pixel mock data (UI-only). */

export type ModelLoadStatus = "geladen" | "beschikbaar" | "niet-geladen";

export type RegistryModel = {
  id: string;
  name: string;
  icon: string;
  provider: string;
  providerIcon: string;
  size: string;
  quant: string;
  status: ModelLoadStatus;
  capabilities: string[];
  lastUsed: string;
};

export type QuickAction = {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  toast: string;
};

export type DownloadQueueItem = {
  id: string;
  name: string;
  source: string;
  progress: number | null;
  eta: string | null;
  state: "downloading" | "done" | "paused";
};

export type BenchmarkMetric = {
  id: string;
  label: string;
  score: number;
};

export type SavedProfile = {
  id: string;
  name: string;
  detail: string;
  count: number;
  icon: string;
};

export type ProviderHealth = {
  id: string;
  name: string;
  kind: string;
  status: "online" | "degraded" | "offline";
  loaded: number;
  total: number;
  healthPct: number;
};

export const MODELS_HERO = {
  title: "MODELS",
  subtitle: "ONTDEKKEN. BEHEREN. OPTIMALISEREN. OVERAL.",
  quote: "De juiste modellen, op het juiste moment, voor een intelligentere wereld.",
  pillars: ["MEER MOGELIJKHEDEN", "MEER PERSPECTIEF", "MEER IMPACT"],
};

export const MODELS_KPIS = [
  {
    id: "total",
    label: "Totaal Modellen",
    value: "42",
    hint: "▲ +27% vs. vorige maand",
    hintTone: "cyan" as const,
    icon: "database",
  },
  {
    id: "loaded",
    label: "Geladen Modellen",
    value: "8",
    hint: "▲ +3 in geheugen",
    hintTone: "cyan" as const,
    icon: "grid",
  },
  {
    id: "providers",
    label: "Actieve Providers",
    value: "5",
    hint: "van 7 beschikbaar",
    hintTone: "muted" as const,
    icon: "link",
  },
  {
    id: "vram",
    label: "VRAM Gebruik",
    value: "18.6 GB",
    hint: "van 24 GB | 78%",
    hintTone: "muted" as const,
    icon: "chart",
    progress: 78,
  },
];

export const MODELS_QUICK_ACTIONS: QuickAction[] = [
  {
    id: "import",
    title: "Importeer model",
    subtitle: "Van bestand of URL",
    icon: "upload",
    toast: "Importeer model — demo",
  },
  {
    id: "scan",
    title: "Scan lokale modellen",
    subtitle: "Zoek op dit systeem",
    icon: "search",
    toast: "Lokale scan gestart",
  },
  {
    id: "hf",
    title: "Haal van Hugging Face",
    subtitle: "Bladeren & downloaden",
    icon: "globe",
    toast: "Hugging Face catalogus",
  },
  {
    id: "connect",
    title: "Verbind provider",
    subtitle: "OpenAI, Anthropic, enz.",
    icon: "bolt",
    toast: "Provider wizard",
  },
  {
    id: "bench",
    title: "Benchmark model",
    subtitle: "Prestaties testen",
    icon: "target",
    toast: "Benchmark gepland",
  },
  {
    id: "active",
    title: "Stel actief model in",
    subtitle: "Voor chat & agents",
    icon: "settings",
    toast: "Actief model kiezen",
  },
];

export const MODELS_REGISTRY_FILTERS = {
  providers: ["Alle providers", "Ollama", "LM Studio", "OpenAI", "Hugging Face", "Lokaal"],
  types: ["Alle types", "Instruct", "Chat", "Vision", "Image", "Code"],
  capabilities: ["Alle capabilities", "Chat", "Code", "Vision", "Reasoning", "Multilingual"],
  statuses: ["Alle statussen", "Geladen", "Beschikbaar", "Niet geladen"],
};

export const MODELS_REGISTRY: RegistryModel[] = [
  {
    id: "llama-31-8b",
    name: "Llama 3.1 8B Instruct",
    icon: "brain",
    provider: "Ollama",
    providerIcon: "database",
    size: "4.9 GB",
    quant: "Q4_K_M",
    status: "geladen",
    capabilities: ["Chat", "Code", "NL"],
    lastUsed: "17 sep 2024, 14:12",
  },
  {
    id: "mistral-7b",
    name: "Mistral 7B Instruct v0.3",
    icon: "brain",
    provider: "LM Studio",
    providerIcon: "terminal",
    size: "4.1 GB",
    quant: "Q4_K_M",
    status: "beschikbaar",
    capabilities: ["Chat", "Reasoning"],
    lastUsed: "16 sep 2024, 09:44",
  },
  {
    id: "gemma-2-9b",
    name: "Gemma 2 9B",
    icon: "brain",
    provider: "Ollama",
    providerIcon: "database",
    size: "5.4 GB",
    quant: "Q4_K_M",
    status: "niet-geladen",
    capabilities: ["Chat", "Multilingual"],
    lastUsed: "12 sep 2024, 18:03",
  },
  {
    id: "gpt-4o",
    name: "GPT-4o",
    icon: "globe",
    provider: "OpenAI (API)",
    providerIcon: "globe",
    size: "—",
    quant: "—",
    status: "beschikbaar",
    capabilities: ["Vision", "Multimodal"],
    lastUsed: "17 sep 2024, 11:28",
  },
  {
    id: "sdxl",
    name: "Stable Diffusion XL",
    icon: "image",
    provider: "Lokaal",
    providerIcon: "folder",
    size: "6.6 GB",
    quant: "FP16",
    status: "beschikbaar",
    capabilities: ["Image", "Generation"],
    lastUsed: "10 sep 2024, 21:15",
  },
  {
    id: "qwen2-7b",
    name: "Qwen2 7B Instruct",
    icon: "brain",
    provider: "Hugging Face",
    providerIcon: "globe",
    size: "4.4 GB",
    quant: "Q4_K_M",
    status: "niet-geladen",
    capabilities: ["Chat", "Code"],
    lastUsed: "8 sep 2024, 07:52",
  },
  {
    id: "qwen2-72b",
    name: "Qwen2 72B Instruct",
    icon: "brain",
    provider: "Hugging Face",
    providerIcon: "globe",
    size: "140 GB",
    quant: "Q4_K_S",
    status: "niet-geladen",
    capabilities: ["Chat", "Code", "Long Context"],
    lastUsed: "—",
  },
];

export const MODELS_DOWNLOAD_QUEUE: DownloadQueueItem[] = [
  {
    id: "dq-qwen",
    name: "Qwen2 7B Instruct",
    source: "Hugging Face",
    progress: 68,
    eta: "12m resterend",
    state: "downloading",
  },
  {
    id: "dq-phi",
    name: "Phi-3 Medium",
    source: "Hugging Face",
    progress: 42,
    eta: "23m resterend",
    state: "downloading",
  },
  {
    id: "dq-llama",
    name: "Llama 3.2 3B",
    source: "Ollama registry",
    progress: null,
    eta: null,
    state: "done",
  },
];

export const MODELS_BENCHMARK = {
  modelId: "llama-31-8b",
  modelLabel: "Llama 3.1 8B Instruct",
  metrics: [
    { id: "mmlu", label: "MMLU (5-shot)", score: 68.4 },
    { id: "gsm8k", label: "GSM8K (CoT)", score: 83.1 },
    { id: "humaneval", label: "HumanEval", score: 71.2 },
    { id: "truthful", label: "TruthfulQA", score: 62.8 },
    { id: "dutch", label: "Dutch MMLU", score: 76.3 },
  ] as BenchmarkMetric[],
};

export const MODELS_VRAM = {
  totalGb: 24,
  usedPct: 78,
  slices: [
    { label: "Modellen", gb: 18.6, color: "#3ac7ee" },
    { label: "Cache", gb: 2.8, color: "#eab94f" },
    { label: "KV Cache", gb: 1.9, color: "#5b9fd4" },
    { label: "Systeem", gb: 0.7, color: "#6f8494" },
  ],
};

export const MODELS_PROFILES: SavedProfile[] = [
  { id: "research", name: "Research (Lokaal)", detail: "4 modellen", count: 4, icon: "search" },
  { id: "coding", name: "Coding Assistant", detail: "3 modellen", count: 3, icon: "code" },
  { id: "vision", name: "Vision & Multimodal", detail: "4 modellen", count: 4, icon: "image" },
  { id: "light", name: "Lightweight / Fast", detail: "2 modellen", count: 2, icon: "bolt" },
  { id: "prod", name: "Production (API)", detail: "5 modellen", count: 5, icon: "shield" },
];

export const MODELS_ACTIVE_RUNTIME = {
  name: "Llama 3.1 8B Instruct",
  provider: "Ollama",
  quant: "Q4_K_M",
  contextTokens: "32K",
  contextPct: 72,
};

export const MODELS_ROUTING_TOGGLES = [
  {
    id: "auto-route",
    label: "Automatische modelroutering",
    hint: "Kies automatisch het beste model per taak",
    defaultOn: true,
  },
  {
    id: "cloud-fallback",
    label: "Fallback naar cloud providers",
    hint: "Gebruik externe providers indien nodig",
    defaultOn: true,
  },
];

export const MODELS_PROVIDERS: ProviderHealth[] = [
  { id: "ollama", name: "Ollama", kind: "Lokaal", status: "online", loaded: 4, total: 4, healthPct: 100 },
  { id: "hf", name: "Hugging Face", kind: "Cloud", status: "online", loaded: 3, total: 3, healthPct: 100 },
  { id: "openai", name: "OpenAI", kind: "API", status: "online", loaded: 3, total: 3, healthPct: 100 },
  { id: "anthropic", name: "Anthropic", kind: "API", status: "online", loaded: 3, total: 3, healthPct: 99 },
  { id: "google", name: "Google", kind: "API", status: "online", loaded: 2, total: 3, healthPct: 92 },
  { id: "cohere", name: "Cohere", kind: "API", status: "degraded", loaded: 2, total: 3, healthPct: 67 },
  { id: "nvidia", name: "NVIDIA", kind: "API", status: "online", loaded: 3, total: 3, healthPct: 100 },
];

export function modelStatusLabel(status: ModelLoadStatus): string {
  if (status === "geladen") return "Geladen";
  if (status === "beschikbaar") return "Beschikbaar";
  return "Niet geladen";
}
