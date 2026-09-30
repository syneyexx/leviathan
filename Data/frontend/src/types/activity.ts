/** Canonical ActivityEvent contracts — mirrors Data/modules/run/activity.py */

export type ActivityCategory =
  | "REQUEST"
  | "PLANNING"
  | "RETRIEVAL"
  | "MEMORY"
  | "KNOWLEDGE"
  | "RESEARCH"
  | "DATA"
  | "MODEL"
  | "AGENT"
  | "TOOL"
  | "EXECUTION"
  | "EXPERIMENT"
  | "HYPOTHESIS"
  | "EVALUATION"
  | "VERIFICATION"
  | "DECISION"
  | "RISK"
  | "TRADING"
  | "ARTIFACT"
  | "SYNTHESIS"
  | "SYSTEM"
  | "SECURITY"
  | "RECOVERY"
  | string;

export type ActivityPhase = string;

export type ActivityLifecycle =
  | "queued"
  | "starting"
  | "running"
  | "waiting"
  | "retrying"
  | "completed"
  | "failed"
  | "cancelled"
  | "degraded"
  | "skipped"
  | string;

export type ActorType =
  | "leviathan"
  | "agent"
  | "worker"
  | "tool"
  | "model"
  | "research"
  | "trading"
  | "system"
  | string;

export type ProgressKind = "unknown" | "indeterminate" | "measured" | "estimated" | string;

export type VisibilityClass = "USER_VISIBLE" | "DEVELOPER" | "INTERNAL" | "SENSITIVE" | string;

export type ActivityDisplayMode = "off" | "compact" | "detailed" | "developer";

export type ProgressMeasurement = {
  kind: ProgressKind;
  value?: number | null;
  unit?: string | null;
  numerator?: number | null;
  denominator?: number | null;
  basis?: string | null;
};

export type ActivityError = {
  code: string;
  message: string;
  retryable?: boolean | null;
  details?: Record<string, unknown>;
};

export type ActivityConfigTriple = {
  requested?: Record<string, unknown>;
  effective?: Record<string, unknown>;
  measured?: Record<string, unknown>;
};

export type ActivityEvent = {
  eventId: string;
  operationId: string;
  parentEventId?: string | null;
  traceId?: string | null;
  spanId?: string | null;
  sequence: number;
  actorType: ActorType;
  actorId?: string | null;
  category: ActivityCategory;
  phase: ActivityPhase;
  lifecycle: ActivityLifecycle;
  title: string;
  summary?: string | null;
  startedAt?: string | null;
  updatedAt?: string | null;
  finishedAt?: string | null;
  progress?: ProgressMeasurement | null;
  evidenceRefs?: string[];
  artifactRefs?: string[];
  sourceRefs?: string[];
  modelRef?: string | null;
  agentRef?: string | null;
  workerRef?: string | null;
  capabilityRef?: string | null;
  config?: ActivityConfigTriple | null;
  resultCount?: number | null;
  retry?: Record<string, unknown> | null;
  error?: ActivityError | null;
  visibility?: VisibilityClass;
  sensitivity?: string;
  schemaVersion?: number;
  payload?: Record<string, unknown>;
  children?: ActivityEvent[];
  truth?: Record<string, boolean>;
};

export type ActivityProjection = {
  operationId: string;
  highestSequence: number;
  stale?: boolean;
  disconnected?: boolean;
  tree: ActivityEvent[];
  events: ActivityEvent[];
  schemaVersion?: number;
  truth?: Record<string, boolean>;
};

export type DecisionCheckResult = {
  name: string;
  status: string;
  detail?: string | null;
  evidenceRefs?: string[];
};

export type DecisionReceipt = {
  decisionId: string;
  operationId?: string | null;
  actorId?: string | null;
  strategyId?: string | null;
  strategyVersion?: string | null;
  modelVersion?: string | null;
  timestamp?: string | null;
  instrumentOrUniverse?: string | null;
  dataVersion?: string | null;
  marketDataSnapshotRef?: string | null;
  featureProvenanceRefs?: string[];
  researchEvidenceRefs?: string[];
  hypothesisRef?: string | null;
  checks?: DecisionCheckResult[];
  riskLimitsInForce?: Record<string, unknown>;
  requestedConfig?: Record<string, unknown>;
  effectiveConfig?: Record<string, unknown>;
  decisionResult?: string | null;
  executionStatus?: string | null;
  artifactOrOrderRef?: string | null;
  warnings?: string[];
  errors?: string[];
  source?: string;
  schemaVersion?: number;
  truth?: Record<string, boolean>;
};

export function parseActivityEvent(raw: unknown): ActivityEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const eventId = typeof obj.eventId === "string" ? obj.eventId : null;
  const operationId = typeof obj.operationId === "string" ? obj.operationId : null;
  if (!eventId || !operationId) return null;
  const sequence = typeof obj.sequence === "number" ? obj.sequence : Number(obj.sequence ?? 0);
  if (!Number.isFinite(sequence)) return null;
  const title = typeof obj.title === "string" ? obj.title : "Activity";
  const lifecycle = typeof obj.lifecycle === "string" ? obj.lifecycle : "running";
  const category = typeof obj.category === "string" ? obj.category : "SYSTEM";
  const phase = typeof obj.phase === "string" ? obj.phase : "unknown";
  const actorType = typeof obj.actorType === "string" ? obj.actorType : "system";
  const childrenRaw = Array.isArray(obj.children) ? obj.children : [];
  const children = childrenRaw
    .map((c) => parseActivityEvent(c))
    .filter((c): c is ActivityEvent => c != null);
  return {
    eventId,
    operationId,
    parentEventId: typeof obj.parentEventId === "string" ? obj.parentEventId : null,
    traceId: typeof obj.traceId === "string" ? obj.traceId : null,
    spanId: typeof obj.spanId === "string" ? obj.spanId : null,
    sequence,
    actorType,
    actorId: typeof obj.actorId === "string" ? obj.actorId : null,
    category,
    phase,
    lifecycle,
    title,
    summary: typeof obj.summary === "string" ? obj.summary : null,
    startedAt: typeof obj.startedAt === "string" ? obj.startedAt : null,
    updatedAt: typeof obj.updatedAt === "string" ? obj.updatedAt : null,
    finishedAt: typeof obj.finishedAt === "string" ? obj.finishedAt : null,
    progress:
      obj.progress && typeof obj.progress === "object"
        ? (obj.progress as ProgressMeasurement)
        : null,
    evidenceRefs: Array.isArray(obj.evidenceRefs)
      ? obj.evidenceRefs.map(String)
      : [],
    artifactRefs: Array.isArray(obj.artifactRefs)
      ? obj.artifactRefs.map(String)
      : [],
    sourceRefs: Array.isArray(obj.sourceRefs) ? obj.sourceRefs.map(String) : [],
    modelRef: typeof obj.modelRef === "string" ? obj.modelRef : null,
    agentRef: typeof obj.agentRef === "string" ? obj.agentRef : null,
    workerRef: typeof obj.workerRef === "string" ? obj.workerRef : null,
    capabilityRef: typeof obj.capabilityRef === "string" ? obj.capabilityRef : null,
    config:
      obj.config && typeof obj.config === "object"
        ? (obj.config as ActivityConfigTriple)
        : null,
    resultCount:
      typeof obj.resultCount === "number" && Number.isFinite(obj.resultCount)
        ? obj.resultCount
        : null,
    retry: obj.retry && typeof obj.retry === "object" ? (obj.retry as Record<string, unknown>) : null,
    error: obj.error && typeof obj.error === "object" ? (obj.error as ActivityError) : null,
    visibility: typeof obj.visibility === "string" ? obj.visibility : "USER_VISIBLE",
    sensitivity: typeof obj.sensitivity === "string" ? obj.sensitivity : undefined,
    schemaVersion:
      typeof obj.schemaVersion === "number" ? obj.schemaVersion : undefined,
    payload:
      obj.payload && typeof obj.payload === "object"
        ? (obj.payload as Record<string, unknown>)
        : {},
    children,
    truth:
      obj.truth && typeof obj.truth === "object"
        ? (obj.truth as Record<string, boolean>)
        : undefined,
  };
}

export function parseActivityProjection(raw: unknown): ActivityProjection | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const operationId = typeof obj.operationId === "string" ? obj.operationId : "";
  const tree = Array.isArray(obj.tree)
    ? obj.tree.map(parseActivityEvent).filter((e): e is ActivityEvent => e != null)
    : [];
  const events = Array.isArray(obj.events)
    ? obj.events.map(parseActivityEvent).filter((e): e is ActivityEvent => e != null)
    : [];
  return {
    operationId,
    highestSequence:
      typeof obj.highestSequence === "number" ? obj.highestSequence : 0,
    stale: Boolean(obj.stale),
    disconnected: Boolean(obj.disconnected),
    tree,
    events,
    schemaVersion:
      typeof obj.schemaVersion === "number" ? obj.schemaVersion : undefined,
    truth:
      obj.truth && typeof obj.truth === "object"
        ? (obj.truth as Record<string, boolean>)
        : undefined,
  };
}
