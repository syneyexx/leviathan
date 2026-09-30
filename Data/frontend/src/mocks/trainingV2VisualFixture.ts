/**
 * TEST-ONLY deterministic Screen 1 Training fixture for visual regression.
 * Activated solely via Playwright route mocking + window.__LV_V2_VISUAL_FIXTURE__.
 * Never imported into production TrainingPage/useTrainingWorkspace data paths as
 * defaults — production always calls the real Training APIs.
 *
 * Values approximate `Data/docs/ui_reference/training-v2-reference.png`
 * (dual-GPU workstation, Leviathan Trainer, trainable HF models — no GGUF).
 */

const GIB = 1024 ** 3;
const gib = (n: number) => Math.round(n * GIB);

export const TRAINING_V2_VISUAL_FROZEN_ISO = "2025-06-02T10:15:00";

const STABLE_GTX = "gpu-0-gtx1060";
const STABLE_RTX = "gpu-1-rtx3060ti";

const CAPABILITIES = {
  packages: [
    { name: "torch", available: true, version: "2.4.1", importError: null },
    { name: "transformers", available: true, version: "4.44.2", importError: null },
    { name: "peft", available: true, version: "0.12.0", importError: null },
    { name: "bitsandbytes", available: true, version: "0.43.3", importError: null },
    { name: "flash_attn", available: false, version: null, importError: "not installed" },
  ],
  canRunFixture: true,
  canRunSft: true,
  canRunLora: true,
  canRunQlora: true,
  canRunDpo: true,
  canRunDpoMicro: true,
  canUseFlashAttention: false,
  canUse8bitOptimizer: true,
  cudaAvailable: true,
  canRunRewardModel: false,
  canRunGrpo: false,
  canRunRl: false,
  rewardModelStatus: "FEATURE_GATED",
  grpoStatus: "FEATURE_GATED",
  rlStatus: "FEATURE_GATED",
  dpoHfStatus: "SUPPORTED",
  methodSupport: {
    sft: { method: "sft", status: "SUPPORTED", operational: true, requires: [], missingPackages: [], reasons: [] },
    lora: { method: "lora", status: "SUPPORTED", operational: true, requires: ["peft"], missingPackages: [], reasons: [] },
    qlora: {
      method: "qlora",
      status: "SUPPORTED",
      operational: true,
      requires: ["peft", "bitsandbytes"],
      missingPackages: [],
      reasons: [],
    },
    dpo: { method: "dpo", status: "SUPPORTED", operational: true, requires: ["trl"], missingPackages: [], reasons: [] },
  },
  productionMethods: ["sft", "lora", "qlora", "dpo"],
  deviceStrategies: ["auto", "single"],
  multiGpuStatus: "UNSUPPORTED",
  ready: true,
  missingForSft: [],
  missingForLora: [],
  missingForQlora: [],
  missingForDpo: [],
  notes: ["Leviathan Trainer — PyTorch / Transformers / PEFT"],
  truth: {
    optional_ml_deps_do_not_crash_imports: true,
    fixture_is_not_production_ready: true,
    ready_requires_production_method: true,
  },
};

const HARDWARE = {
  cpuModel: "AMD Ryzen 7",
  logicalCores: 16,
  physicalCores: 8,
  ramTotalBytes: gib(16),
  ramAvailableBytes: gib(9.8),
  diskFreeBytes: gib(420),
  gpus: [
    {
      index: 0,
      name: "GTX 1060",
      stableDeviceId: STABLE_GTX,
      uuid: "GPU-fixture-0",
      pciBusId: "0000:01:00.0",
      totalVramBytes: gib(6),
      usedVramBytes: gib(4.2),
      freeVramBytes: gib(1.8),
      computeCapability: "6.1",
      utilizationPct: 70,
      temperatureC: 68,
      probeSource: "nvidia-smi",
    },
    {
      index: 1,
      name: "RTX 3060 Ti",
      stableDeviceId: STABLE_RTX,
      uuid: "GPU-fixture-1",
      pciBusId: "0000:02:00.0",
      totalVramBytes: gib(16),
      usedVramBytes: gib(6.8),
      freeVramBytes: gib(9.2),
      computeCapability: "8.6",
      utilizationPct: 43,
      temperatureC: 54,
      probeSource: "nvidia-smi",
    },
  ],
  cudaAvailable: true,
  cudaRuntimeVersion: "12.4",
  torchCudaVersion: "12.4",
  driverVersion: "550.90.07",
  supportsFp16: true,
  supportsBf16: true,
  supports4bit: true,
  notes: [],
  measuredAt: TRAINING_V2_VISUAL_FROZEN_ISO,
  truth: { no_fabricated_gpu_telemetry: true, gpu_absent_when_unmeasured: false },
};

const DATASETS = {
  datasets: [
    {
      datasetId: "ds-alpaca-nl",
      name: "Alpaca Dutch",
      displayName: "Alpaca Dutch",
      sourceType: "local",
      status: "ready",
      description: "NL instruct pairs",
      schemaVersion: 1,
      rowCount: 52300,
      detectedFormat: "Instruct",
      createdAt: "2025-05-01T10:00:00",
      updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
    },
    {
      datasetId: "ds-sharegpt-nl",
      name: "ShareGPT NL",
      displayName: "ShareGPT NL",
      sourceType: "huggingface",
      status: "ready",
      description: "Chat turns",
      schemaVersion: 1,
      rowCount: 88100,
      detectedFormat: "Chat",
      createdAt: "2025-05-02T10:00:00",
      updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
    },
    {
      datasetId: "ds-orca-nl",
      name: "OpenOrca NL",
      displayName: "OpenOrca NL",
      sourceType: "huggingface",
      status: "ready",
      description: "Orca style",
      schemaVersion: 1,
      rowCount: 120400,
      detectedFormat: "Instruct",
      createdAt: "2025-05-03T10:00:00",
      updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
    },
  ],
};

const VERSIONS: Record<string, { versions: Array<Record<string, unknown>> }> = {
  "ds-alpaca-nl": {
    versions: [
      {
        versionId: "ver-alpaca-v1",
        datasetId: "ds-alpaca-nl",
        versionLabel: "v1",
        status: "ready",
        kind: "snapshot",
        rowCount: 52300,
        createdAt: "2025-05-01T10:00:00",
        updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      },
    ],
  },
  "ds-sharegpt-nl": {
    versions: [
      {
        versionId: "ver-sharegpt-v1",
        datasetId: "ds-sharegpt-nl",
        versionLabel: "v1",
        status: "ready",
        kind: "snapshot",
        rowCount: 88100,
        createdAt: "2025-05-02T10:00:00",
        updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      },
    ],
  },
  "ds-orca-nl": {
    versions: [
      {
        versionId: "ver-orca-v1",
        datasetId: "ds-orca-nl",
        versionLabel: "v1",
        status: "ready",
        kind: "snapshot",
        rowCount: 120400,
        createdAt: "2025-05-03T10:00:00",
        updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      },
    ],
  },
};

function hfModel(partial: Record<string, unknown>) {
  return {
    providerId: "hf-local",
    source: "huggingface",
    objectType: "llm",
    format: "safetensors",
    capabilities: {
      chat: "supported",
      reasoning: "unverified",
      coding: "unverified",
      toolCalling: "unverified",
      structuredOutput: "unverified",
      vision: "unsupported",
      embeddings: "unsupported",
      streaming: "supported",
    },
    lifecycleState: "available",
    health: "healthy",
    active: false,
    loaded: false,
    tags: ["trainable"],
    metadata: {},
    ...partial,
  };
}

const MODELS = {
  models: [
    hfModel({
      id: "Qwen/Qwen2.5-14B",
      displayName: "Qwen2.5-14B",
      family: "Qwen",
      architecture: "qwen2",
      parameterCount: 14_000_000_000,
    }),
    hfModel({
      id: "meta-llama/Llama-3.2-3B",
      displayName: "Llama-3.2-3B",
      family: "Llama",
      architecture: "llama",
      parameterCount: 3_000_000_000,
    }),
    hfModel({
      id: "mistralai/Mistral-7B-v0.3",
      displayName: "Mistral-7B",
      family: "Mistral",
      architecture: "mistral",
      parameterCount: 7_000_000_000,
    }),
    // GGUF must be filtered out of the trainable panel.
    {
      id: "qwen2.5-14b-instruct-q4_k_m.gguf",
      displayName: "Qwen2.5-14B-Instruct Q4_K_M",
      providerId: "lmstudio-fixture-1",
      source: "lm_studio",
      objectType: "llm",
      format: "gguf",
      family: "Qwen",
      quantization: "Q4_K_M",
      parameterCount: 14_000_000_000,
      capabilities: {
        chat: "supported",
        reasoning: "unverified",
        coding: "unverified",
        toolCalling: "unverified",
        structuredOutput: "unverified",
        vision: "unsupported",
        embeddings: "unsupported",
        streaming: "supported",
      },
      lifecycleState: "available",
      health: "healthy",
      active: true,
      loaded: true,
      tags: ["gguf"],
      metadata: {},
    },
  ],
  status: { runtime: "mixed", online: true },
};

const JOB_RUNNING = {
  jobId: "job-qwen-nl-sft",
  name: "qwen2.5-nl-sft",
  status: "running",
  phase: "train",
  method: "sft",
  baseModelRef: "Qwen/Qwen2.5-14B",
  datasetVersionId: "ver-alpaca-v1",
  outputDir: "/tmp/training/job-qwen-nl-sft",
  config: {
    epochs: 3,
    train_batch_size: 4,
    learning_rate: 2e-5,
    max_seq_length: 2048,
    precision: "bf16",
    device_strategy: "single",
    selected_stable_device_ids: [STABLE_RTX],
    optimizer: "adamw_bnb_8bit",
    lr_scheduler_type: "cosine",
    gradient_checkpointing: true,
    flash_attention: false,
    eval_during_training: true,
  },
  planner: {},
  preflight: { verdict: "PASS" },
  progress: 0.67,
  cancelRequested: false,
  workerPid: 4242,
  checkpoint: {},
  metricsSummary: {
    epoch: 2,
    train_loss: 0.481,
    eval_loss: 0.623,
    tokens_per_second: 28.4,
    eval_tokens_per_second: 52.1,
    best_eval_loss: 0.623,
    gpu_hours: 4.2,
  },
  evaluation: {},
  artifactId: null,
  error: null,
  logPath: "/tmp/training/logs/job-qwen-nl-sft/worker.log",
  traceId: "trace-1",
  seed: 42,
  configHash: "abc123",
  environment: {},
  createdAt: "2025-06-02T08:00:00",
  startedAt: "2025-06-02T08:05:00",
  updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
  finishedAt: null,
  truth: { no_fabricated_metrics: true },
};

const JOB_QUEUED = {
  ...JOB_RUNNING,
  jobId: "job-llama-lora",
  name: "llama-3.2-nl-lora",
  status: "queued",
  phase: null,
  method: "lora",
  baseModelRef: "meta-llama/Llama-3.2-3B",
  datasetVersionId: "ver-sharegpt-v1",
  progress: 0,
  workerPid: null,
  metricsSummary: {},
  startedAt: null,
  createdAt: "2025-06-02T09:40:00",
  updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
};

const JOB_DONE = {
  ...JOB_RUNNING,
  jobId: "job-mistral-done",
  name: "mistral-nl-sft",
  status: "completed",
  phase: "done",
  method: "sft",
  baseModelRef: "mistralai/Mistral-7B-v0.3",
  datasetVersionId: "ver-orca-v1",
  progress: 1,
  workerPid: null,
  metricsSummary: {
    epoch: 3,
    train_loss: 0.312,
    eval_loss: 0.401,
    best_eval_loss: 0.401,
    gpu_hours: 6.1,
  },
  startedAt: "2025-06-01T10:00:00",
  finishedAt: "2025-06-01T16:12:00",
  createdAt: "2025-06-01T09:50:00",
  updatedAt: "2025-06-01T16:12:00",
};

const JOB_FAILED = {
  ...JOB_RUNNING,
  jobId: "job-failed",
  name: "qwen-qlora-oom",
  status: "failed",
  phase: "train",
  method: "qlora",
  baseModelRef: "Qwen/Qwen2.5-14B",
  progress: 0.12,
  error: "CUDA OOM",
  metricsSummary: { train_loss: 1.82, gpu_hours: 0.4 },
  startedAt: "2025-05-30T12:00:00",
  finishedAt: "2025-05-30T12:24:00",
  createdAt: "2025-05-30T11:55:00",
  updatedAt: "2025-05-30T12:24:00",
};

const JOBS = [JOB_RUNNING, JOB_QUEUED, JOB_DONE, JOB_FAILED, {
  ...JOB_DONE,
  jobId: "job-done-2",
  name: "llama-sft-v2",
  metricsSummary: { best_eval_loss: 0.455, gpu_hours: 3.2, eval_loss: 0.455 },
}, {
  ...JOB_DONE,
  jobId: "job-done-3",
  name: "mistral-lora-v1",
  method: "lora",
  metricsSummary: { best_eval_loss: 0.512, gpu_hours: 2.8, eval_loss: 0.512 },
}, {
  ...JOB_RUNNING,
  jobId: "job-running-2",
  name: "qwen-dpo",
  status: "running",
  method: "dpo",
  progress: 0.22,
  metricsSummary: { train_loss: 0.91, tokens_per_second: 18.2, gpu_hours: 1.1 },
}];

function buildMetrics(jobId: string) {
  const points: Array<Record<string, unknown>> = [];
  const losses = [1.82, 1.41, 1.12, 0.91, 0.74, 0.62, 0.55, 0.51, 0.49, 0.481];
  const evals = [1.95, 1.55, 1.28, 1.05, 0.88, 0.76, 0.69, 0.66, 0.64, 0.623];
  losses.forEach((v, i) => {
    points.push({
      id: i * 3 + 1,
      jobId,
      step: (i + 1) * 50,
      epoch: i < 5 ? 1 : 2,
      metricName: "train_loss",
      metricValue: v,
      recordedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      metadata: {},
    });
    points.push({
      id: i * 3 + 2,
      jobId,
      step: (i + 1) * 50,
      epoch: i < 5 ? 1 : 2,
      metricName: "eval_loss",
      metricValue: evals[i],
      recordedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      metadata: {},
    });
    points.push({
      id: i * 3 + 3,
      jobId,
      step: (i + 1) * 50,
      epoch: i < 5 ? 1 : 2,
      metricName: "tokens_per_second",
      metricValue: 24 + i * 0.4,
      recordedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
      metadata: {},
    });
  });
  points.push({
    id: 999,
    jobId,
    step: 500,
    epoch: 2,
    metricName: "epoch",
    metricValue: 2,
    recordedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
    metadata: {},
  });
  points.push({
    id: 1000,
    jobId,
    step: 500,
    epoch: 2,
    metricName: "eval_tokens_per_second",
    metricValue: 52.1,
    recordedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
    metadata: {},
  });
  return points;
}

const CHECKPOINTS = {
  checkpoints: [
    {
      checkpointId: "ckpt-1",
      jobId: "job-qwen-nl-sft",
      step: 200,
      epoch: 1,
      path: "/tmp/training/job-qwen-nl-sft/checkpoint-epoch-1",
      contentHash: "h1",
      metrics: { eval_loss: 0.76 },
      createdAt: "2025-06-02T09:10:00",
      metadata: { byteSize: gib(2.1) },
    },
    {
      checkpointId: "ckpt-2",
      jobId: "job-qwen-nl-sft",
      step: 400,
      epoch: 2,
      path: "/tmp/training/job-qwen-nl-sft/checkpoint-epoch-2",
      contentHash: "h2",
      metrics: { eval_loss: 0.623 },
      createdAt: "2025-06-02T10:00:00",
      metadata: { byteSize: gib(2.1) },
    },
  ],
};

export const TRAINING_V2_VISUAL_FIXTURE = {
  health: { ok: true, llm: { available: true }, database: "ok" },
  capabilities: CAPABILITIES,
  hardware: HARDWARE,
  datasets: DATASETS,
  versions: VERSIONS,
  models: MODELS,
  jobs: JOBS,
  metrics: buildMetrics("job-qwen-nl-sft"),
  checkpoints: CHECKPOINTS,
  logs: {
    jobId: "job-qwen-nl-sft",
    logPath: "/tmp/training/logs/job-qwen-nl-sft/worker.log",
    text: "step 500 loss=0.481\n",
    events: [],
  },
  preflight: {
    verdict: "PASS",
    issues: [],
    details: {},
  },
  plan: {
    strategy: "single_gpu",
    reason: `selected ${STABLE_RTX}`,
    effectiveBatchSize: 4,
    trainBatchSize: 4,
    gradientAccumulation: 1,
    maxSeqLength: 2048,
    precision: "bf16",
    gradientCheckpointing: true,
    loadIn4bit: false,
    warnings: [],
    estimated: true,
    selectedDevice: { stableDeviceId: STABLE_RTX, name: "RTX 3060 Ti" },
    memoryEstimate: { totalBytes: gib(11.2) },
  },
  telemetry: {
    truth: { measured: true },
    memory: { available: true, usedBytes: gib(6.2), totalBytes: gib(16), utilizationPct: 39 },
    gpu: {
      available: true,
      devices: [
        { name: "GTX 1060", utilizationPct: 70, vramUsedBytes: gib(4.2), vramTotalBytes: gib(6) },
        { name: "RTX 3060 Ti", utilizationPct: 43, vramUsedBytes: gib(6.8), vramTotalBytes: gib(16) },
      ],
    },
  },
};

export type TrainingV2VisualFixture = typeof TRAINING_V2_VISUAL_FIXTURE;
