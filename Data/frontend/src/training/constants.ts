/**
 * Structural Training V2 constants (tabs, method labels, optimizers).
 * Moved out of mocks so production UI never depends on mock modules for chrome.
 */

export const TRAINING_V2_TABS = ["General", "Model", "Dataset", "Training", "Advanced"] as const;
export type TrainingV2Tab = (typeof TRAINING_V2_TABS)[number];

export const TRAINING_DATASET_PREVIEW_TABS = ["Voorbeeld", "Statistieken", "Token distributie"] as const;
export type TrainingDatasetPreviewTab = (typeof TRAINING_DATASET_PREVIEW_TABS)[number];

/** Production training methods — fixture is never offered in the production selector. */
export const PRODUCTION_TRAINING_METHODS = ["sft", "lora", "qlora", "dpo"] as const;
export type ProductionTrainingMethod = (typeof PRODUCTION_TRAINING_METHODS)[number];

export const TRAINING_METHOD_LABELS: Record<string, string> = {
  sft: "Supervised Fine-Tuning (SFT)",
  lora: "LoRA",
  qlora: "QLoRA",
  dpo: "DPO",
};

export const TRAINING_OPTIMIZERS = [
  { value: "adamw_torch", label: "AdamW" },
  { value: "adamw_torch_fused", label: "AdamW fused" },
  { value: "adamw_bnb_8bit", label: "AdamW 8-bit" },
  { value: "paged_adamw_8bit", label: "Paged AdamW 8-bit" },
  { value: "paged_adamw_32bit", label: "Paged AdamW 32-bit" },
  { value: "adafactor", label: "Adafactor" },
  { value: "sgd", label: "SGD" },
] as const;

export const TRAINING_LR_SCHEDULERS = [
  { value: "linear", label: "Linear" },
  { value: "cosine", label: "Cosine" },
  { value: "cosine_with_restarts", label: "Cosine restarts" },
  { value: "constant", label: "Constant" },
  { value: "constant_with_warmup", label: "Constant + warmup" },
] as const;

export const TRAINING_PRECISION_OPTIONS = [
  { value: "fp32", label: "FP32" },
  { value: "fp16", label: "FP16" },
  { value: "bf16", label: "BF16" },
] as const;

export const ACTIVE_TRAINING_STATUSES = new Set([
  "queued",
  "preflight",
  "running",
  "evaluating",
  "exporting",
  "cancelling",
]);

export const RESUMABLE_TRAINING_STATUSES = new Set(["interrupted", "queued"]);

export const TERMINAL_TRAINING_STATUSES = new Set([
  "cancelled",
  "completed",
  "failed",
  "interrupted",
]);

export const TRAINING_STATUS_LABELS: Record<string, string> = {
  queued: "In wachtrij",
  preflight: "Preflight",
  running: "Training",
  evaluating: "Evalueren",
  exporting: "Exporteren",
  cancelling: "Stoppen…",
  cancelled: "Gestopt",
  completed: "Voltooid",
  failed: "Mislukt",
  interrupted: "Onderbroken",
};

export type TrainingStatusTone = "info" | "warning" | "success" | "danger" | "muted" | "training";

export function trainingStatusTone(status: string): TrainingStatusTone {
  switch (status) {
    case "running":
    case "evaluating":
    case "exporting":
      return "info";
    case "queued":
    case "preflight":
    case "cancelling":
      return "warning";
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "cancelled":
    case "interrupted":
      return "muted";
    default:
      return "training";
  }
}
