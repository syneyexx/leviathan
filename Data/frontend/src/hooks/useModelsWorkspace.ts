/**
 * Models V2 workspace orchestration (LM Studio control plane).
 *
 * Owns model catalog, hardware inventory, draft load configuration (sliders
 * never auto-load — the user must press "Model laden"), provider capability
 * gating, resource estimation, the bounded optimizer, and VRAM reserve
 * policy. Mirrors the Research V2 workspace hook pattern: one hook, real
 * APIs only, no invented production numbers (Screen 1 fixture values live
 * exclusively in `mocks/modelsV2VisualFixture.ts`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useAppToast } from "../state/useAppToast";
import type {
  CapabilitySupportValue,
  GatewaySnapshot,
  ModelDescriptor,
  ModelEstimateResult,
  ModelHardwareInventory,
  ModelLoadOptions,
  ModelOptimizationCandidate,
  ModelOptimizationRun,
  ModelProvider,
  ModelResidency,
  ModelRuntimeBinding,
  ModelsStatus,
  ProviderCapabilityField,
  ProviderControlCapabilities,
  ResidencyPolicy,
  RouterConfig,
} from "../types/api";

const OPTIMIZE_POLL_MS = 1500;
const JOB_POLL_MS = 750;
const JOB_POLL_TIMEOUT_MS = 30 * 60 * 1000;
const RUNNING_OPTIMIZATION_STATUSES = new Set(["PENDING", "RUNNING"]);
const TERMINAL_JOB_STATES = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "COMPLETED",
  "SUCCESS",
  "ERROR",
]);

/** Map UI / legacy capability keys → backend field-matrix keys. */
const CAP_KEY_ALIASES: Record<string, string[]> = {
  contextLength: ["contextLength"],
  evalBatch: ["evalBatchSize", "evalBatch", "batchSize"],
  evalBatchSize: ["evalBatchSize", "evalBatch"],
  flashAttention: ["flashAttention"],
  kvGpuOffload: ["offloadKvCacheToGpu", "kvGpuOffload"],
  moeNumExperts: ["numExperts", "moeNumExperts"],
  gpuRatio: ["gpuOffloadRatio", "gpuRatio"],
  gpuOffloadRatio: ["gpuOffloadRatio", "gpuRatio"],
  gpuSplit: ["gpuSplitMode", "gpuSplit"],
  gpuSplitMode: ["gpuSplitMode", "gpuSplit"],
  customGpuSplit: ["tensorSplit", "customGpuSplit"],
  tensorSplit: ["tensorSplit", "customGpuSplit"],
  mainGpu: ["mainGpuOrdinal", "mainGpu"],
  mainGpuOrdinal: ["mainGpuOrdinal", "mainGpu"],
  kvQuantization: ["kvCacheDtype", "kvQuantization"],
  kvCacheDtype: ["kvCacheDtype", "kvQuantization"],
  continuousBatching: ["continuousBatching"],
  prefixCache: ["prefixCache"],
  speculativeDecoding: ["speculativeDecoding"],
  draftModel: ["draftModelId", "draftModel"],
  draftModelId: ["draftModelId", "draftModel"],
  speculativeTokens: ["speculativeTokens"],
  cpuThreads: ["cpuThreads"],
  seed: ["seed"],
  shardingMode: ["shardingMode", "gpuSplitMode"],
  keepDisplayHeadroom: ["keepDisplayHeadroom"],
  tensorParallelSize: ["tensorParallelSize"],
};

const REASON_NL: Record<string, string> = {
  SDK_REQUIRED: "Vereist LM Studio SDK (niet geïnstalleerd of niet bereikbaar)",
  SDK_OR_CLI_REQUIRED: "Vereist lms CLI of LM Studio SDK",
  SDK_SPLIT_STRATEGY_ONLY:
    "Alleen Auto/evenly/favorMainGpu — geen willekeurige per-GPU percentages",
  INFERENCE_ONLY_SETTING: "Inferentie-instelling (niet bij model laden)",
  PROVIDER_VERSION_UNSUPPORTED: "Niet beschikbaar via de verbonden LM Studio-versie",
  UNSUPPORTED: "Niet ondersteund door deze provider",
  NATIVE_API_UNAVAILABLE: "Native LM Studio REST-API niet bereikbaar",
};

export type GpuAllocationDraft = Record<string, number>;

export type ModelsLoadDraft = {
  contextLength: number;
  evalBatchSize: number;
  gpuOffloadRatio: number;
  flashAttention: boolean;
  offloadKvCacheToGpu: boolean;
  numExperts: number | null;
  cpuThreads: number | null;
  seed: number | null;
  gpuSplitMode: string;
  gpuAllocation: GpuAllocationDraft;
  keepDisplayHeadroom: boolean;
  kvCacheDtype: string;
  tensorParallelSize: number;
  mainGpuOrdinal: number | null;
  shardingMode: string;
  continuousBatching: boolean;
  prefixCache: boolean;
  speculativeDecoding: boolean;
  draftModelId: string | null;
  speculativeTokens: number;
};

export type OptimizationGoals = {
  maxTokensPerSec: boolean;
  keepDisplayResponsive: boolean;
  maximizeModelSize: boolean;
  stableNoOom: boolean;
};

export type VramReserveDraft = {
  displayGpuReserveGb: number;
  auxGpuReserveGb: number;
  systemRamReserveGb: number;
};

export type ModelsDrawer = "providers" | "gateway" | "router" | "residency" | null;

const DEFAULT_DRAFT: ModelsLoadDraft = {
  contextLength: 8192,
  evalBatchSize: 256,
  gpuOffloadRatio: 0.8,
  flashAttention: true,
  offloadKvCacheToGpu: true,
  numExperts: null,
  cpuThreads: null,
  seed: null,
  gpuSplitMode: "auto",
  gpuAllocation: {},
  keepDisplayHeadroom: true,
  kvCacheDtype: "auto",
  tensorParallelSize: 1,
  mainGpuOrdinal: null,
  shardingMode: "auto",
  continuousBatching: true,
  prefixCache: false,
  speculativeDecoding: false,
  draftModelId: null,
  speculativeTokens: 0,
};

const DEFAULT_GOALS: OptimizationGoals = {
  maxTokensPerSec: true,
  keepDisplayResponsive: true,
  maximizeModelSize: true,
  stableNoOom: true,
};

const DEFAULT_VRAM_RESERVE: VramReserveDraft = {
  displayGpuReserveGb: 0,
  auxGpuReserveGb: 0,
  systemRamReserveGb: 0,
};

const GIB = 1024 ** 3;

function gbToBytes(gb: number): number {
  return Math.round(gb * GIB);
}

function bytesToGb(bytes: number | null | undefined): number {
  if (bytes == null) return 0;
  return Math.round((bytes / GIB) * 100) / 100;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function draftKey(draft: ModelsLoadDraft): string {
  return JSON.stringify(draft);
}

function loadOptionsPayload(draft: ModelsLoadDraft, devices: ModelHardwareInventory["devices"]): Partial<ModelLoadOptions> {
  const orderedIds = [...devices]
    .sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0))
    .map((d) => d.stableDeviceId);
  const manualSplit =
    draft.gpuSplitMode === "manual" && orderedIds.some((id) => draft.gpuAllocation[id] != null);
  const tensorSplit = manualSplit
    ? orderedIds.map((id) => draft.gpuAllocation[id] ?? 0)
    : undefined;

  // Inference-scoped fields (cpuThreads, speculative*) stay out of the load
  // payload — they belong on prediction/runtime profiles, not LM Studio load.
  return {
    contextLength: draft.contextLength,
    batchSize: draft.evalBatchSize,
    flashAttention: draft.flashAttention,
    offloadKvCacheToGpu: draft.offloadKvCacheToGpu,
    numExperts: draft.numExperts,
    gpuOffloadRatio: draft.gpuOffloadRatio,
    gpuSplitMode: draft.gpuSplitMode,
    tensorSplit,
    keepDisplayHeadroom: draft.keepDisplayHeadroom,
    kvCacheDtype: draft.kvCacheDtype === "auto" ? null : draft.kvCacheDtype,
    tensorParallelSize: draft.tensorParallelSize,
    mainGpuOrdinal: draft.mainGpuOrdinal,
    shardingMode: draft.shardingMode === "auto" ? null : draft.shardingMode,
    continuousBatching: draft.continuousBatching,
    prefixCache: draft.prefixCache,
    seed: draft.seed,
    allowMultiGpu: draft.gpuSplitMode !== "single",
  };
}

function draftFromResidencyPolicy(policy: ResidencyPolicy | null | undefined): Partial<ModelsLoadDraft> {
  const lo = policy?.loadOptions;
  if (!lo) return {};
  const patch: Partial<ModelsLoadDraft> = {};
  if (lo.contextLength != null) patch.contextLength = lo.contextLength;
  if (lo.batchSize != null) patch.evalBatchSize = lo.batchSize;
  if (lo.flashAttention != null) patch.flashAttention = lo.flashAttention;
  return patch;
}

export type ModelsWorkspace = {
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  error: string | null;
  online: boolean | null;
  sidebarStatus: SidebarStatusRow[];

  models: ModelDescriptor[];
  filteredModels: ModelDescriptor[];
  query: string;
  setQuery: (q: string) => void;
  status: ModelsStatus | null;

  providers: ModelProvider[];
  activeProvider: ModelProvider | null;
  setActiveProviderId: (id: string) => void;
  providerConnecting: boolean;
  testProviderConnection: () => Promise<void>;

  hardware: ModelHardwareInventory | null;

  selectedId: string | null;
  selectedModel: ModelDescriptor | null;
  selectModel: (id: string | null) => void;

  draft: ModelsLoadDraft;
  setDraft: (patch: Partial<ModelsLoadDraft>) => void;
  setGpuAllocation: (deviceId: string, ratio: number) => void;
  resetDraft: () => void;
  dirty: boolean;

  capabilities: ProviderControlCapabilities | null;
  capabilitiesLoading: boolean;
  capSupport: (key: string) => CapabilitySupportValue;
  capNote: (key: string) => string | null;

  estimate: ModelEstimateResult | null;
  estimating: boolean;
  runEstimate: () => Promise<void>;

  optimization: ModelOptimizationRun | null;
  optimizing: boolean;
  optimizationGoals: OptimizationGoals;
  setOptimizationGoal: (key: keyof OptimizationGoals, value: boolean) => void;
  startOptimize: () => Promise<void>;
  cancelOptimize: () => Promise<void>;
  applyCandidate: (candidate: ModelOptimizationCandidate) => void;

  vramReserveDraft: VramReserveDraft;
  setVramReserveDraft: (patch: Partial<VramReserveDraft>) => void;
  vramReserveDirty: boolean;
  savingVramReserve: boolean;
  saveVramReserve: () => Promise<void>;

  busy: string | null;
  activeJobId: string | null;
  loadSelected: () => Promise<void>;
  unloadSelected: () => Promise<void>;
  stop: () => Promise<void>;
  /** Worker Fabric model_runtime readiness (separate from provider health). */
  modelRuntime: ModelsStatus["modelRuntime"];
  capField: (key: string) => ProviderCapabilityField | null;

  showImport: boolean;
  setShowImport: (v: boolean) => void;

  drawer: ModelsDrawer;
  openDrawer: (name: Exclude<ModelsDrawer, null>) => void;
  closeDrawer: () => void;

  gateway: GatewaySnapshot | null;
  router: RouterConfig | null;
  residency: ModelResidency | null;
  residencyPolicy: ResidencyPolicy | null;
  runtimeBinding: ModelRuntimeBinding | null;
  saveResidencyPolicy: (next: Partial<ResidencyPolicy>) => Promise<void>;
  saveRouter: (next: Partial<RouterConfig>) => Promise<void>;
};

export function useModelsWorkspace(): ModelsWorkspace {
  const toast = useAppToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [activeProviderId, setActiveProviderId] = useState<string>("");
  const [hardware, setHardware] = useState<ModelHardwareInventory | null>(null);
  const [gateway, setGateway] = useState<GatewaySnapshot | null>(null);
  const [router, setRouter] = useState<RouterConfig | null>(null);
  const [query, setQuery] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [residency, setResidency] = useState<ModelResidency | null>(null);
  const [residencyPolicy, setResidencyPolicy] = useState<ResidencyPolicy | null>(null);
  const [runtimeBinding, setRuntimeBinding] = useState<ModelRuntimeBinding | null>(null);

  const [draft, setDraftState] = useState<ModelsLoadDraft>(DEFAULT_DRAFT);
  const [baseline, setBaseline] = useState<ModelsLoadDraft>(DEFAULT_DRAFT);

  const [capabilities, setCapabilities] = useState<ProviderControlCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false);
  const capabilitiesCache = useRef<Map<string, ProviderControlCapabilities>>(new Map());

  const [estimate, setEstimate] = useState<ModelEstimateResult | null>(null);
  const [estimating, setEstimating] = useState(false);

  const [optimization, setOptimization] = useState<ModelOptimizationRun | null>(null);
  const [optimizationGoals, setOptimizationGoals] = useState<OptimizationGoals>(DEFAULT_GOALS);
  const optimizePollRef = useRef<number | null>(null);

  const [vramReserveDraft, setVramReserveDraftState] = useState<VramReserveDraft>(DEFAULT_VRAM_RESERVE);
  const [vramReserveBaseline, setVramReserveBaseline] = useState<VramReserveDraft>(DEFAULT_VRAM_RESERVE);
  const [savingVramReserve, setSavingVramReserve] = useState(false);

  const [busy, setBusy] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [drawer, setDrawer] = useState<ModelsDrawer>(null);
  const [providerConnecting, setProviderConnecting] = useState(false);

  const selectGen = useRef(0);
  const jobPollAbort = useRef(0);

  const selectedModel = useMemo(
    () => models.find((m) => m.id === selectedId) ?? null,
    [models, selectedId],
  );

  const activeProvider = useMemo(
    () => providers.find((p) => p.id === activeProviderId) ?? providers[0] ?? null,
    [providers, activeProviderId],
  );

  const filteredModels = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) =>
      [m.id, m.displayName, m.family ?? "", m.architecture ?? "", m.quantization ?? "", ...(m.tags ?? [])]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [models, query]);

  const dirty = useMemo(() => draftKey(draft) !== draftKey(baseline), [draft, baseline]);
  const vramReserveDirty = useMemo(
    () => JSON.stringify(vramReserveDraft) !== JSON.stringify(vramReserveBaseline),
    [vramReserveDraft, vramReserveBaseline],
  );

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [list, providersRes, hardwareRes, gatewayRes, routerRes] = await Promise.all([
        api.listModels(),
        api.listModelProviders(),
        api.modelsHardware().catch(() => null),
        api.getGateway().catch(() => null),
        api.getRouter().catch(() => null),
      ]);
      setModels(list.models);
      setStatus(list.status);
      setProviders(providersRes.providers);
      if (!activeProviderId && providersRes.providers[0]) {
        setActiveProviderId(providersRes.providers[0].id);
      }
      if (hardwareRes) setHardware(hardwareRes.hardware);
      if (gatewayRes) setGateway(gatewayRes.gateway);
      if (routerRes) setRouter(routerRes.router);
      if (!selectedId && list.models.length > 0) {
        const active = list.models.find((m) => m.active || m.loaded) ?? list.models[0];
        setSelectedId(active.id);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load models workspace"));
    }
  }, [activeProviderId, selectedId]);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      await loadAll();
      setLoading(false);
    })();
    // Bootstrap once; refresh() re-runs loadAll explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!hardware) return;
    const policy = (hardware as unknown as { policy?: Record<string, unknown> }).policy ?? {};
    setVramReserveDraftState((prev) => {
      const next: VramReserveDraft = {
        displayGpuReserveGb: bytesToGb(policy.displayGpuReserveBytes as number | undefined) || prev.displayGpuReserveGb,
        auxGpuReserveGb: bytesToGb(policy.auxGpuReserveBytes as number | undefined) || prev.auxGpuReserveGb,
        systemRamReserveGb:
          bytesToGb((policy.ramHeadroomBytes ?? policy.defaultVramHeadroomBytes) as number | undefined) ||
          prev.systemRamReserveGb,
      };
      setVramReserveBaseline(next);
      return next;
    });
    // Only re-derive when hardware identity changes (new snapshot after save/refresh).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hardware]);

  const loadCapabilities = useCallback(async (providerId: string, force = false) => {
    if (!providerId) {
      setCapabilities(null);
      return;
    }
    if (!force) {
      const cached = capabilitiesCache.current.get(providerId);
      if (cached) {
        setCapabilities(cached);
        return;
      }
    }
    setCapabilitiesLoading(true);
    try {
      const caps = await api.getProviderCapabilities(providerId);
      capabilitiesCache.current.set(providerId, caps);
      setCapabilities(caps);
    } catch {
      setCapabilities(null);
    } finally {
      setCapabilitiesLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      capabilitiesCache.current.clear();
      const result = await api.refreshModels();
      setModels(result.models);
      setStatus(result.status);
      await loadAll();
      if (activeProvider?.id) {
        await loadCapabilities(activeProvider.id, true);
      }
      toast("Modellen vernieuwd");
    } catch (err) {
      toast(errMsg(err, "Refresh mislukt"));
    } finally {
      setRefreshing(false);
    }
  }, [loadAll, toast, activeProvider?.id, loadCapabilities]);

  const selectModel = useCallback(
    (id: string | null) => {
      const gen = ++selectGen.current;
      setSelectedId(id);
      setEstimate(null);
      setOptimization(null);
      if (!id) {
        setResidency(null);
        setResidencyPolicy(null);
        setRuntimeBinding(null);
        setCapabilities(null);
        return;
      }
      void (async () => {
        try {
          const detail = await api.getModel(id);
          if (gen !== selectGen.current) return;
          setResidency(detail.residency ?? null);
          setRuntimeBinding(detail.runtimeBinding ?? null);
          setResidencyPolicy(detail.residencyPolicy ?? null);
          const patch = draftFromResidencyPolicy(detail.residencyPolicy);
          const nextDraft: ModelsLoadDraft = { ...DEFAULT_DRAFT, ...patch };
          setDraftState(nextDraft);
          setBaseline(nextDraft);
          if (detail.provider?.id) {
            setActiveProviderId(detail.provider.id);
            await loadCapabilities(detail.provider.id);
          }
          const optList = await api.listModelOptimizations(id).catch(() => ({ optimizations: [] }));
          if (gen !== selectGen.current) return;
          const latest = [...(optList.optimizations ?? [])].sort(
            (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0),
          )[0];
          if (latest) setOptimization(latest);
        } catch (err) {
          if (gen === selectGen.current) toast(errMsg(err, "Kon modeldetails niet laden"));
        }
      })();
    },
    [loadCapabilities, toast],
  );

  useEffect(() => {
    if (selectedId && !selectedModel) return;
    if (selectedId) selectModel(selectedId);
    // Run once when the initial catalog resolves a default selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models.length > 0]);

  const setDraft = useCallback((patch: Partial<ModelsLoadDraft>) => {
    setDraftState((prev) => ({ ...prev, ...patch }));
  }, []);

  const setGpuAllocation = useCallback((deviceId: string, ratio: number) => {
    setDraftState((prev) => ({
      ...prev,
      gpuAllocation: { ...prev.gpuAllocation, [deviceId]: ratio },
    }));
  }, []);

  const resetDraft = useCallback(() => {
    setDraftState(baseline);
  }, [baseline]);

  const capField = useCallback(
    (key: string): ProviderCapabilityField | null => {
      const fields = capabilities?.capabilities?.fields;
      if (!fields?.length) return null;
      const aliases = CAP_KEY_ALIASES[key] ?? [key];
      for (const alias of aliases) {
        const hit = fields.find((f) => f.key === alias);
        if (hit) return hit;
      }
      return null;
    },
    [capabilities],
  );

  const capSupport = useCallback(
    (key: string): CapabilitySupportValue => {
      const field = capField(key);
      if (field) return field.support;
      const caps = capabilities?.capabilities as Record<string, unknown> | undefined;
      if (!caps) return "UNKNOWN";
      const aliases = CAP_KEY_ALIASES[key] ?? [key];
      for (const alias of aliases) {
        const raw = caps[alias];
        if (raw === "SUPPORTED" || raw === "UNSUPPORTED" || raw === "UNKNOWN") return raw;
      }
      return "UNKNOWN";
    },
    [capField, capabilities],
  );

  const capNote = useCallback(
    (key: string): string | null => {
      const field = capField(key);
      const support = field?.support ?? capSupport(key);
      if (support === "SUPPORTED") return null;
      if (field?.reasonCode && REASON_NL[field.reasonCode]) {
        return REASON_NL[field.reasonCode];
      }
      if (field?.note) return field.note;
      if (support === "UNSUPPORTED") {
        const providerName = activeProvider?.name || "deze provider";
        return `Niet ondersteund door ${providerName}`;
      }
      if (support === "UNKNOWN") return "Capability nog niet geprobeerd";
      return null;
    },
    [capField, capSupport, activeProvider],
  );

  const awaitJob = useCallback(async (jobId: string): Promise<{ ok: boolean; message?: string }> => {
    const token = ++jobPollAbort.current;
    setActiveJobId(jobId);
    const deadline = Date.now() + JOB_POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (token !== jobPollAbort.current) {
        return { ok: false, message: "Operatie geannuleerd" };
      }
      try {
        const res = await api.getJob(jobId);
        const job = res.job;
        const state = String(job.state ?? job.status ?? "").toUpperCase();
        if (TERMINAL_JOB_STATES.has(state)) {
          setActiveJobId(null);
          if (state === "SUCCEEDED" || state === "COMPLETED" || state === "SUCCESS") {
            return { ok: true };
          }
          if (state === "CANCELLED") {
            return { ok: false, message: "Geannuleerd" };
          }
          return {
            ok: false,
            message: String(job.error ?? job.error_code ?? `Job ${state}`),
          };
        }
      } catch (err) {
        // Transient poll errors — keep trying until timeout.
        if (err instanceof ApiError && err.status === 404) {
          setActiveJobId(null);
          return { ok: false, message: "Job niet gevonden" };
        }
      }
      await new Promise((r) => window.setTimeout(r, JOB_POLL_MS));
    }
    setActiveJobId(null);
    return { ok: false, message: "Timeout tijdens wachten op model_runtime job" };
  }, []);

  const extractQueuedJobId = (result: unknown): string | null => {
    if (!result || typeof result !== "object") return null;
    const obj = result as Record<string, unknown>;
    const job = obj.job;
    if (job && typeof job === "object") {
      const j = job as Record<string, unknown>;
      const id = j.jobId ?? j.job_id ?? j.id;
      if (typeof id === "string" && id) return id;
    }
    const direct = obj.jobId ?? obj.job_id;
    return typeof direct === "string" ? direct : null;
  };

  const runEstimate = useCallback(async () => {
    if (!selectedId) return;
    setEstimating(true);
    try {
      const payload = loadOptionsPayload(draft, hardware?.devices ?? []);
      const result = await api.estimateModelLoad(selectedId, payload);
      setEstimate(result);
      if (result.warnings.length > 0) toast(result.warnings[0]);
    } catch (err) {
      toast(errMsg(err, "Schatting mislukt"));
    } finally {
      setEstimating(false);
    }
  }, [selectedId, draft, hardware, toast]);

  const stopOptimizePolling = useCallback(() => {
    if (optimizePollRef.current != null) {
      window.clearInterval(optimizePollRef.current);
      optimizePollRef.current = null;
    }
  }, []);

  const pollOptimization = useCallback(
    (runId: string) => {
      stopOptimizePolling();
      optimizePollRef.current = window.setInterval(() => {
        void (async () => {
          try {
            const res = await api.getModelOptimization(runId);
            setOptimization(res.optimization);
            if (!RUNNING_OPTIMIZATION_STATUSES.has(res.optimization.status)) {
              stopOptimizePolling();
              const label =
                res.optimization.status === "BEST" || res.optimization.status === "PASS"
                  ? "Optimalisatie voltooid"
                  : `Optimalisatie gestopt: ${res.optimization.status}`;
              toast(label);
            }
          } catch {
            stopOptimizePolling();
          }
        })();
      }, OPTIMIZE_POLL_MS);
    },
    [stopOptimizePolling, toast],
  );

  useEffect(() => stopOptimizePolling, [stopOptimizePolling]);

  const startOptimize = useCallback(async () => {
    if (!selectedId) return;
    try {
      const payload = {
        ...loadOptionsPayload(draft, hardware?.devices ?? []),
        objectives: {
          maxTokensPerSec: optimizationGoals.maxTokensPerSec,
          keepDisplayResponsive: optimizationGoals.keepDisplayResponsive,
          maximizeModelSize: optimizationGoals.maximizeModelSize,
          stableNoOom: optimizationGoals.stableNoOom,
        },
        maxCandidates: 8,
        deadlineSeconds: 900,
      };
      const res = await api.startModelOptimization(selectedId, payload);
      setOptimization(res.optimization);
      toast("Automatisch optimaliseren gestart");
      pollOptimization(res.optimization.runId);
    } catch (err) {
      toast(errMsg(err, "Optimalisatie starten mislukt"));
    }
  }, [selectedId, draft, hardware, optimizationGoals, pollOptimization, toast]);

  const cancelOptimize = useCallback(async () => {
    if (!optimization?.runId) return;
    try {
      const res = await api.cancelModelOptimization(optimization.runId);
      setOptimization(res.optimization);
      stopOptimizePolling();
      toast("Optimalisatie geannuleerd");
    } catch (err) {
      toast(errMsg(err, "Annuleren mislukt"));
    }
  }, [optimization?.runId, stopOptimizePolling, toast]);

  const applyCandidate = useCallback((candidate: ModelOptimizationCandidate) => {
    const opts = candidate.options as Record<string, unknown>;
    setDraftState((prev) => ({
      ...prev,
      contextLength: (opts.contextLength as number) ?? prev.contextLength,
      evalBatchSize: (opts.batchSize as number) ?? prev.evalBatchSize,
      flashAttention: (opts.flashAttention as boolean) ?? prev.flashAttention,
      offloadKvCacheToGpu: (opts.offloadKvCacheToGpu as boolean) ?? prev.offloadKvCacheToGpu,
      gpuOffloadRatio: (opts.gpuOffloadRatio as number) ?? prev.gpuOffloadRatio,
      gpuSplitMode: (opts.gpuSplitMode as string) ?? prev.gpuSplitMode,
      numExperts: (opts.numExperts as number) ?? prev.numExperts,
      keepDisplayHeadroom: (opts.keepDisplayHeadroom as boolean) ?? prev.keepDisplayHeadroom,
    }));
  }, []);

  async function withOp(name: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(name);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  }

  const loadSelected = useCallback(async () => {
    if (!selectedId) return;
    await withOp("load", async () => {
      const payload = loadOptionsPayload(draft, hardware?.devices ?? []);
      try {
        const result = await api.loadModel(selectedId, payload);
        const jobId = extractQueuedJobId(result);
        if (jobId) {
          toast("Laden in wachtrij — Worker Fabric start model_runtime indien koud");
          const terminal = await awaitJob(jobId);
          if (!terminal.ok) {
            toast(terminal.message || "Laden mislukt");
            return;
          }
        }
        setBaseline(draft);
        toast("Model geladen");
        await loadAll();
      } catch (err) {
        const message = errMsg(err, "Laden mislukt");
        if (/OOM|memory/i.test(message) && window.confirm(`${message}\n\nToch doorgaan (confirmOom)?`)) {
          try {
            const result = await api.loadModel(selectedId, { ...payload, confirmOom: true });
            const jobId = extractQueuedJobId(result);
            if (jobId) {
              const terminal = await awaitJob(jobId);
              if (!terminal.ok) {
                toast(terminal.message || "Laden mislukt");
                return;
              }
            }
            setBaseline(draft);
            toast("Model geladen (OOM bevestigd)");
            await loadAll();
            return;
          } catch (err2) {
            toast(errMsg(err2, "Laden mislukt"));
            return;
          }
        }
        toast(message);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, draft, hardware, loadAll, toast, busy, awaitJob]);

  const unloadSelected = useCallback(async () => {
    if (!selectedId) return;
    await withOp("unload", async () => {
      try {
        const result = await api.unloadModel(selectedId);
        const jobId = extractQueuedJobId(result);
        if (jobId) {
          toast("Ontladen in wachtrij");
          const terminal = await awaitJob(jobId);
          if (!terminal.ok) {
            toast(terminal.message || "Ontladen mislukt");
            return;
          }
        }
        toast("Model ontladen");
        await loadAll();
      } catch (err) {
        toast(errMsg(err, "Ontladen mislukt"));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, loadAll, toast, busy, awaitJob]);

  const stop = useCallback(async () => {
    // Cancel Leviathan-owned operation only — never kill external LM Studio.
    const jobId = activeJobId;
    if (jobId) {
      jobPollAbort.current += 1;
      try {
        await api.cancelJob(jobId, "models_page_stop");
        toast("Operatie geannuleerd");
      } catch (err) {
        toast(errMsg(err, "Annuleren mislukt"));
      } finally {
        setActiveJobId(null);
        setBusy(null);
      }
    }
    if (optimization && RUNNING_OPTIMIZATION_STATUSES.has(optimization.status)) {
      await cancelOptimize();
    }
    if (!jobId && !(optimization && RUNNING_OPTIMIZATION_STATUSES.has(optimization.status))) {
      toast("Geen annuleerbare Leviathan-operatie actief");
    }
  }, [activeJobId, optimization, cancelOptimize, toast]);

  const setVramReserveDraft = useCallback((patch: Partial<VramReserveDraft>) => {
    setVramReserveDraftState((prev) => ({ ...prev, ...patch }));
  }, []);

  const saveVramReserve = useCallback(async () => {
    setSavingVramReserve(true);
    try {
      const result = await api.updateHardwarePolicy({
        displayGpuReserveBytes: gbToBytes(vramReserveDraft.displayGpuReserveGb),
        auxGpuReserveBytes: gbToBytes(vramReserveDraft.auxGpuReserveGb),
        ramHeadroomBytes: gbToBytes(vramReserveDraft.systemRamReserveGb),
      });
      setHardware(result.hardware);
      setVramReserveBaseline(vramReserveDraft);
      toast("VRAM reservering opgeslagen");
    } catch (err) {
      toast(errMsg(err, "Opslaan reservering mislukt"));
    } finally {
      setSavingVramReserve(false);
    }
  }, [vramReserveDraft, toast]);

  const testProviderConnection = useCallback(async () => {
    if (!activeProvider) return;
    setProviderConnecting(true);
    try {
      const result = await api.testModelProvider(activeProvider.id);
      capabilitiesCache.current.delete(activeProvider.id);
      await loadCapabilities(activeProvider.id, true);
      toast(
        result.connected
          ? `Verbonden met ${result.provider}: ${result.modelsFound} modellen`
          : "Verbinding mislukt",
      );
      await loadAll();
    } catch (err) {
      toast(errMsg(err, "Testverbinding mislukt"));
    } finally {
      setProviderConnecting(false);
    }
  }, [activeProvider, loadAll, loadCapabilities, toast]);

  const setOptimizationGoal = useCallback((key: keyof OptimizationGoals, value: boolean) => {
    setOptimizationGoals((prev) => ({ ...prev, [key]: value }));
  }, []);

  const saveResidencyPolicy = useCallback(
    async (next: Partial<ResidencyPolicy>) => {
      if (!selectedId) return;
      const saved = await api.saveResidencyPolicy(selectedId, next);
      setResidencyPolicy(saved.policy);
      const detail = await api.getModel(selectedId);
      setResidency(detail.residency ?? null);
      toast("Residency policy opgeslagen");
    },
    [selectedId, toast],
  );

  const saveRouter = useCallback(
    async (next: Partial<RouterConfig>) => {
      const saved = await api.saveRouter(next);
      setRouter(saved.router);
      toast("Router opgeslagen");
    },
    [toast],
  );

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const provider = activeProvider;
    const providerTone = provider?.health === "healthy" ? "success" : provider?.health === "offline" ? "danger" : "muted";
    const rt = status?.modelRuntime;
    const rtState = String(rt?.poolState || rt?.state || "UNMEASURED");
    const rtTone =
      rtState === "READY"
        ? "success"
        : rtState === "COLD" || rtState === "STARTING"
          ? "warning"
          : rt?.acceptJobs
            ? "info"
            : "danger";
    return [
      {
        id: "lm-studio",
        label: provider?.name || "LM Studio",
        value: provider ? (provider.health === "healthy" ? "Running" : provider.health) : loading ? "…" : "UNMEASURED",
        tone: providerTone,
      },
      {
        id: "model-runtime",
        label: "model_runtime",
        value: loading ? "…" : rtState,
        tone: rtTone,
      },
      {
        id: "gpu0",
        label: hardware?.devices?.[0]?.name || "GPU 0",
        value: hardware?.devices?.[0] ? "Ready" : loading ? "…" : "UNMEASURED",
        tone: hardware?.devices?.[0] ? "success" : "muted",
      },
      {
        id: "gpu1",
        label: hardware?.devices?.[1]?.name || "GPU 1",
        value: hardware?.devices?.[1] ? "Ready" : loading ? "…" : "UNMEASURED",
        tone: hardware?.devices?.[1] ? "success" : "muted",
      },
      {
        id: "loaded",
        label: "Geladen modellen",
        value: String(models.filter((m) => m.loaded).length),
        tone: "info",
      },
    ];
  }, [activeProvider, hardware, models, loading, status?.modelRuntime]);

  const online: boolean | null =
    activeProvider?.health === "healthy" ? true : activeProvider?.health === "offline" ? false : null;

  return {
    loading,
    refreshing,
    refresh,
    error,
    online,
    sidebarStatus,

    models,
    filteredModels,
    query,
    setQuery,
    status,

    providers,
    activeProvider,
    setActiveProviderId,
    providerConnecting,
    testProviderConnection,

    hardware,

    selectedId,
    selectedModel,
    selectModel,

    draft,
    setDraft,
    setGpuAllocation,
    resetDraft,
    dirty,

    capabilities,
    capabilitiesLoading,
    capSupport,
    capNote,

    estimate,
    estimating,
    runEstimate,

    optimization,
    optimizing: optimization != null && RUNNING_OPTIMIZATION_STATUSES.has(optimization.status),
    optimizationGoals,
    setOptimizationGoal,
    startOptimize,
    cancelOptimize,
    applyCandidate,

    vramReserveDraft,
    setVramReserveDraft,
    vramReserveDirty,
    savingVramReserve,
    saveVramReserve,

    busy,
    activeJobId,
    loadSelected,
    unloadSelected,
    stop,
    modelRuntime: status?.modelRuntime ?? null,
    capField,

    showImport,
    setShowImport,

    drawer,
    openDrawer: (name) => setDrawer(name),
    closeDrawer: () => setDrawer(null),

    gateway,
    router,
    residency,
    residencyPolicy,
    runtimeBinding,
    saveResidencyPolicy,
    saveRouter,
  };
}
