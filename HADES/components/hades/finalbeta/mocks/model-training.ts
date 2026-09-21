/** FINALBETA Model Training mock data (UI-only). */

export const TRAINING_TABS = ["Overzicht", "Datasets", "Model", "Framework", "Runs"] as const;
export type TrainingTab = (typeof TRAINING_TABS)[number];

export type DatasetStatus = "Gereed" | "Verwerken" | "Validatie";

export type TrainingDataset = {
  id: string;
  name: string;
  domain: string;
  source: string;
  split: string;
  size: string;
  status: DatasetStatus;
  description: string;
  examples: string;
  format: string;
  updated: string;
  quality: number;
};

export type TrainingRunStatus = "Actief" | "Voltooid" | "Mislukt" | "Gepauzeerd" | "Wachtrij";

export type TrainingRun = {
  id: string;
  name: string;
  model: string;
  dataset: string;
  strategy: string;
  progress: number;
  status: TrainingRunStatus;
  loss: string;
  eta: string;
  started: string;
  throughput: string;
  score: string;
};

export const DATASET_STATS = [
  { label: "Totaal datasets", value: "24", hint: "Lokale bibliotheek", tone: "cyan" as const },
  { label: "Totaal voorbeelden", value: "14.2M", hint: "Train + eval", tone: "gold" as const },
  { label: "Storage", value: "67.8 GB", hint: "SSD cache", tone: "blue" as const },
  { label: "Actieve pipelines", value: "3", hint: "Preprocess", tone: "green" as const },
  { label: "Validatie", value: "87%", hint: "Laatste batch", tone: "cyan" as const },
  { label: "Laatste sync", value: "2u 14m", hint: "Hugging Face", tone: "muted" as const },
];

export const mockDatasets: TrainingDataset[] = [
  {
    id: "ds-chat",
    name: "HADES-Chat",
    domain: "Conversatie",
    source: "Dataset Brain",
    split: "92 / 5 / 3",
    size: "4.8 GB",
    status: "Gereed",
    description:
      "Curated instruct-mix uit Chat, Knowledge en Evidence Vault. Geoptimaliseerd voor lokale assistant-responsen.",
    examples: "142.6K",
    format: "JSONL · chatml",
    updated: "16 sep 2026, 18:42",
    quality: 94,
  },
  {
    id: "ds-smol",
    name: "HuggingFaceTB/smoltalk",
    domain: "Instruct",
    source: "Hugging Face",
    split: "95 / 3 / 2",
    size: "1.1 GB",
    status: "Gereed",
    description: "Gesynchroniseerde open instruct-set voor snelle QLoRA warm-ups.",
    examples: "12.4K",
    format: "Parquet",
    updated: "17 sep 2026, 09:10",
    quality: 88,
  },
  {
    id: "ds-custom",
    name: "custom-instruct",
    domain: "Custom",
    source: "Lokaal",
    split: "90 / 7 / 3",
    size: "620 MB",
    status: "Verwerken",
    description: "Lokale instructies uit D:\\HADES\\data\\custom-instruct. Chunking + dedupe in pipeline.",
    examples: "8.1K",
    format: "JSONL",
    updated: "17 sep 2026, 11:02",
    quality: 76,
  },
  {
    id: "ds-research",
    name: "Research Corpus v3",
    domain: "Research",
    source: "Evidence Vault",
    split: "88 / 8 / 4",
    size: "12.4 GB",
    status: "Validatie",
    description: "Research-documenten met citation-aware splits voor framework evaluation.",
    examples: "1.8M",
    format: "JSONL · docs",
    updated: "15 sep 2026, 22:18",
    quality: 91,
  },
  {
    id: "ds-code",
    name: "Code-Assist Mix",
    domain: "Coding",
    source: "Lokaal + HF",
    split: "93 / 4 / 3",
    size: "3.2 GB",
    status: "Gereed",
    description: "Code-instruct paren voor Qwen2.5-Coder fine-tuning.",
    examples: "96.2K",
    format: "JSONL",
    updated: "14 sep 2026, 16:05",
    quality: 90,
  },
  {
    id: "ds-eval",
    name: "eval-holdout-v2",
    domain: "Eval",
    source: "Lokaal",
    split: "0 / 0 / 100",
    size: "180 MB",
    status: "Gereed",
    description: "Vaste holdout voor regressie-checks tussen training runs.",
    examples: "2.1K",
    format: "JSONL",
    updated: "12 sep 2026, 08:40",
    quality: 97,
  },
];

export const DATASET_PIPELINE = [
  { step: "Ingest", detail: "Bronnen laden & checksum", state: "done" as const },
  { step: "Normalize", detail: "Schema + encoding", state: "done" as const },
  { step: "Dedupe", detail: "Near-duplicate filter", state: "doing" as const },
  { step: "Split", detail: "Train / val / test", state: "todo" as const },
  { step: "Validate", detail: "Quality gates", state: "todo" as const },
];

export const DATASET_SOURCES = [
  { name: "Hugging Face", path: "HuggingFaceTB/smoltalk", tag: "Sync", count: "12.4K" },
  { name: "Lokale dataset", path: "D:\\HADES\\data\\custom-instruct", tag: "Lokaal", count: "8.1K" },
  { name: "Dataset Brain", path: "HADES Knowledge v1.2", tag: "Brain", count: "122.1K" },
];

export const DATASET_ACTIVITY = [
  { title: "Sync smoltalk voltooid", ago: "14m", tone: "green" as const },
  { title: "custom-instruct chunking", ago: "32m", tone: "cyan" as const },
  { title: "Research Corpus validatie gestart", ago: "1u", tone: "gold" as const },
  { title: "HADES-Chat quality score 94", ago: "3u", tone: "green" as const },
];

export const DATASET_STORAGE = [
  { label: "Train sets", pct: 58, value: "39.3 GB" },
  { label: "Eval / holdout", pct: 12, value: "8.1 GB" },
  { label: "Cache / shards", pct: 22, value: "14.9 GB" },
  { label: "Artifacts", pct: 8, value: "5.5 GB" },
];

export const DATASET_DETAIL_TABS = ["Overzicht", "Schema", "Voorbeeld", "Statistieken"] as const;
export type DatasetDetailTab = (typeof DATASET_DETAIL_TABS)[number];

export const DATASET_SCHEMA_FIELDS = [
  { name: "messages", type: "array<object>", required: true },
  { name: "role", type: "string", required: true },
  { name: "content", type: "string", required: true },
  { name: "meta.source", type: "string", required: false },
  { name: "meta.quality", type: "number", required: false },
];

export const DATASET_SAMPLE_ROWS = [
  { role: "user", content: "Vat de laatste research-notities samen." },
  { role: "assistant", content: "Ik open Evidence Vault en geef een bron-gebonden samenvatting." },
  { role: "user", content: "Maak een QLoRA plan voor Qwen2.5-Coder." },
];

export const MODEL_STATUS = [
  { label: "Selected model", value: "Qwen2.5-Coder", hint: "Base checkpoint" },
  { label: "Parameters", value: "7B", hint: "Dense" },
  { label: "Context", value: "128K", hint: "RoPE scaled" },
  { label: "Quantization", value: "Q4_K_M", hint: "GGUF-ready" },
  { label: "Training mode", value: "QLoRA", hint: "4-bit adapters" },
];

export const MODEL_CAPABILITIES = [
  { label: "Coding", score: 92 },
  { label: "Chat", score: 78 },
  { label: "Reasoning", score: 84 },
  { label: "Tools", score: 88 },
  { label: "Safety", score: 81 },
  { label: "Multilang", score: 74 },
];

export const MODEL_COMPAT = [
  { label: "VRAM ≥ 12 GB", ok: true },
  { label: "Transformers ≥ 4.46", ok: true },
  { label: "BitsAndBytes", ok: true },
  { label: "FlashAttention 2", ok: false },
  { label: "ATME dual memory", ok: true },
];

export const MODEL_PROFILES = [
  { id: "coder", name: "Coder QLoRA", desc: "Code-first adapters", tag: "Actief" },
  { id: "chat", name: "Chat balanced", desc: "Instruct + safety", tag: "Preset" },
  { id: "research", name: "Research long-ctx", desc: "128K retrieval", tag: "Preset" },
];

export const FRAMEWORK_STATUS = [
  { label: "Framework status", value: "Healthy", hint: "Alle nodes online", tone: "green" as const },
  { label: "Brain nodes", value: "9/9", hint: "Fully meshed", tone: "cyan" as const },
  { label: "Memory", value: "1.2M", hint: "Indexed items", tone: "gold" as const },
  { label: "Actieve tools", value: "12/14", hint: "2 gedeactiveerd", tone: "blue" as const },
  { label: "Safety", value: "Strict", hint: "Local policies", tone: "green" as const },
  { label: "Runtime load", value: "42%", hint: "CPU+GPU avg", tone: "cyan" as const },
];

export const FRAMEWORK_NODES = [
  { id: "research", label: "Research", x: 50, y: 8 },
  { id: "coding", label: "Coding", x: 88, y: 32 },
  { id: "media", label: "Media", x: 88, y: 68 },
  { id: "safety", label: "Safety", x: 50, y: 92 },
  { id: "trading", label: "Trading", x: 12, y: 68 },
  { id: "agents", label: "Agents", x: 12, y: 32 },
];

export const FRAMEWORK_OBJECTIVES = [
  { label: "Routing precisie", pct: 86 },
  { label: "Memory recall", pct: 79 },
  { label: "Tool success", pct: 91 },
  { label: "Safety compliance", pct: 97 },
  { label: "Latency budget", pct: 72 },
];

export const FRAMEWORK_SIGNALS = [
  { signal: "Tool-call accuracy", value: "94.2%", trend: "+1.8%", tone: "green" as const },
  { signal: "Retrieval nDCG", value: "0.81", trend: "+0.04", tone: "green" as const },
  { signal: "Refusal precision", value: "98.1%", trend: "stable", tone: "cyan" as const },
  { signal: "Hallucination rate", value: "3.4%", trend: "−0.6%", tone: "green" as const },
];

export const FRAMEWORK_ACTIVITY = [
  { title: "Neural core sync", detail: "Evidence Vault → Brain graph", ago: "8m" },
  { title: "Safety policy reload", detail: "Strict local profile", ago: "26m" },
  { title: "Tool schema refresh", detail: "12/14 tools eligible", ago: "1u 12m" },
  { title: "Objective eval batch", detail: "Score 0.87", ago: "3u" },
];

export const RUN_STATS = [
  { label: "Actieve", value: "2", tone: "gold" as const },
  { label: "Voltooide", value: "47", tone: "green" as const },
  { label: "Mislukte", value: "3", tone: "warn" as const },
  { label: "Gem. throughput", value: "1.84 tok/s", tone: "cyan" as const },
  { label: "Beste score", value: "9.4 / 10", tone: "gold" as const },
  { label: "Totale training uren", value: "186u", tone: "blue" as const },
];

export const mockRuns: TrainingRun[] = [
  {
    id: "run-llama",
    name: "HADES-Llama-8B",
    model: "Llama-3.1-8B-Instruct",
    dataset: "HADES-Chat",
    strategy: "ATME · QLoRA",
    progress: 24,
    status: "Actief",
    loss: "0.842",
    eta: "1u 34m",
    started: "17 sep 2026, 14:22",
    throughput: "2.1 tok/s",
    score: "—",
  },
  {
    id: "run-qwen",
    name: "Qwen-Coder-QLoRA",
    model: "Qwen2.5-Coder-7B",
    dataset: "Code-Assist Mix",
    strategy: "Fixed · QLoRA",
    progress: 61,
    status: "Actief",
    loss: "0.612",
    eta: "42m",
    started: "17 sep 2026, 16:05",
    throughput: "2.4 tok/s",
    score: "—",
  },
  {
    id: "run-atme",
    name: "ATME-bench-4090",
    model: "Hardware profile",
    dataset: "—",
    strategy: "Benchmark",
    progress: 100,
    status: "Voltooid",
    loss: "—",
    eta: "—",
    started: "14 nov 2024, 09:00",
    throughput: "—",
    score: "9.4 / 10",
  },
  {
    id: "run-fail",
    name: "Qwen14B-QLoRA",
    model: "Qwen2.5-14B",
    dataset: "Research Corpus v3",
    strategy: "QLoRA",
    progress: 4,
    status: "Mislukt",
    loss: "1.920",
    eta: "—",
    started: "12 sep 2026, 21:14",
    throughput: "0.4 tok/s",
    score: "OOM",
  },
  {
    id: "run-mistral",
    name: "Mistral-7B-eval",
    model: "Mistral-7B-Instruct",
    dataset: "eval-holdout-v2",
    strategy: "Eval only",
    progress: 100,
    status: "Voltooid",
    loss: "0.521",
    eta: "—",
    started: "10 sep 2026, 11:40",
    throughput: "3.1 tok/s",
    score: "ppl 5.21",
  },
  {
    id: "run-queue",
    name: "Framework-Neural-v3",
    model: "HADES Neural",
    dataset: "Multi-domain",
    strategy: "Framework",
    progress: 0,
    status: "Wachtrij",
    loss: "—",
    eta: "wacht",
    started: "—",
    throughput: "—",
    score: "—",
  },
];

export const RUN_METRICS_POINTS = [78, 72, 68, 64, 60, 58, 55, 52, 50, 48, 46, 44, 42, 40, 38];

export const RUN_DETAIL_TABS = ["Overzicht", "Metrics", "Parameters", "Logboek"] as const;
export type RunDetailTab = (typeof RUN_DETAIL_TABS)[number];

export const RUN_LOG_LINES = [
  "[14:22:01] ATME planner: dual-memory profile selected",
  "[14:22:08] Loading base model meta-llama/Llama-3.1-8B-Instruct",
  "[14:22:41] QLoRA adapters attached (r=64, alpha=128)",
  "[14:23:02] Dataset HADES-Chat ready · 142.6K examples",
  "[14:24:18] Step 100 · loss 1.204 · vram 12.8 GB",
  "[14:48:33] Step 2480 · loss 0.842 · bottleneck VRAM 71%",
];
