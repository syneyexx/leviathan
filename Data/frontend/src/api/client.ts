import type {
  ApiErrorBody,
  BackupManifest,
  ChatResponse,
  Conversation,
  HealthResponse,
  MasterGateReport,
  Message,
  MetricsSnapshot,
  NeuroAssessmentResponse,
  NeuroResidualStatus,
  ReleaseGateReport,
  SecurityAuditReport,
  SoakReport,
  TrainingRecipe,
  VerificationReport,
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
  return `Request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
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

  listConversations(): Promise<{ conversations: Conversation[] }> {
    return request<{ conversations: Conversation[] }>("/api/conversations");
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

  chat(message: string, conversationId: string | null): Promise<ChatResponse> {
    return request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
      }),
    });
  },

  listCapabilities(): Promise<{ capabilities: unknown[] }> {
    return request<{ capabilities: unknown[] }>("/api/capabilities");
  },

  listApprovals(status?: string): Promise<{ approvals: unknown[] }> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<{ approvals: unknown[] }>(`/api/approvals${query}`);
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

  neuroAbsorb(limit = 50): Promise<{ ingested: number; truth?: Record<string, boolean> }> {
    return request<{ ingested: number; truth?: Record<string, boolean> }>("/api/neuro/absorb", {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
  },

  neuroSoak(iterations = 3): Promise<{ report: SoakReport }> {
    return request<{ report: SoakReport }>("/api/neuro/soak", {
      method: "POST",
      body: JSON.stringify({ iterations }),
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
    models: import("../types/api").ModelDescriptor[];
    status: import("../types/api").ModelsStatus;
    discoveryLatencyMs?: number | null;
  }> {
    return request("/api/models");
  },

  modelsStatus(): Promise<{
    status: import("../types/api").ModelsStatus;
    telemetry: Record<string, unknown>;
  }> {
    return request("/api/models/status");
  },

  refreshModels(): Promise<{
    summary: unknown;
    models: import("../types/api").ModelDescriptor[];
    status: import("../types/api").ModelsStatus;
  }> {
    return request("/api/models/refresh", { method: "POST" });
  },

  getModel(modelId: string): Promise<{
    model: import("../types/api").ModelDescriptor;
    profile: import("../types/api").ModelProfile;
    capabilities: import("../types/api").VerifiedCapability[];
    provider: import("../types/api").ModelProvider | null;
    preflight: Record<string, unknown>;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}`);
  },

  getModelProfile(modelId: string): Promise<{ profile: import("../types/api").ModelProfile }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`);
  },

  saveModelProfile(
    modelId: string,
    profile: Partial<import("../types/api").ModelProfile> & { activate?: boolean },
  ): Promise<{ profile: import("../types/api").ModelProfile; activeModelId: string | null }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`, {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  },

  activateModel(modelId: string): Promise<{
    model: import("../types/api").ModelDescriptor;
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

  probeModel(
    modelId: string,
    capabilities?: string[],
  ): Promise<{ results: import("../types/api").VerifiedCapability[] }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/probe`, {
      method: "POST",
      body: JSON.stringify({ capabilities }),
    });
  },

  benchmarkModel(modelId: string): Promise<{ benchmark: Record<string, unknown> }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/benchmark`, { method: "POST" });
  },

  getGateway(): Promise<{ gateway: import("../types/api").GatewaySnapshot }> {
    return request("/api/models/gateway");
  },

  getRouter(): Promise<{ router: import("../types/api").RouterConfig }> {
    return request("/api/models/router");
  },

  saveRouter(
    config: Partial<import("../types/api").RouterConfig>,
  ): Promise<{ router: import("../types/api").RouterConfig }> {
    return request("/api/models/router", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  },

  listModelProviders(): Promise<{ providers: import("../types/api").ModelProvider[] }> {
    return request("/api/model-providers");
  },

  createModelProvider(payload: Record<string, unknown>): Promise<{
    provider: import("../types/api").ModelProvider;
  }> {
    return request("/api/model-providers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateModelProvider(
    providerId: string,
    payload: Record<string, unknown>,
  ): Promise<{ provider: import("../types/api").ModelProvider }> {
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
    download: import("../types/api").DownloadJob;
  }> {
    return request("/api/models/download", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listModelDownloads(): Promise<{ downloads: import("../types/api").DownloadJob[] }> {
    return request("/api/model-downloads");
  },

  cancelModelDownload(downloadId: string): Promise<{ download: import("../types/api").DownloadJob }> {
    return request(`/api/model-downloads/${encodeURIComponent(downloadId)}/cancel`, {
      method: "POST",
    });
  },
};
