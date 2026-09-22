import type {
  ApiErrorBody,
  BackupManifest,
  ChatResponse,
  CognitionHealth,
  CognitionRunStatus,
  Conversation,
  DatasetFile,
  DatasetIndex,
  DatasetJob,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetVersion,
  DownloadJob,
  GatewaySnapshot,
  HardwareSnapshot,
  HealthResponse,
  HfDatasetFile,
  MasterGateReport,
  Message,
  MetricsSnapshot,
  ModelDescriptor,
  ModelInferenceTestResult,
  ModelProfile,
  ModelProvider,
  ModelsStatus,
  NeuroAssessmentResponse,
  NeuroResidualStatus,
  PreflightResult,
  ReleaseGateReport,
  ResearchClaim,
  ResearchConflict,
  ResearchCoverage,
  ResearchEvent,
  ResearchEvidence,
  ResearchPlan,
  ResearchProject,
  ResearchProjectCreate,
  ResearchReport,
  ResearchSource,
  ResearchBudget,
  RouterConfig,
  SecurityAuditReport,
  SoakReport,
  TrainingCapabilities,
  TrainingCheckpoint,
  TrainingJob,
  TrainingJobCreatePayload,
  TrainingLogs,
  TrainingMetric,
  TrainingPlan,
  TrainingPreflightPayload,
  TrainingRecipe,
  VerificationReport,
  VerifiedCapability,
  CodingStatusResponse,
  CodingSession,
  CodingSessionDetail,
  CodingMission,
  CodingWorkspaceTreeResponse,
  ChatOptions,
  CapabilityListItem,
  SystemTelemetryResponse,
  McpCallRecord,
  McpServerPublic,
  McpToolRecord,
  MarketSimStatusResponse,
  MarketDataSource,
  MarketStrategy,
  MarketStrategyVersion,
  MarketSimRun,
  MarketSimLiveState,
  SettingsSnapshot,
  SettingState,
  SettingMutationResult,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(data: ApiErrorBody | null, status: number): string {
  if (!data?.detail) {
    return `Request failed (${status})`;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail.map((item) => item.msg).join("; ");
  }
  if (typeof data.detail === "object" && data.detail !== null && "message" in data.detail) {
    const body = data.detail as { code?: string; message?: string };
    return body.code ? `${body.code}: ${body.message ?? ""}` : String(body.message ?? `Request failed (${status})`);
  }
  if (typeof data.detail === "object" && data.detail !== null && "error" in data.detail) {
    const body = data.detail as { error?: unknown; detail?: unknown; message?: string };
    if (typeof body.error === "string") {
      const msg =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.message === "string"
            ? body.message
            : "";
      return msg ? `${body.error}: ${msg}` : body.error;
    }
    const nested = body.error as { code?: string; message?: string };
    if (nested?.message) {
      return nested.code ? `${nested.code}: ${nested.message}` : nested.message;
    }
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = new Headers(options.headers ?? undefined);
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isFormData) {
    // Browser must set multipart boundary — never force application/json.
    headers.delete("Content-Type");
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  let data: ApiErrorBody | null = null;
  try {
    data = (await response.json()) as ApiErrorBody;
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, detailMessage(data, response.status));
  }

  return data as T;
}

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/api/health");
  },

  metrics(): Promise<{ metrics: MetricsSnapshot }> {
    return request<{ metrics: MetricsSnapshot }>("/api/metrics");
  },

  listConversations(opts?: {
    q?: string;
    limit?: number;
  }): Promise<{ conversations: Conversation[] }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request<{ conversations: Conversation[] }>(`/api/conversations${q ? `?${q}` : ""}`);
  },

  createConversation(title = "New conversation"): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },

  getConversation(
    conversationId: string,
  ): Promise<{ conversation: Conversation; messages: Message[] }> {
    return request<{ conversation: Conversation; messages: Message[] }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
    );
  },

  updateConversation(
    conversationId: string,
    patch: { title?: string; pinned?: boolean },
  ): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(patch),
      },
    );
  },

  deleteConversation(conversationId: string): Promise<{ deleted: boolean; id: string }> {
    return request<{ deleted: boolean; id: string }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
      { method: "DELETE" },
    );
  },

  chat(message: string, options: ChatOptions = {}): Promise<ChatResponse> {
    return request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: options.conversationId ?? null,
        ...(options.modelId ? { model_id: options.modelId } : {}),
        ...(options.preferredRole ? { preferred_role: options.preferredRole } : {}),
        ...(options.stream != null ? { stream: options.stream } : {}),
      }),
    });
  },

  /**
   * Stream chat via SSE when backend CHAT_STREAMING is ON.
   * Falls back to non-stream chat() when the response is JSON (feature off / degrade).
   */
  async chatStream(
    message: string,
    options: ChatOptions,
    handlers: {
      onMeta?: (data: Record<string, unknown>) => void;
      onToken?: (text: string, model?: string) => void;
      onDone?: (data: ChatResponse) => void;
      onError?: (detail: string) => void;
    },
  ): Promise<ChatResponse> {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        message,
        conversation_id: options.conversationId ?? null,
        stream: true,
        ...(options.modelId ? { model_id: options.modelId } : {}),
        ...(options.preferredRole ? { preferred_role: options.preferredRole } : {}),
      }),
    });

    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = (await response.json()) as ApiErrorBody;
        detail = detailMessage(body, response.status);
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail);
    }

    // Feature flag OFF → normal JSON response.
    if (!contentType.includes("text/event-stream")) {
      const data = (await response.json()) as ChatResponse;
      handlers.onDone?.(data);
      return data;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new ApiError(503, "Streaming response body missing");
    }
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload: ChatResponse | null = null;
    let eventName = "message";

    const flushBlock = (block: string) => {
      const lines = block.split("\n");
      let dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!dataLines.length) return;
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      } catch {
        return;
      }
      if (eventName === "meta") {
        handlers.onMeta?.(parsed);
      } else if (eventName === "token") {
        const text = typeof parsed.text === "string" ? parsed.text : "";
        const model = typeof parsed.model === "string" ? parsed.model : undefined;
        if (text) handlers.onToken?.(text, model);
      } else if (eventName === "done") {
        donePayload = parsed as unknown as ChatResponse;
        handlers.onDone?.(donePayload);
      } else if (eventName === "error") {
        const detail =
          typeof parsed.detail === "string" ? parsed.detail : "stream error";
        handlers.onError?.(detail);
        throw new ApiError(503, detail);
      }
      eventName = "message";
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        flushBlock(block);
        sep = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) {
      flushBlock(buffer);
    }
    if (!donePayload) {
      throw new ApiError(503, "Stream ended without done event");
    }
    return donePayload;
  },

  listApprovals(status?: string): Promise<{ approvals: unknown[] }> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<{ approvals: unknown[] }>(`/api/approvals${query}`);
  },

  approveApproval(approvalId: string, reason?: string): Promise<{ approval: unknown }> {
    return request(`/api/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    });
  },

  denyApproval(approvalId: string, reason?: string): Promise<{ approval: unknown }> {
    return request(`/api/approvals/${encodeURIComponent(approvalId)}/deny`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    });
  },

  listJobs(): Promise<{ jobs: unknown[] }> {
    return request<{ jobs: unknown[] }>("/api/jobs");
  },

  releaseGates(): Promise<{ report: ReleaseGateReport }> {
    return request<{ report: ReleaseGateReport }>("/api/release/gates");
  },

  securityAudit(): Promise<{ report: SecurityAuditReport }> {
    return request<{ report: SecurityAuditReport }>("/api/security/audit");
  },

  masterGates(): Promise<{ report: MasterGateReport }> {
    return request<{ report: MasterGateReport }>("/api/master/gates");
  },

  listVerificationReports(limit = 20): Promise<{ reports: VerificationReport[] }> {
    return request<{ reports: VerificationReport[] }>(
      `/api/verification/reports?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listBackups(): Promise<{ backups: BackupManifest[] }> {
    return request<{ backups: BackupManifest[] }>("/api/backup");
  },

  createBackup(note?: string): Promise<{ backup: BackupManifest }> {
    return request<{ backup: BackupManifest }>("/api/backup", {
      method: "POST",
      body: JSON.stringify({ note: note ?? null }),
    });
  },

  telemetry(): Promise<{ events: unknown[]; snapshot?: unknown }> {
    return request<{ events: unknown[]; snapshot?: unknown }>("/api/telemetry");
  },

  neuroAssess(text: string): Promise<NeuroAssessmentResponse> {
    return request<NeuroAssessmentResponse>("/api/neuro/assess", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  neuroResidual(): Promise<NeuroResidualStatus> {
    return request<NeuroResidualStatus>("/api/neuro/residual");
  },

  neuroStatus(): Promise<{
    enabled: boolean;
    residual: Record<string, unknown>;
    contrastive: Record<string, unknown>;
    streaming: Record<string, unknown>;
    truth?: Record<string, boolean>;
  }> {
    return request("/api/neuro/status");
  },

  neuroAbsorb(limit = 50): Promise<{ ingested: number; truth?: Record<string, boolean> }> {
    return request<{ ingested: number; truth?: Record<string, boolean> }>("/api/neuro/absorb", {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
  },

  neuroSoak(iterations = 3, mode: "mini" | "long" = "mini"): Promise<{ report: SoakReport }> {
    return request<{ report: SoakReport }>("/api/neuro/soak", {
      method: "POST",
      body: JSON.stringify({ iterations, mode }),
    });
  },

  neuroResidualOrchestrate(payload: {
    text: string;
    complexity?: string;
    run_forward?: boolean;
    mode?: string;
  }): Promise<{ report: unknown }> {
    return request<{ report: unknown }>("/api/neuro/residual/orchestrate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  neuroEvaluation(): Promise<{ report: unknown }> {
    return request<{ report: unknown }>("/api/evaluation/neuro", { method: "POST" });
  },

  listModules(): Promise<{ enabled?: boolean; modules?: unknown[]; truth?: Record<string, boolean> }> {
    return request<{ enabled?: boolean; modules?: unknown[]; truth?: Record<string, boolean> }>(
      "/api/modules",
    );
  },

  listTrainingRecipes(): Promise<{ recipes: TrainingRecipe[] }> {
    return request<{ recipes: TrainingRecipe[] }>("/api/training/recipes");
  },

  listModels(): Promise<{
    models: ModelDescriptor[];
    status: ModelsStatus;
    discoveryLatencyMs?: number | null;
  }> {
    return request("/api/models");
  },

  modelsStatus(): Promise<{
    status: ModelsStatus;
    telemetry: Record<string, unknown>;
  }> {
    return request("/api/models/status");
  },

  refreshModels(): Promise<{
    summary: unknown;
    models: ModelDescriptor[];
    status: ModelsStatus;
  }> {
    return request("/api/models/refresh", { method: "POST" });
  },

  getModel(modelId: string): Promise<{
    model: ModelDescriptor;
    profile: ModelProfile;
    capabilities: VerifiedCapability[];
    provider: ModelProvider | null;
    preflight: Record<string, unknown>;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}`);
  },

  getModelProfile(modelId: string): Promise<{ profile: ModelProfile }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`);
  },

  saveModelProfile(
    modelId: string,
    profile: Partial<ModelProfile> & { activate?: boolean },
  ): Promise<{ profile: ModelProfile; activeModelId: string | null }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`, {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  },

  activateModel(modelId: string): Promise<{
    model: ModelDescriptor;
    activeModelId: string;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/activate`, { method: "POST" });
  },

  loadModel(modelId: string, options: Record<string, unknown> = {}): Promise<unknown> {
    return request(`/api/models/${encodeURIComponent(modelId)}/load`, {
      method: "POST",
      body: JSON.stringify(options),
    });
  },

  unloadModel(modelId: string): Promise<unknown> {
    return request(`/api/models/${encodeURIComponent(modelId)}/unload`, { method: "POST" });
  },

  deleteModel(modelId: string): Promise<{ deleted: boolean }> {
    return request(`/api/models/${encodeURIComponent(modelId)}`, { method: "DELETE" });
  },

  probeModel(modelId: string, capabilities?: string[]): Promise<{ results: VerifiedCapability[] }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/probe`, {
      method: "POST",
      body: JSON.stringify({ capabilities }),
    });
  },

  benchmarkModel(modelId: string): Promise<{ benchmark: Record<string, unknown> }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/benchmark`, { method: "POST" });
  },

  testModel(
    modelId: string,
    payload: { prompt: string; maxTokens?: number; stream?: boolean },
  ): Promise<{ result: ModelInferenceTestResult }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/test`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getGateway(): Promise<{ gateway: GatewaySnapshot }> {
    return request("/api/models/gateway");
  },

  getRouter(): Promise<{ router: RouterConfig }> {
    return request("/api/models/router");
  },

  saveRouter(config: Partial<RouterConfig>): Promise<{ router: RouterConfig }> {
    return request("/api/models/router", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  },

  listModelProviders(): Promise<{ providers: ModelProvider[] }> {
    return request("/api/model-providers");
  },

  createModelProvider(payload: Record<string, unknown>): Promise<{
    provider: ModelProvider;
  }> {
    return request("/api/model-providers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateModelProvider(
    providerId: string,
    payload: Record<string, unknown>,
  ): Promise<{ provider: ModelProvider }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteModelProvider(providerId: string): Promise<{ deleted: boolean }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}`, { method: "DELETE" });
  },

  testModelProvider(providerId: string): Promise<{
    connected: boolean;
    providerId: string;
    provider: string;
    modelsFound: number;
    latencyMs: number | null;
    health: string;
    error: string | null;
  }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
    });
  },

  importModel(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return request("/api/models/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  downloadModel(payload: Record<string, unknown>): Promise<{
    download: DownloadJob;
  }> {
    return request("/api/models/download", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listModelDownloads(): Promise<{ downloads: DownloadJob[] }> {
    return request("/api/model-downloads");
  },

  cancelModelDownload(downloadId: string): Promise<{ download: DownloadJob }> {
    return request(`/api/model-downloads/${encodeURIComponent(downloadId)}/cancel`, {
      method: "POST",
    });
  },

  /* ---------- Datasets ---------- */

  listDatasets(limit = 100): Promise<{ datasets: DatasetRecord[] }> {
    return request(`/api/datasets?limit=${encodeURIComponent(String(limit))}`);
  },

  createDataset(payload: {
    name: string;
    description?: string;
    license?: string | null;
    metadata?: Record<string, unknown>;
  }): Promise<{ dataset: DatasetRecord }> {
    return request("/api/datasets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  uploadDataset(form: FormData): Promise<{ job: DatasetJob; bytes: number; filename: string }> {
    return request("/api/datasets/upload", {
      method: "POST",
      body: form,
    });
  },

  getDataset(datasetId: string): Promise<{
    dataset: DatasetRecord;
    versions: DatasetVersion[];
    files: DatasetFile[];
    indexes: DatasetIndex[];
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}`);
  },

  deleteDataset(datasetId: string): Promise<{ deleted: boolean; datasetId: string }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" });
  },

  inspectDatasetPath(path: string): Promise<{ inspection: Record<string, unknown> }> {
    return request("/api/datasets/inspect", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },

  importDatasetLocal(payload: {
    path: string;
    name?: string | null;
    description?: string;
    license?: string | null;
    materialize?: boolean;
    datasetId?: string | null;
  }): Promise<{ job: DatasetJob }> {
    return request("/api/datasets/import/local", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  importDatasetHuggingFace(payload: {
    repositoryId: string;
    filename: string;
    revision?: string;
    name?: string | null;
    description?: string;
    license?: string | null;
    token?: string | null;
    materialize?: boolean;
    datasetId?: string | null;
  }): Promise<{ job: DatasetJob }> {
    return request("/api/datasets/import/huggingface", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listHuggingFaceDatasetFiles(payload: {
    repositoryId: string;
    revision?: string;
    token?: string | null;
  }): Promise<{ files: HfDatasetFile[] }> {
    return request("/api/datasets/huggingface/list", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listDatasetVersions(datasetId: string): Promise<{ versions: DatasetVersion[] }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/versions`);
  },

  getDatasetVersion(versionId: string): Promise<{ version: DatasetVersion }> {
    return request(`/api/datasets/versions/${encodeURIComponent(versionId)}`);
  },

  previewDatasetVersion(
    versionId: string,
    limit = 20,
  ): Promise<{ rows: DatasetPreviewRow[]; limit: number }> {
    return request(
      `/api/datasets/versions/${encodeURIComponent(versionId)}/preview?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  scanDatasetPii(versionId: string): Promise<{ pii: Record<string, unknown> }> {
    return request(`/api/datasets/versions/${encodeURIComponent(versionId)}/pii`);
  },

  materializeDataset(datasetId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/materialize`, {
      method: "POST",
    });
  },

  validateDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/validate`,
      { method: "POST" },
    );
  },

  dedupeDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/dedupe`,
      { method: "POST" },
    );
  },

  transformDatasetVersion(
    datasetId: string,
    versionId: string,
    transforms: Record<string, unknown>[] = [],
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/transform`,
      { method: "POST", body: JSON.stringify({ transforms }) },
    );
  },

  splitDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { seed?: number; trainRatio?: number; valRatio?: number; testRatio?: number } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/split`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  tokenizeStatsDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/tokenize-stats`,
      { method: "POST" },
    );
  },

  exportDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { split?: string | null } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/export`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  indexDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { scope?: string; maxRecords?: number | null } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/index`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  listDatasetJobs(datasetId?: string, limit = 100): Promise<{ jobs: DatasetJob[] }> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (datasetId) params.set("datasetId", datasetId);
    return request(`/api/datasets/jobs?${params.toString()}`);
  },

  getDatasetJob(jobId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/jobs/${encodeURIComponent(jobId)}`);
  },

  cancelDatasetJob(jobId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },

  processDatasetJobs(maxJobs = 10): Promise<{ processed: DatasetJob[] }> {
    return request(`/api/datasets/jobs/process?maxJobs=${encodeURIComponent(String(maxJobs))}`, {
      method: "POST",
    });
  },

  reconcileDatasetJobs(): Promise<{ updated: DatasetJob[] }> {
    return request("/api/datasets/jobs/reconcile", { method: "POST" });
  },

  /* ---------- Training ---------- */

  trainingCapabilities(): Promise<{ capabilities: TrainingCapabilities }> {
    return request("/api/training/capabilities");
  },

  trainingHardware(): Promise<{ hardware: HardwareSnapshot }> {
    return request("/api/training/hardware");
  },

  trainingPreflight(payload: TrainingPreflightPayload): Promise<{ preflight: PreflightResult }> {
    return request("/api/training/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  trainingPlan(payload: TrainingPreflightPayload): Promise<{ plan: TrainingPlan }> {
    return request("/api/training/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listTrainingJobs(status?: string, limit = 100): Promise<{ jobs: TrainingJob[] }> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set("status", status);
    return request(`/api/training/jobs?${params.toString()}`);
  },

  createTrainingJob(payload: TrainingJobCreatePayload): Promise<{ job: TrainingJob }> {
    return request("/api/training/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}`);
  },

  startTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/start`, { method: "POST" });
  },

  cancelTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },

  resumeTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
  },

  listTrainingCheckpoints(jobId: string): Promise<{ checkpoints: TrainingCheckpoint[] }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/checkpoints`);
  },

  listTrainingMetrics(jobId: string, limit = 500): Promise<{ metrics: TrainingMetric[] }> {
    return request(
      `/api/training/jobs/${encodeURIComponent(jobId)}/metrics?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  getTrainingLogs(jobId: string): Promise<TrainingLogs> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/logs`);
  },

  evaluateTrainingJob(jobId: string): Promise<{ evaluation: Record<string, unknown> }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/evaluate`, { method: "POST" });
  },

  exportTrainingJob(jobId: string): Promise<{ export: Record<string, unknown> }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/export`, { method: "POST" });
  },

  reconcileTrainingJobs(): Promise<{ reconciled: number }> {
    return request("/api/training/reconcile", { method: "POST" });
  },

  /* ---------- Research ---------- */

  researchBudgets(): Promise<{ presets: Record<string, ResearchBudget> }> {
    return request("/api/research/budgets");
  },

  listResearchProjects(limit = 100): Promise<{ projects: ResearchProject[] }> {
    return request(`/api/research?limit=${encodeURIComponent(String(limit))}`);
  },

  createResearchProject(payload: ResearchProjectCreate): Promise<{ project: ResearchProject }> {
    return request("/api/research", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}`);
  },

  updateResearchProject(
    projectId: string,
    payload: Partial<ResearchProjectCreate>,
  ): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  planResearchProject(
    projectId: string,
    payload: Record<string, unknown> = {},
  ): Promise<{ project: ResearchProject; plan: ResearchPlan | null }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/plan`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/run`, { method: "POST" });
  },

  cancelResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/cancel`, { method: "POST" });
  },

  resumeResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/resume`, { method: "POST" });
  },

  deepenResearchProject(
    projectId: string,
    extraRounds = 1,
  ): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/deepen`, {
      method: "POST",
      body: JSON.stringify({ extraRounds }),
    });
  },

  listResearchEvents(projectId: string, limit = 200): Promise<{ events: ResearchEvent[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/events?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchSources(projectId: string, limit = 200): Promise<{ sources: ResearchSource[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchEvidence(projectId: string, limit = 500): Promise<{ evidence: ResearchEvidence[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/evidence?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchClaims(projectId: string, limit = 500): Promise<{ claims: ResearchClaim[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/claims?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchConflicts(
    projectId: string,
    limit = 200,
  ): Promise<{ conflicts: ResearchConflict[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/conflicts?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  getResearchCoverage(projectId: string): Promise<{ coverage: ResearchCoverage }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/coverage`);
  },

  getResearchReport(projectId: string): Promise<{ report: ResearchReport }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/report`);
  },

  regenerateResearchReport(projectId: string): Promise<{ report: ResearchReport }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/report`, { method: "POST" });
  },

  exportResearchProject(
    projectId: string,
    format: "markdown" | "md" | "html" | "json" = "markdown",
  ): Promise<{ export: Record<string, unknown> }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/export?format=${encodeURIComponent(format)}`,
    );
  },

  /* ---------- Coding Agent ---------- */

  codingStatus(): Promise<CodingStatusResponse> {
    return request("/api/coding/status");
  },

  listCodingSessions(limit = 50): Promise<{ sessions: CodingSession[] }> {
    return request(`/api/coding/sessions?limit=${encodeURIComponent(String(limit))}`);
  },

  createCodingSession(payload: {
    goal: string;
    mission?: CodingMission;
    workspace_root?: string;
    model_id?: string;
  }): Promise<{ session: CodingSession }> {
    return request("/api/coding/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getCodingSession(sessionId: string): Promise<CodingSessionDetail> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}`);
  },

  codingTurn(
    sessionId: string,
    payload: { message?: string; approval_id?: string; capability_id?: string },
  ): Promise<CodingSessionDetail> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}/turn`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  cancelCodingSession(sessionId: string): Promise<{ session: CodingSession }> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}/cancel`, {
      method: "POST",
    });
  },

  codingWorkspaceTree(opts?: {
    path?: string;
    recursive?: boolean;
  }): Promise<CodingWorkspaceTreeResponse> {
    const params = new URLSearchParams();
    if (opts?.path) params.set("path", opts.path);
    if (opts?.recursive != null) params.set("recursive", String(opts.recursive));
    const q = params.toString();
    return request(`/api/coding/workspace/tree${q ? `?${q}` : ""}`);
  },

  systemTelemetry(): Promise<SystemTelemetryResponse> {
    return request<SystemTelemetryResponse>("/api/system/telemetry");
  },

  listCapabilities(opts?: {
    q?: string;
    limit?: number;
  }): Promise<{ capabilities: CapabilityListItem[] }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request<{ capabilities: CapabilityListItem[] }>(`/api/capabilities${q ? `?${q}` : ""}`);
  },

  mcpServers(): Promise<{ servers: McpServerPublic[]; feature_enabled: boolean }> {
    return request("/api/mcp/servers");
  },

  mcpCreateServer(payload: Record<string, unknown>): Promise<{ server: McpServerPublic }> {
    return request("/api/mcp/servers", { method: "POST", body: JSON.stringify(payload) });
  },

  mcpEnableServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/enable`, { method: "POST" });
  },

  mcpDisableServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/disable`, { method: "POST" });
  },

  mcpConnectServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/connect`, { method: "POST" });
  },

  mcpDisconnectServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/disconnect`, {
      method: "POST",
    });
  },

  mcpRefreshTools(serverId: string): Promise<{ tools: McpToolRecord[] }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/refresh-tools`, {
      method: "POST",
    });
  },

  mcpDeleteServer(serverId: string): Promise<{ ok: boolean }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}`, { method: "DELETE" });
  },

  mcpTools(serverId?: string): Promise<{ tools: McpToolRecord[] }> {
    const q = serverId ? `?server_id=${encodeURIComponent(serverId)}` : "";
    return request(`/api/mcp/tools${q}`);
  },

  mcpCalls(limit = 100): Promise<{ calls: McpCallRecord[] }> {
    return request(`/api/mcp/calls?limit=${encodeURIComponent(String(limit))}`);
  },

  mcpCall(payload: {
    capability_id: string;
    arguments?: Record<string, unknown>;
    approval_id?: string;
    approved_by_user?: boolean;
  }): Promise<{ result: unknown; truth: Record<string, boolean> }> {
    return request("/api/mcp/call", { method: "POST", body: JSON.stringify(payload) });
  },

  /* ---------- Market Simulation ---------- */

  marketSimStatus(): Promise<MarketSimStatusResponse> {
    return request("/api/market-sim/status");
  },

  listMarketData(limit = 200): Promise<{ sources: MarketDataSource[] }> {
    return request(`/api/market-sim/data?limit=${encodeURIComponent(String(limit))}`);
  },

  scanMarketData(): Promise<{ sources: MarketDataSource[] }> {
    return request("/api/market-sim/data/scan", { method: "POST" });
  },

  registerMarketData(payload: {
    path: string;
    symbol?: string;
    timeframe?: string;
  }): Promise<{ source: MarketDataSource }> {
    return request("/api/market-sim/data/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listMarketStrategies(limit = 100): Promise<{ strategies: MarketStrategy[] }> {
    return request(`/api/market-sim/strategies?limit=${encodeURIComponent(String(limit))}`);
  },

  createMarketStrategy(payload: {
    name: string;
    description?: string;
    tags?: string[];
    parameters?: Record<string, unknown>;
    entryRules?: Record<string, unknown>;
    exitRules?: Record<string, unknown>;
    riskRules?: Record<string, unknown>;
    requiredTimeframes?: string[];
    brainDependencies?: string[];
  }): Promise<{ strategy: MarketStrategy; version: MarketStrategyVersion }> {
    return request("/api/market-sim/strategies", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getMarketStrategy(
    strategyId: string,
  ): Promise<{ strategy: MarketStrategy; versions: MarketStrategyVersion[] }> {
    return request(`/api/market-sim/strategies/${encodeURIComponent(strategyId)}`);
  },

  listMarketSimRuns(limit = 50): Promise<{ runs: MarketSimRun[] }> {
    return request(`/api/market-sim/runs?limit=${encodeURIComponent(String(limit))}`);
  },

  createMarketSimRun(payload: {
    sourceId: string;
    strategyId?: string;
    strategyVersion?: number;
    startTs?: string;
    endTs?: string;
    seed?: number;
    speed?: number;
    initialCash?: number;
    deliberationEveryN?: number;
    agents?: Array<Record<string, unknown>>;
  }): Promise<{ run: MarketSimRun }> {
    return request("/api/market-sim/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  startMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/start`, { method: "POST" });
  },

  pauseMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/pause`, { method: "POST" });
  },

  stepMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/step`, { method: "POST" });
  },

  stopMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
  },

  getMarketSimLive(runId: string): Promise<MarketSimLiveState> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/live`);
  },

  getMarketSimResults(runId: string): Promise<MarketSimLiveState & { metrics: Record<string, unknown> }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/results`);
  },

  cognitionHealth(): Promise<{ cognition: CognitionHealth }> {
    return request("/api/cognition/health");
  },

  cognitionSubmit(payload: {
    message: string;
    conversation_id?: string | null;
    history?: Array<{ role: string; content: string }>;
    has_knowledge?: boolean;
    shadow?: boolean | null;
    constraints?: string[];
    run?: boolean;
  }): Promise<CognitionRunStatus> {
    return request("/api/cognition/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  cognitionStatus(runId: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}`);
  },

  cognitionEvents(runId: string): Promise<{ run_id: string; events: unknown[] }> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/events`);
  },

  cognitionCancel(runId: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  },

  cognitionSteer(runId: string, instruction: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/steer`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    });
  },

  getSettings(): Promise<SettingsSnapshot> {
    return request("/api/settings");
  },

  getSettingsCatalog(): Promise<Record<string, unknown>> {
    return request("/api/settings/catalog");
  },

  getSettingsCategory(category: string): Promise<{ category: string; settings: SettingState[] }> {
    return request(`/api/settings/categories/${encodeURIComponent(category)}`);
  },

  patchSettings(
    values: Record<string, unknown>,
    confirmDangerous = false,
  ): Promise<{ results: SettingMutationResult[]; settings: SettingState[] }> {
    return request("/api/settings", {
      method: "PATCH",
      body: JSON.stringify({ values, confirm_dangerous: confirmDangerous }),
    });
  },

  patchSetting(
    key: string,
    value: unknown,
    opts?: { confirmDangerous?: boolean; clearSecret?: boolean },
  ): Promise<{ result: SettingMutationResult; setting: SettingState }> {
    return request(`/api/settings/keys/${key.split("/").map(encodeURIComponent).join("/")}`, {
      method: "PATCH",
      body: JSON.stringify({
        value,
        confirm_dangerous: opts?.confirmDangerous ?? false,
        clear_secret: opts?.clearSecret ?? false,
      }),
    });
  },

  resetSetting(key: string): Promise<{ result: SettingMutationResult; setting: SettingState }> {
    return request(`/api/settings/reset/${key.split("/").map(encodeURIComponent).join("/")}`, {
      method: "POST",
    });
  },

  resetSettingsCategory(
    category: string,
  ): Promise<{ results: SettingMutationResult[]; settings: SettingState[] }> {
    return request(`/api/settings/reset-category/${encodeURIComponent(category)}`, {
      method: "POST",
    });
  },
};
