/**
 * Training V2 workspace orchestration.
 *
 * ONE data owner for `/training`: capabilities, hardware, datasets, trainable
 * models, draft config, jobs, metrics, checkpoints, preflight/plan.
 * Real APIs only — no production mock fallback. Screen 1 fixture values live
 * exclusively in `mocks/trainingV2VisualFixture.ts` (Playwright route stubs).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useAppToast } from "../state/useAppToast";
import {
  ACTIVE_TRAINING_STATUSES,
  PRODUCTION_TRAINING_METHODS,
  RESUMABLE_TRAINING_STATUSES,
} from "../training/constants";
import type {
  DatasetRecord,
  DatasetVersion,
  HardwareSnapshot,
  ModelDescriptor,
  PreflightResult,
  TrainingCapabilities,
  TrainingCheckpoint,
  TrainingJob,
  TrainingJobCreatePayload,
  TrainingLogs,
  TrainingMetric,
  TrainingPlan,
} from "../types/api";

const POLL_MS = 3000;
const GIB = 1024 ** 3;

export type TrainingDraft = {
  name: string;
  method: string;
  baseModelRef: string;
  datasetVersionId: string;
  datasetPath: string;
  epochs: number;
  trainBatchSize: number;
  evalBatchSize: number;
  gradientAccumulation: number;
  learningRate: number;
  warmupSteps: number;
  weightDecay: number;
  maxSeqLength: number;
  precision: string;
  loraR: number;
  loraAlpha: number;
  loraDropout: number;
  gradientCheckpointing: boolean;
  loadIn4bit: boolean;
  flashAttention: boolean;
  evalDuringTraining: boolean;
  autoSave: boolean;
  saveSteps: number;
  optimizer: string;
  lrSchedulerType: string;
  deviceStrategy: string;
  selectedStableDeviceId: string | null;
  seed: number;
};

export type TrainingStats = {
  active: number;
  queued: number;
  completed: number;
  failed: number;
  totalTrainingHours: number | null;
  bestEvalLoss: number | null;
  totalComputeHours: number | null;
};

export type MetricsChartMode = "loss" | "perplexity";

const DEFAULT_DRAFT: TrainingDraft = {
  name: "training-run",
  method: "lora",
  baseModelRef: "",
  datasetVersionId: "",
  datasetPath: "",
  epochs: 3,
  trainBatchSize: 4,
  evalBatchSize: 4,
  gradientAccumulation: 1,
  learningRate: 2e-5,
  warmupSteps: 100,
  weightDecay: 0.01,
  maxSeqLength: 2048,
  precision: "bf16",
  loraR: 16,
  loraAlpha: 32,
  loraDropout: 0.05,
  gradientCheckpointing: true,
  loadIn4bit: false,
  flashAttention: false,
  evalDuringTraining: true,
  autoSave: true,
  saveSteps: 50,
  optimizer: "adamw_torch",
  lrSchedulerType: "cosine",
  deviceStrategy: "auto",
  selectedStableDeviceId: null,
  seed: 42,
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null) return "—";
  if (bytes < GIB) return `${(bytes / 1024 ** 2).toFixed(digits)} MB`;
  return `${(bytes / GIB).toFixed(digits)} GB`;
}

/** GGUF and similar quantized inference blobs are not trainable base weights. */
export function isTrainableModel(model: ModelDescriptor): boolean {
  const format = (model.format || "").toLowerCase();
  if (format.includes("gguf")) return false;
  const source = (model.source || "").toLowerCase();
  if (source === "gguf") return false;
  const tags = (model.tags || []).map((t) => t.toLowerCase());
  if (tags.some((t) => t === "gguf" || t.includes("gguf"))) return false;
  const id = (model.id || "").toLowerCase();
  const name = (model.displayName || "").toLowerCase();
  if (id.endsWith(".gguf") || name.endsWith(".gguf")) return false;
  return true;
}

export function perplexityFromLoss(loss: number | null | undefined): number | null {
  if (loss == null || !Number.isFinite(loss)) return null;
  // Clamp extreme losses so exp() stays finite for display.
  const clamped = Math.max(-20, Math.min(20, loss));
  return Math.exp(clamped);
}

export function latestMetric(
  metrics: TrainingMetric[],
  names: string[],
): TrainingMetric | null {
  const wanted = new Set(names.map((n) => n.toLowerCase()));
  const matches = metrics
    .filter((m) => wanted.has(m.metricName.toLowerCase()))
    .sort(
      (a, b) =>
        (b.step ?? 0) - (a.step ?? 0) ||
        b.recordedAt.localeCompare(a.recordedAt),
    );
  return matches[0] ?? null;
}

export function metricSeries(metrics: TrainingMetric[], names: string[]): number[] {
  const wanted = new Set(names.map((n) => n.toLowerCase()));
  return metrics
    .filter((m) => wanted.has(m.metricName.toLowerCase()))
    .sort(
      (a, b) =>
        (a.step ?? 0) - (b.step ?? 0) ||
        a.recordedAt.localeCompare(b.recordedAt),
    )
    .map((m) => m.metricValue);
}

function durationHours(startedAt?: string | null, finishedAt?: string | null): number | null {
  if (!startedAt) return null;
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return null;
  const end = finishedAt ? Date.parse(finishedAt) : visualNowMs();
  if (Number.isNaN(end) || end < start) return null;
  return (end - start) / 3_600_000;
}

/** Prefer Playwright frozen clock when present so visual fixtures stay honest. */
export function visualNowMs(): number {
  if (typeof window !== "undefined") {
    const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
    if (frozen) {
      const t = Date.parse(frozen);
      if (!Number.isNaN(t)) return t;
    }
  }
  return Date.now();
}

function summaryNumber(summary: Record<string, unknown> | undefined, keys: string[]): number | null {
  if (!summary) return null;
  for (const key of keys) {
    const v = summary[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

export type TrainingWorkspace = {
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  error: string | null;
  online: boolean | null;
  sidebarStatus: SidebarStatusRow[];
  busy: boolean;

  capabilities: TrainingCapabilities | null;
  hardware: HardwareSnapshot | null;
  capsError: string | null;
  hwError: string | null;

  datasets: DatasetRecord[];
  datasetVersions: DatasetVersion[];
  selectedDatasetId: string | null;
  selectDataset: (datasetId: string | null) => void;
  selectedVersionId: string | null;
  selectVersion: (versionId: string | null) => void;
  loadDatasetVersions: (datasetId: string) => Promise<void>;

  models: ModelDescriptor[];
  trainableModels: ModelDescriptor[];
  modelQuery: string;
  setModelQuery: (q: string) => void;
  selectedModelId: string | null;
  selectModel: (id: string | null) => void;

  draft: TrainingDraft;
  setDraft: (patch: Partial<TrainingDraft>) => void;
  resetDraft: () => void;
  createPayload: TrainingJobCreatePayload;

  jobs: TrainingJob[];
  selectedJobId: string | null;
  selectedJob: TrainingJob | null;
  selectJob: (jobId: string | null) => void;
  stats: TrainingStats;

  metrics: TrainingMetric[];
  logs: TrainingLogs | null;
  checkpoints: TrainingCheckpoint[];
  chartMode: MetricsChartMode;
  setChartMode: (mode: MetricsChartMode) => void;

  preflight: PreflightResult | null;
  plan: TrainingPlan | null;
  preflightOpen: boolean;
  setPreflightOpen: (open: boolean) => void;
  runPreflight: () => Promise<void>;
  createJob: (autoStart: boolean) => Promise<void>;
  startJob: (jobId: string) => Promise<void>;
  cancelJob: (jobId: string) => Promise<void>;
  resumeJob: (jobId: string) => Promise<void>;
  evaluateJob: (jobId: string) => Promise<void>;
  exportJob: (jobId: string) => Promise<void>;
  openNewTraining: () => void;

  methodDisabledReason: (method: string) => string | null;
  formatBytes: typeof formatBytes;
};

export function useTrainingWorkspace(): TrainingWorkspace {
  const toast = useAppToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [capabilities, setCapabilities] = useState<TrainingCapabilities | null>(null);
  const [hardware, setHardware] = useState<HardwareSnapshot | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [hwError, setHwError] = useState<string | null>(null);

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [datasetVersions, setDatasetVersions] = useState<DatasetVersion[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [modelQuery, setModelQuery] = useState("");
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);

  const [draft, setDraftState] = useState<TrainingDraft>(DEFAULT_DRAFT);

  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<TrainingMetric[]>([]);
  const [logs, setLogs] = useState<TrainingLogs | null>(null);
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpoint[]>([]);
  const [chartMode, setChartMode] = useState<MetricsChartMode>("loss");

  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);
  const [preflightOpen, setPreflightOpen] = useState(false);

  const setDraft = useCallback((patch: Partial<TrainingDraft>) => {
    setDraftState((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetDraft = useCallback(() => {
    setDraftState(DEFAULT_DRAFT);
    setPreflight(null);
    setPlan(null);
  }, []);

  const trainableModels = useMemo(() => models.filter(isTrainableModel), [models]);

  const filteredTrainable = useMemo(() => {
    const q = modelQuery.trim().toLowerCase();
    if (!q) return trainableModels;
    return trainableModels.filter((m) =>
      [m.id, m.displayName, m.family ?? "", m.architecture ?? "", ...(m.tags ?? [])]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [trainableModels, modelQuery]);

  const selectedJob = useMemo(
    () => jobs.find((j) => j.jobId === selectedJobId) ?? null,
    [jobs, selectedJobId],
  );

  const createPayload = useMemo((): TrainingJobCreatePayload => {
    const method = draft.method;
    const deviceIds =
      draft.deviceStrategy === "single" && draft.selectedStableDeviceId
        ? [draft.selectedStableDeviceId]
        : [];
    return {
      name: draft.name.trim() || "training-run",
      method,
      base_model_ref: draft.baseModelRef.trim() || selectedModelId || "unspecified",
      dataset_version_id: draft.datasetVersionId.trim() || selectedVersionId || null,
      dataset_path: draft.datasetPath.trim() || null,
      seed: draft.seed,
      epochs: draft.epochs,
      train_batch_size: draft.trainBatchSize,
      eval_batch_size: draft.evalBatchSize,
      gradient_accumulation: draft.gradientAccumulation,
      learning_rate: draft.learningRate,
      warmup_steps: draft.warmupSteps,
      weight_decay: draft.weightDecay,
      max_seq_length: draft.maxSeqLength,
      precision: draft.precision,
      lora_r: draft.loraR,
      lora_alpha: draft.loraAlpha,
      lora_dropout: draft.loraDropout,
      gradient_checkpointing: draft.gradientCheckpointing,
      load_in_4bit: method === "qlora" ? true : draft.loadIn4bit,
      save_steps: draft.autoSave ? draft.saveSteps : draft.saveSteps,
      device_strategy: draft.deviceStrategy,
      selected_stable_device_ids: deviceIds,
      optimizer: draft.optimizer,
      lr_scheduler_type: draft.lrSchedulerType,
      flash_attention: draft.flashAttention,
      eval_during_training: draft.evalDuringTraining,
      save_total_limit: draft.autoSave ? 3 : null,
    };
  }, [draft, selectedModelId, selectedVersionId]);

  const stats = useMemo((): TrainingStats => {
    let active = 0;
    let queued = 0;
    let completed = 0;
    let failed = 0;
    let hours = 0;
    let hoursKnown = false;
    let bestEvalLoss: number | null = null;
    let computeHours: number | null = null;

    for (const job of jobs) {
      if (ACTIVE_TRAINING_STATUSES.has(job.status)) {
        if (job.status === "queued" || job.status === "preflight") queued += 1;
        else active += 1;
      }
      if (job.status === "completed") completed += 1;
      if (job.status === "failed") failed += 1;

      const dh = durationHours(job.startedAt, job.finishedAt);
      if (dh != null) {
        hours += dh;
        hoursKnown = true;
      }

      const evalLoss = summaryNumber(job.metricsSummary, [
        "eval_loss",
        "evalLoss",
        "best_eval_loss",
        "bestEvalLoss",
        "val_loss",
        "valLoss",
      ]);
      if (evalLoss != null && (bestEvalLoss == null || evalLoss < bestEvalLoss)) {
        bestEvalLoss = evalLoss;
      }

      const gpuHours = summaryNumber(job.metricsSummary, [
        "gpu_hours",
        "gpuHours",
        "compute_hours",
        "computeHours",
      ]);
      if (gpuHours != null) {
        computeHours = (computeHours ?? 0) + gpuHours;
      }
    }

    return {
      active,
      queued,
      completed,
      failed,
      totalTrainingHours: hoursKnown ? Math.round(hours * 10) / 10 : null,
      bestEvalLoss,
      totalComputeHours: computeHours != null ? Math.round(computeHours * 10) / 10 : null,
    };
  }, [jobs]);

  const methodDisabledReason = useCallback(
    (method: string): string | null => {
      if (!capabilities) return capsError ?? "Capabilities not loaded";
      if (method === "fixture") return "Fixture is not a production training method";
      const support = capabilities.methodSupport?.[method];
      if (support && support.operational === false) {
        const missing = support.missingPackages?.join(", ");
        return (
          support.reasons?.[0] ||
          (missing ? `Missing: ${missing}` : `${method.toUpperCase()} unavailable`)
        );
      }
      if (method === "sft" && capabilities.canRunSft === false) {
        return `SFT unavailable — missing: ${(capabilities.missingForSft || []).join(", ") || "deps"}`;
      }
      if (method === "lora" && !capabilities.canRunLora) {
        return `LoRA unavailable — missing: ${capabilities.missingForLora.join(", ") || "deps"}`;
      }
      if (method === "qlora" && !capabilities.canRunQlora) {
        return `QLoRA unavailable — missing: ${(capabilities.missingForQlora || []).join(", ") || "deps"}`;
      }
      if (method === "dpo" && !capabilities.canRunDpo) {
        return `DPO unavailable — missing: ${(capabilities.missingForDpo || []).join(", ") || "deps"}`;
      }
      if (!(PRODUCTION_TRAINING_METHODS as readonly string[]).includes(method)) {
        return "Unsupported method";
      }
      return null;
    },
    [capabilities, capsError],
  );

  const loadDatasetVersions = useCallback(async (datasetId: string) => {
    try {
      const res = await api.listDatasetVersions(datasetId);
      setDatasetVersions(res.versions);
      const preferred =
        res.versions.find((v) => v.status === "ready" || v.status === "published") ??
        res.versions[0] ??
        null;
      setSelectedVersionId(preferred?.versionId ?? null);
      if (preferred) {
        setDraftState((prev) => ({ ...prev, datasetVersionId: preferred.versionId }));
      }
    } catch {
      setDatasetVersions([]);
      setSelectedVersionId(null);
    }
  }, []);

  const selectDataset = useCallback(
    (datasetId: string | null) => {
      setSelectedDatasetId(datasetId);
      if (datasetId) void loadDatasetVersions(datasetId);
      else {
        setDatasetVersions([]);
        setSelectedVersionId(null);
        setDraftState((prev) => ({ ...prev, datasetVersionId: "" }));
      }
    },
    [loadDatasetVersions],
  );

  const selectVersion = useCallback((versionId: string | null) => {
    setSelectedVersionId(versionId);
    setDraftState((prev) => ({ ...prev, datasetVersionId: versionId ?? "" }));
  }, []);

  const selectModel = useCallback((id: string | null) => {
    setSelectedModelId(id);
    if (id) setDraftState((prev) => ({ ...prev, baseModelRef: id }));
  }, []);

  const loadAll = useCallback(async () => {
    setError(null);
    setCapsError(null);
    setHwError(null);

    const [capsRes, hwRes, jobsRes, datasetsRes, modelsRes] = await Promise.allSettled([
      api.trainingCapabilities(),
      api.trainingHardware(),
      api.listTrainingJobs(),
      api.listDatasets(100),
      api.listModels(),
    ]);

    if (capsRes.status === "fulfilled") {
      setCapabilities(capsRes.value.capabilities);
      const caps = capsRes.value.capabilities;
      const production =
        caps.productionMethods?.filter(Boolean) ??
        PRODUCTION_TRAINING_METHODS.filter((m) => {
          if (m === "sft") return caps.canRunSft !== false;
          if (m === "lora") return caps.canRunLora;
          if (m === "qlora") return caps.canRunQlora;
          if (m === "dpo") return caps.canRunDpo;
          return false;
        });
      setDraftState((prev) => {
        if (production.includes(prev.method as (typeof PRODUCTION_TRAINING_METHODS)[number])) {
          return prev;
        }
        const nextMethod = production[0] ?? "lora";
        return { ...prev, method: nextMethod, loadIn4bit: nextMethod === "qlora" };
      });
    } else {
      setCapabilities(null);
      setCapsError(errMsg(capsRes.reason, "Training capabilities unavailable"));
    }

    if (hwRes.status === "fulfilled") {
      setHardware(hwRes.value.hardware);
      const firstGpu = hwRes.value.hardware.gpus?.[0];
      const stableId = firstGpu?.stableDeviceId || (firstGpu ? `gpu-${firstGpu.index}` : null);
      if (stableId) {
        setDraftState((prev) =>
          prev.selectedStableDeviceId ? prev : { ...prev, selectedStableDeviceId: stableId },
        );
      }
    } else {
      setHardware(null);
      setHwError(errMsg(hwRes.reason, "Hardware probe unavailable"));
    }

    if (jobsRes.status === "fulfilled") {
      const list = jobsRes.value.jobs;
      setJobs(list);
      setSelectedJobId((prev) => {
        if (prev && list.some((j) => j.jobId === prev)) return prev;
        const running = list.find((j) => ACTIVE_TRAINING_STATUSES.has(j.status));
        return running?.jobId ?? list[0]?.jobId ?? null;
      });
    } else {
      setJobs([]);
      setError(errMsg(jobsRes.reason, "Failed to load training jobs"));
    }

    if (datasetsRes.status === "fulfilled") {
      const list = datasetsRes.value.datasets;
      setDatasets(list);
      setSelectedDatasetId((prev) => {
        if (prev && list.some((d) => d.datasetId === prev)) return prev;
        return list[0]?.datasetId ?? null;
      });
    } else {
      setDatasets([]);
    }

    if (modelsRes.status === "fulfilled") {
      const list = modelsRes.value.models;
      setModels(list);
      const trainable = list.filter(isTrainableModel);
      setSelectedModelId((prev) => {
        if (prev && trainable.some((m) => m.id === prev)) return prev;
        const pick = trainable[0]?.id ?? null;
        if (pick) {
          setDraftState((d) => (d.baseModelRef ? d : { ...d, baseModelRef: pick }));
        }
        return pick;
      });
    } else {
      setModels([]);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      await loadAll();
      setLoading(false);
    })();
  }, [loadAll]);

  useEffect(() => {
    if (!selectedDatasetId) return;
    void loadDatasetVersions(selectedDatasetId);
  }, [selectedDatasetId, loadDatasetVersions]);

  useEffect(() => {
    if (!selectedJobId) {
      setMetrics([]);
      setLogs(null);
      setCheckpoints([]);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const [m, l, c, jobRes] = await Promise.all([
          api.listTrainingMetrics(selectedJobId),
          api.getTrainingLogs(selectedJobId),
          api.listTrainingCheckpoints(selectedJobId),
          api.getTrainingJob(selectedJobId),
        ]);
        if (cancelled) return;
        setMetrics(m.metrics);
        setLogs(l);
        setCheckpoints(c.checkpoints);
        setJobs((prev) => {
          const others = prev.filter((j) => j.jobId !== selectedJobId);
          return [jobRes.job, ...others].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
        });
      } catch {
        /* keep last good snapshot */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [selectedJobId]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadAll();
    } finally {
      setRefreshing(false);
    }
  }, [loadAll]);

  async function withBusy(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok);
    } catch (err) {
      toast(errMsg(err, "Action failed"));
    } finally {
      setBusy(false);
    }
  }

  const runPreflight = useCallback(async () => {
    await withBusy(async () => {
      const [pf, pl] = await Promise.all([
        api.trainingPreflight(createPayload),
        api.trainingPlan(createPayload),
      ]);
      setPreflight(pf.preflight);
      setPlan(pl.plan);
      setPreflightOpen(true);
    }, "Preflight complete");
  }, [createPayload]); // eslint-disable-line react-hooks/exhaustive-deps

  const createJob = useCallback(
    async (autoStart: boolean) => {
      if (preflight?.verdict === "BLOCKED") {
        toast("Preflight blocked — fix issues before starting");
        setPreflightOpen(true);
        return;
      }
      await withBusy(async () => {
        let verdict = preflight?.verdict;
        if (!preflight) {
          const pf = await api.trainingPreflight(createPayload);
          setPreflight(pf.preflight);
          verdict = pf.preflight.verdict;
          if (verdict === "BLOCKED") {
            setPreflightOpen(true);
            throw new ApiError(400, "Preflight blocked — cannot start");
          }
        }
        const res = await api.createTrainingJob({ ...createPayload, auto_start: autoStart });
        setSelectedJobId(res.job.jobId);
        setPreflightOpen(false);
        await loadAll();
      }, autoStart ? "Training gestart" : "Job aangemaakt");
    },
    [createPayload, preflight, loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const startJob = useCallback(
    async (jobId: string) => {
      await withBusy(async () => {
        await api.startTrainingJob(jobId);
        await loadAll();
      }, "Training gestart");
    },
    [loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const cancelJob = useCallback(
    async (jobId: string) => {
      await withBusy(async () => {
        await api.cancelTrainingJob(jobId);
        await loadAll();
      }, "Stop aangevraagd");
    },
    [loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const resumeJob = useCallback(
    async (jobId: string) => {
      await withBusy(async () => {
        await api.resumeTrainingJob(jobId);
        await loadAll();
      }, "Training hervat");
    },
    [loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const evaluateJob = useCallback(
    async (jobId: string) => {
      await withBusy(async () => {
        await api.evaluateTrainingJob(jobId);
        await loadAll();
      }, "Evaluatie gestart");
    },
    [loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const exportJob = useCallback(
    async (jobId: string) => {
      await withBusy(async () => {
        await api.exportTrainingJob(jobId);
        await loadAll();
      }, "Export gestart");
    },
    [loadAll], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const openNewTraining = useCallback(() => {
    setPreflight(null);
    setPlan(null);
    setPreflightOpen(true);
    void runPreflight();
  }, [runPreflight]);

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const ready = capabilities?.ready === true;
    const rows: SidebarStatusRow[] = [
      {
        id: "trainer",
        label: "Leviathan Trainer",
        value: ready ? "Ready" : capabilities ? "Deps missing" : loading ? "…" : "UNMEASURED",
        tone: ready ? "success" : capabilities ? "warning" : "muted",
      },
    ];
    const gpus = hardware?.gpus ?? [];
    if (gpus.length) {
      gpus.slice(0, 2).forEach((g, i) => {
        rows.push({
          id: `gpu-${i}`,
          label: `GPU ${g.index} - ${g.name || "GPU"}`,
          value: hardware?.cudaAvailable ? "Ready" : "No CUDA",
          tone: hardware?.cudaAvailable ? "success" : "warning",
        });
      });
    } else {
      rows.push({
        id: "gpu",
        label: "GPU",
        value: hardware ? "UNAVAILABLE" : loading ? "…" : "UNMEASURED",
        tone: "muted",
      });
    }
    const ramUsed =
      hardware?.ramTotalBytes != null && hardware.ramAvailableBytes != null
        ? hardware.ramTotalBytes - hardware.ramAvailableBytes
        : null;
    rows.push({
      id: "ram",
      label: "RAM",
      value:
        ramUsed != null && hardware?.ramTotalBytes != null
          ? `${(ramUsed / GIB).toFixed(1)} / ${(hardware.ramTotalBytes / GIB).toFixed(0)} GB`
          : hardware
            ? "UNMEASURED"
            : "…",
      tone: "muted",
    });
    const vramUsed = gpus.reduce((s, g) => s + (g.usedVramBytes ?? 0), 0);
    const vramTotal = gpus.reduce((s, g) => s + (g.totalVramBytes ?? 0), 0);
    rows.push({
      id: "vram",
      label: "VRAM Totaal",
      value:
        gpus.length && vramTotal > 0
          ? `${(vramUsed / GIB).toFixed(1)} / ${(vramTotal / GIB).toFixed(0)} GB`
          : hardware
            ? "UNMEASURED"
            : "…",
      tone: "muted",
    });
    return rows;
  }, [capabilities, hardware, loading]);

  const online: boolean | null =
    capabilities?.ready === true ? true : capabilities != null ? false : null;

  return {
    loading,
    refreshing,
    refresh,
    error,
    online,
    sidebarStatus,
    busy,

    capabilities,
    hardware,
    capsError,
    hwError,

    datasets,
    datasetVersions,
    selectedDatasetId,
    selectDataset,
    selectedVersionId,
    selectVersion,
    loadDatasetVersions,

    models,
    trainableModels: filteredTrainable,
    modelQuery,
    setModelQuery,
    selectedModelId,
    selectModel,

    draft,
    setDraft,
    resetDraft,
    createPayload,

    jobs,
    selectedJobId,
    selectedJob,
    selectJob: setSelectedJobId,
    stats,

    metrics,
    logs,
    checkpoints,
    chartMode,
    setChartMode,

    preflight,
    plan,
    preflightOpen,
    setPreflightOpen,
    runPreflight,
    createJob,
    startJob,
    cancelJob,
    resumeJob,
    evaluateJob,
    exportJob,
    openNewTraining,

    methodDisabledReason,
    formatBytes,
  };
}

export { formatBytes, ACTIVE_TRAINING_STATUSES, RESUMABLE_TRAINING_STATUSES };
