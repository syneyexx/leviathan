/** FINALBETA Model Training pixel mock (General tab). */

export const TRAINING_PIXEL_TABS = ["General", "Model", "Dataset", "Training", "Advanced"] as const;
export type TrainingPixelTab = (typeof TRAINING_PIXEL_TABS)[number];

export const TRAINING_PIXEL_DATASET_PREVIEW_TABS = ["Voorbeeld", "Statistieken", "Token distributie"] as const;
export type TrainingDatasetPreviewTab = (typeof TRAINING_PIXEL_DATASET_PREVIEW_TABS)[number];

export type TrainingStatusCard = {
  id: string;
  label: string;
  value: string;
  hint: string;
  tone?: "default" | "gold" | "cyan" | "green" | "warn";
  icon?: string;
  spark?: number[];
};

export const TRAINING_STATUS_CARDS: TrainingStatusCard[] = [
  {
    id: "active",
    label: "Actieve runs",
    value: "3",
    hint: "2 trainen | 1 valideren",
    tone: "cyan",
    spark: [12, 18, 14, 22, 19, 26, 24, 28, 25, 30, 27, 32],
  },
  {
    id: "queue",
    label: "Wachtrij",
    value: "5",
    hint: "3 hoge prioriteit",
    icon: "list",
  },
  {
    id: "model",
    label: "Geselecteerd model",
    value: "Llama 3.1 8B Instruct",
    hint: "Meta · instruct",
    tone: "gold",
    icon: "meta",
  },
  {
    id: "datasets",
    label: "Datasets",
    value: "4",
    hint: "128.4M tokens",
    icon: "database",
  },
  {
    id: "vram",
    label: "Geschat VRAM",
    value: "18.6 GB",
    hint: "op 1 × A100 (80GB)",
    icon: "bolt",
  },
  {
    id: "checkpoints",
    label: "Checkpoints",
    value: "12",
    hint: "5.6 GB gebruikt",
    icon: "save",
  },
  {
    id: "health",
    label: "Training health",
    value: "Gezond",
    hint: "Alle systemen nominaal",
    tone: "green",
    icon: "pulse",
  },
];

export const TRAINING_RUN_FORM = {
  name: "llama31-nl-assistant-v1",
  project: "NL Assistant",
  outputDir: "/models/runs/llama31-nl-v1",
  description:
    "Nederlandstalige assistent, gefinetuned op interne kennis en conversatiedata. Doel: stabiele instruct-volging met lage hallucinatie-rate.",
  tags: ["nl", "assistant", "sft", "v1"],
};

export const TRAINING_BASE_MODEL = {
  model: "Llama 3.1 8B Instruct",
  provider: "Meta",
  parameters: "8.0B",
  context: "128,000",
  quant: "Geen (FP16)",
  info: {
    architecture: "Transformer · decoder-only",
    license: "Llama 3.1 Community",
    family: "Llama 3.1",
    notes: "Geschikt voor SFT/LoRA op 1× A100. Instruct-template: chatml.",
  },
};

export const TRAINING_HARDWARE = {
  device: "NVIDIA A100 (80GB)",
  vramPerGpu: "80 GB",
  gpuCount: "1",
  batchSize: "4",
  gradAccum: "8",
  precision: "bf16",
  dataloaderWorkers: "4",
  usage: [
    { label: "VRAM gebruik", value: "18.6 / 80 GB", pct: 23 },
    { label: "Systeem RAM", value: "49%", pct: 49 },
    { label: "Opslag", value: "30%", pct: 30 },
  ],
};

export type TrainingDatasetRow = {
  id: string;
  name: string;
  split: string;
  examples: string;
  tokens: string;
  selected: boolean;
};

export const TRAINING_DATASET_ROWS: TrainingDatasetRow[] = [
  { id: "ds1", name: "NL-Assistant v2", split: "train", examples: "125,432", tokens: "42.8M", selected: true },
  { id: "ds2", name: "OpenOrca (NL)", split: "train", examples: "88,210", tokens: "31.2M", selected: true },
  { id: "ds3", name: "HADES-Knowledge Mix", split: "train", examples: "54,980", tokens: "28.6M", selected: true },
  { id: "ds4", name: "Eval-NL held-out", split: "validation", examples: "6,240", tokens: "2.1M", selected: true },
];

export const TRAINING_DATASET_PREVIEW = `### Instruction:
Leg uit wat fine-tuning is in één alinea.

### Response:
Fine-tuning past een voorgetraind taalmodel aan met domeinspecifieke voorbeelden, zodat het beter volgt wat jij vraagt.`;

export const TRAINING_DATASET_SETTINGS = {
  validationPct: 5,
  formatTemplate: "Alpaca",
};

export type TrainingSafetyToggle = {
  id: string;
  label: string;
  description: string;
  on: boolean;
};

export const TRAINING_SAFETY_TOGGLES: TrainingSafetyToggle[] = [
  { id: "val", label: "Validatie tijdens training", description: "Eval elke N stappen op held-out set", on: true },
  { id: "ckpt", label: "Automatische checkpoints", description: "Schrijf checkpoint bij interval", on: true },
  { id: "resume", label: "Hervatten vanaf laatste checkpoint", description: "Bij crash veilig verder", on: false },
  { id: "early", label: "Early stopping", description: "Stop bij plateau validatie-loss", on: true },
];

export const TRAINING_SAFETY_NUMBERS = {
  checkpointInterval: 500,
  maxEpochs: 10,
  earlyStoppingPatience: 3,
  maxTrainingHours: 24,
};

export type TrainingLogLine = {
  time: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
};

export const TRAINING_LOG_LINES: TrainingLogLine[] = [
  { time: "14:24:01", level: "INFO", message: "Dataset NL-Assistant v2 geladen (125,432 voorbeelden)" },
  { time: "14:24:08", level: "INFO", message: "Tokenizer geladen · vocab 128,256" },
  { time: "14:25:12", level: "INFO", message: "Training gestart · batch 4 × grad_accum 8" },
  { time: "14:26:44", level: "WARNING", message: "Gradient norm piek gedetecteerd · clipping actief" },
  { time: "14:27:18", level: "INFO", message: "Stap 12,480 · loss 0.0324 · 2,841 tok/s" },
  { time: "14:27:36", level: "INFO", message: "Checkpoint checkpoint-12500 geschreven (2.1 GB)" },
];

export type TrainingCheckpoint = {
  name: string;
  step: string;
  size: string;
  when: string;
};

export const TRAINING_CHECKPOINTS: TrainingCheckpoint[] = [
  { name: "checkpoint-12500", step: "12,500", size: "2.1 GB", when: "14:27:36" },
  { name: "checkpoint-12000", step: "12,000", size: "2.1 GB", when: "14:18:02" },
  { name: "checkpoint-11500", step: "11,500", size: "2.1 GB", when: "14:08:41" },
  { name: "checkpoint-11000", step: "11,000", size: "2.1 GB", when: "13:59:10" },
];

export const TRAINING_MONITOR = {
  live: true,
  epoch: { current: 2, total: 10, pct: 20 },
  steps: { current: 12480, total: 50000, pct: 25 },
  elapsed: "03:27:18",
  eta: "14:32:10",
  lossSeries: {
    train: [2.8, 2.1, 1.6, 1.2, 0.95, 0.72, 0.55, 0.42, 0.34, 0.29, 0.26, 0.24, 0.22, 0.2, 0.18, 0.16, 0.14, 0.12, 0.1, 0.085, 0.072, 0.062, 0.055, 0.048, 0.042, 0.038, 0.035, 0.033, 0.032, 0.0324],
    val: [2.9, 2.3, 1.8, 1.35, 1.05, 0.82, 0.64, 0.5, 0.41, 0.36, 0.32, 0.3, 0.28, 0.26, 0.24, 0.22, 0.2, 0.18, 0.16, 0.14, 0.12, 0.1, 0.09, 0.08, 0.075, 0.07, 0.068, 0.065, 0.063, 0.062],
  },
  lrSeries: [0, 0.00002, 0.00004, 0.00006, 0.00008, 0.0001, 0.0001, 0.000095, 0.00009, 0.000085, 0.00008, 0.000075, 0.00007, 0.000065, 0.00006, 0.000055, 0.00005, 0.000045, 0.00004, 0.000035],
  stats: [
    { label: "Tokens / seconde", value: "2,841" },
    { label: "GPU gebruik", value: "87%" },
    { label: "GPU temperatuur", value: "68°C" },
    { label: "Verlies (laatste)", value: "0.0324" },
  ],
};

export type TrainingQueueRow = {
  rank: number;
  name: string;
  model: string;
  dataset: string;
  status: "Training" | "Valideren" | "In wachtrij";
  progress: number;
  priority: "Hoog" | "Normaal" | "Laag";
};

export const TRAINING_QUEUE: TrainingQueueRow[] = [
  {
    rank: 1,
    name: "llama31-nl-assistant-v1",
    model: "Llama 3.1 8B",
    dataset: "NL-Assistant v2",
    status: "Training",
    progress: 25,
    priority: "Hoog",
  },
  {
    rank: 2,
    name: "orca-nl-sft-v2",
    model: "Llama 3.1 8B",
    dataset: "OpenOrca (NL)",
    status: "Valideren",
    progress: 62,
    priority: "Hoog",
  },
  {
    rank: 3,
    name: "knowledge-mix-qlora",
    model: "Mistral 7B",
    dataset: "HADES-Knowledge",
    status: "In wachtrij",
    progress: 0,
    priority: "Normaal",
  },
  {
    rank: 4,
    name: "eval-nl-baseline",
    model: "Llama 3.1 8B",
    dataset: "Eval-NL",
    status: "In wachtrij",
    progress: 0,
    priority: "Normaal",
  },
  {
    rank: 5,
    name: "assistant-v1-resume",
    model: "Llama 3.1 8B",
    dataset: "NL-Assistant v2",
    status: "In wachtrij",
    progress: 0,
    priority: "Laag",
  },
];
