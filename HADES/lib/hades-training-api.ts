import { API_BASE, HadesApiError } from "@/lib/hades-api";

export type TrainingCapabilities = {
  trainer_ready: boolean;
  required_packages: string[];
  packages: Record<string, { available: boolean; version: string | null }>;
  workspace: string;
  upload_limit_bytes: number;
  supported_local_extensions: string[];
  training_mode: "lora_adapter" | string;
  note: string;
  atme?: {
    planner_version: number;
    strategies: string[];
    streaming_architecture_v1: string;
    streamed_resume_supported: boolean;
  };
};

export type TrainingDataset = {
  id: string;
  name: string;
  source_type: "local" | "upload" | "huggingface" | string;
  status: string;
  format: string;
  path: string | null;
  size_bytes: number | null;
  row_count: number | null;
  columns: string[];
  preview: Array<Record<string, unknown>>;
  mapping: { text_field?: string };
  source: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type HuggingFaceSplit = { config: string; split: string };
export type HuggingFaceInspect = { dataset_id: string; splits: HuggingFaceSplit[] };
export type HuggingFacePreview = {
  dataset_id: string;
  config: string;
  split: string;
  columns: string[];
  preview: Array<Record<string, unknown>>;
  row_count: number | null;
  partial: boolean;
};

export type MemoryStrategy =
  | "auto"
  | "gpu_resident"
  | "gpu_resident_4bit"
  | "cpu_offload"
  | "ram_layer_streaming"
  | "nvme_layer_streaming";

export type TrainingExecutionPlan = {
  strategy: MemoryStrategy | string;
  precision?: string;
  base_model_residency?: string;
  trainable_residency?: string;
  optimizer_residency?: string;
  activation_checkpointing?: string;
  buffer_count?: number;
  estimated_vram_peak_bytes?: number;
  estimated_ram_peak_bytes?: number;
  estimated_storage_bytes?: number;
  estimated_storage_read_bytes_per_step?: number;
  safety_margin_vram_bytes?: number;
  expected_bottleneck?: string;
  confidence?: "high" | "medium" | "low" | string;
  warnings?: string[];
  planner_version?: number;
  model_profile_hash?: string;
  hardware_profile_hash?: string;
  feasible?: boolean;
  rejection_reason?: string | null;
  selection_reason?: string | null;
  failure_code?: string | null;
};

export type TrainingPlanResponse = {
  selected: TrainingExecutionPlan | null;
  candidates: TrainingExecutionPlan[];
  hardware_profile_hash: string;
  model_profile_hash: string;
  planner_version: number;
};

export type TrainingJob = {
  id: string;
  dataset_id: string;
  dataset_name: string | null;
  base_model: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed" | string;
  progress: number;
  step: number;
  max_steps: number;
  parameters: Record<string, number | boolean | string | null>;
  output_dir: string;
  log_path: string;
  error: string | null;
  failure_code?: string | null;
  pid: number | null;
  metrics?: Record<string, string | number>;
  requested_memory_strategy?: string;
  resolved_execution_plan?: TrainingExecutionPlan | null;
  runtime_peak_vram_bytes?: number | null;
  runtime_peak_ram_bytes?: number | null;
  runtime_bytes_host_to_device?: number | null;
  observed_bottleneck?: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type TrainingJobInput = {
  dataset_id: string;
  base_model: string;
  max_steps: number;
  learning_rate: number;
  sequence_length: number;
  batch_size: number;
  gradient_accumulation_steps: number;
  lora_r: number;
  lora_alpha: number;
  lora_dropout: number;
  load_in_4bit: boolean;
  memory_strategy?: MemoryStrategy;
  activation_checkpointing?: "auto" | "enabled" | "disabled";
  host_memory_limit_bytes?: number | null;
  vram_reserve_bytes?: number | null;
  stream_buffer_count?: number | "auto";
  experimental_streaming_allowed?: boolean;
  hf_token?: string;
  approved_network: boolean;
  approved_subprocess?: boolean;
};

export type HardwareSnapshot = {
  gpu: Record<string, unknown>;
  host: Record<string, unknown>;
  storage: Array<Record<string, unknown>>;
  packages: Record<string, { available: boolean; version: string | null }>;
  profile_hash: string;
  collected_at: string;
};

export type TrainingTelemetry = {
  job_id: string;
  status?: string;
  strategy?: string | null;
  runtime_peak_vram_bytes?: number | null;
  runtime_peak_ram_bytes?: number | null;
  runtime_bytes_host_to_device?: number | null;
  observed_bottleneck?: string | null;
  samples: Array<Record<string, unknown>>;
};

async function trainingRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }
  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    let detail: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        message = String((body.detail as { message: unknown }).message);
      }
    } catch {
      // Keep HTTP status fallback for non-JSON errors.
    }
    throw new HadesApiError(message, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const hadesTrainingApi = {
  capabilities: () => trainingRequest<TrainingCapabilities>("/training/capabilities"),
  hardware: () => trainingRequest<HardwareSnapshot>("/training/hardware"),
  inspectModel: (values: { base_model: string; approved_network?: boolean }) =>
    trainingRequest<Record<string, unknown>>("/training/models/inspect", { method: "POST", body: JSON.stringify(values) }),
  createPlan: (values: Partial<TrainingJobInput> & { base_model: string }) =>
    trainingRequest<TrainingPlanResponse>("/training/plans", { method: "POST", body: JSON.stringify(values) }),
  startBenchmark: (values: { approved: boolean; include_storage?: boolean; include_gpu?: boolean }) =>
    trainingRequest<Record<string, unknown>>("/training/benchmarks", { method: "POST", body: JSON.stringify(values) }),
  latestBenchmark: () => trainingRequest<Record<string, unknown>>("/training/benchmarks/latest"),
  datasets: () => trainingRequest<TrainingDataset[]>("/training/datasets"),
  registerLocal: (values: { path: string; name?: string; text_field?: string; approved_file_read: boolean }) =>
    trainingRequest<TrainingDataset>("/training/datasets/local", { method: "POST", body: JSON.stringify(values) }),
  upload: (file: File, values: { name?: string; text_field?: string } = {}) => {
    const body = new FormData();
    body.set("file", file);
    body.set("name", values.name || "");
    body.set("text_field", values.text_field || "");
    return trainingRequest<TrainingDataset>("/training/datasets/upload", { method: "POST", body });
  },
  inspectHuggingFace: (values: { dataset_id: string; token?: string; approved_network: boolean }) =>
    trainingRequest<HuggingFaceInspect>("/training/huggingface/inspect", { method: "POST", body: JSON.stringify(values) }),
  previewHuggingFace: (values: { dataset_id: string; config: string; split: string; token?: string; rows?: number; approved_network: boolean }) =>
    trainingRequest<HuggingFacePreview>("/training/huggingface/preview", { method: "POST", body: JSON.stringify(values) }),
  registerHuggingFace: (values: { dataset_id: string; config: string; split: string; name?: string; text_field?: string; token?: string; approved_network: boolean; rows?: number }) =>
    trainingRequest<TrainingDataset>("/training/datasets/huggingface", { method: "POST", body: JSON.stringify({ rows: 20, ...values }) }),
  updateMapping: (datasetId: string, textField: string) =>
    trainingRequest<TrainingDataset>(`/training/datasets/${encodeURIComponent(datasetId)}/mapping`, {
      method: "PUT",
      body: JSON.stringify({ text_field: textField }),
    }),
  deleteDataset: (datasetId: string) =>
    trainingRequest<void>(`/training/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" }),
  jobs: () => trainingRequest<TrainingJob[]>("/training/jobs"),
  job: (jobId: string) => trainingRequest<TrainingJob>(`/training/jobs/${encodeURIComponent(jobId)}`),
  jobTelemetry: (jobId: string) =>
    trainingRequest<TrainingTelemetry>(`/training/jobs/${encodeURIComponent(jobId)}/telemetry`),
  startJob: (values: TrainingJobInput) =>
    trainingRequest<TrainingJob>("/training/jobs", { method: "POST", body: JSON.stringify(values) }),
  cancelJob: (jobId: string) =>
    trainingRequest<TrainingJob>(`/training/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  jobLog: (jobId: string) =>
    trainingRequest<{ content: string }>(`/training/jobs/${encodeURIComponent(jobId)}/log`),
};
