import type { ServiceCardModel, ServiceTone } from "../types/backend";
import type { HostSnapshot } from "../types/host";
import {
  asProjection,
  transportFailed,
  type ProjectionState,
  type ReadProjection,
} from "./projection";

function card(id: string, name: string, state: string, detail: string): ServiceCardModel {
  return { id, name, state, detail, tone: toneFor(state) };
}

export function toneFor(state: string): ServiceTone {
  const token = state.toUpperCase().replace(/\s+/g, "_");
  if (["HEALTHY", "READY", "OK", "AVAILABLE", "RUNNING", "PASS", "IDLE", "WAITING"].includes(token)) return "ok";
  if (
    [
      "DEGRADED",
      "BUSY",
      "STARTING",
      "PARTIAL",
      "DISABLED",
      "DISABLED_BY_SAFE_MODE",
      "STALE",
      "NOT_CONFIGURED",
      "NO_MODEL_LOADED",
    ].includes(token)
  ) {
    return "warn";
  }
  if (
    [
      "FAILED",
      "ERROR",
      "MISSING",
      "BUILD_MISSING",
      "UNAVAILABLE",
      "TRANSPORT_ERROR",
    ].includes(token)
  ) {
    return "bad";
  }
  return "muted";
}

function transportLabel(state: ProjectionState): string {
  if (state === "STALE") return "STALE";
  if (state === "UNAVAILABLE") return "UNAVAILABLE";
  return "TRANSPORT ERROR";
}

function dbCard(
  projection: ReadProjection<Array<Record<string, unknown>>>,
  domain: string,
): ServiceCardModel {
  if (transportFailed(projection) && projection.data == null) {
    return card(domain.toLowerCase(), `${domain} DB`, transportLabel(projection.state), projection.errorDetail || "database status unread");
  }
  const rows = projection.data;
  const row = rows?.find((item) => String(item.domain || "").toUpperCase() === domain);
  if (!row) {
    if (projection.state === "LIVE" || projection.state === "STALE") {
      return card(domain.toLowerCase(), `${domain} DB`, "UNMEASURED", "No database status");
    }
    if (transportFailed(projection)) {
      return card(domain.toLowerCase(), `${domain} DB`, transportLabel(projection.state), projection.errorDetail || "database status unread");
    }
    return card(domain.toLowerCase(), `${domain} DB`, "UNMEASURED", "No database status");
  }
  const health = String(row.health || "UNMEASURED");
  const tables = row.tableCount;
  const detail = typeof tables === "number" ? `${tables} tables` : health === "MISSING" ? "file missing" : String(tables ?? health);
  const state = health === "OK" ? "HEALTHY" : health === "MISSING" ? "NOT CONFIGURED" : health;
  const displayState = projection.state === "STALE" && state === "HEALTHY" ? "STALE" : state;
  return card(domain.toLowerCase(), `${domain} DB`, displayState, detail);
}

function pickApiEvidence(
  liveness: ReadProjection<Record<string, unknown>>,
  health: ReadProjection<Record<string, unknown>>,
): ReadProjection<Record<string, unknown>> {
  if (liveness.state === "LIVE" || (liveness.data != null && (liveness.state === "STALE" || liveness.state === "TRANSPORT_ERROR"))) {
    return liveness;
  }
  if (liveness.state === "TRANSPORT_ERROR" || liveness.state === "UNAVAILABLE") {
    if (health.state === "LIVE" || health.data != null) return health;
    return liveness;
  }
  if (health.state === "LIVE" || health.data != null || transportFailed(health)) return health;
  return liveness.state !== "LOADING" ? liveness : health;
}

function mapApiCard(
  host: HostSnapshot,
  liveness: ReadProjection<Record<string, unknown>>,
  health: ReadProjection<Record<string, unknown>>,
): ServiceCardModel {
  if (host.state === "STOPPED") return card("api", "API", "STOPPED", "host stopped");

  const evidence = pickApiEvidence(liveness, health);
  const body = evidence.data;
  const ok = body?.ok === true;
  const livenessText = typeof body?.liveness === "string" ? body.liveness : null;

  if (ok) {
    const state = evidence.state === "STALE" ? "STALE" : "HEALTHY";
    return card("api", "API", state, livenessText || "liveness alive");
  }

  if (body != null && (evidence.state === "LIVE" || evidence.state === "STALE")) {
    if (body.ok === false) {
      return card("api", "API", evidence.state === "STALE" ? "STALE" : "DEGRADED", livenessText || "liveness did not report ok");
    }
    // Endpoint succeeded but the liveness/ok metric is missing.
    return card("api", "API", "UNMEASURED", "liveness metric missing");
  }

  if (transportFailed(evidence)) {
    return card("api", "API", transportLabel(evidence.state), evidence.errorDetail || "API transport failed");
  }

  if (host.state === "STARTING" || host.state === "PREFLIGHT") {
    return card("api", "API", "STARTING", host.message || "waiting for /api/host/liveness");
  }

  return card("api", "API", "UNMEASURED", "waiting for /api/host/liveness");
}

function mapWorkersCard(input: {
  host: HostSnapshot;
  supervisor: string | null;
  dashboard: ReadProjection<Record<string, unknown>>;
}): ServiceCardModel {
  const { host, supervisor, dashboard } = input;
  if (host.safeModeActive) {
    return card("workers", "Workers", "DISABLED BY SAFE MODE", "Safe Mode does not start the supervisor");
  }
  if (!host.workersExpected && (host.state === "RUNNING" || host.state === "DEGRADED" || host.state === "ATTACHED_EXTERNAL")) {
    return card("workers", "Workers", "NOT CONFIGURED", "Supervisor disabled in settings");
  }
  if (transportFailed(dashboard) && !supervisor && dashboard.data == null) {
    return card("workers", "Workers", transportLabel(dashboard.state), dashboard.errorDetail || "Worker Fabric unread");
  }
  const supervisorHealth = (supervisor || host.supervisorHealth || "").toUpperCase();
  if (supervisorHealth) {
    const state = supervisorHealth === "RUNNING" || supervisorHealth === "READY" ? "HEALTHY" : supervisorHealth;
    return card("workers", "Workers", state, `supervisor ${supervisorHealth}`);
  }
  if (transportFailed(dashboard)) {
    return card("workers", "Workers", transportLabel(dashboard.state), dashboard.errorDetail || "Worker Fabric unread");
  }
  return card("workers", "Workers", "UNMEASURED", "Worker Fabric unread");
}

export function modelStateFrom(source: Record<string, unknown>): { state: string; detail: string } {
  const nested = source.status;
  const cardBody =
    nested && typeof nested === "object" && !Array.isArray(nested)
      ? (nested as Record<string, unknown>)
      : source;
  const llm =
    source.llm && typeof source.llm === "object" && !Array.isArray(source.llm)
      ? (source.llm as Record<string, unknown>)
      : null;
  const body = llm ?? cardBody;

  if (body.available === true) {
    const active = body.activeModel ?? body.model;
    if (active == null || active === "" || active === false) {
      return { state: "IDLE", detail: "NO MODEL LOADED" };
    }
    return { state: "HEALTHY", detail: String(active) };
  }

  const hasModelsStatusShape =
    "availableModels" in body || "gatewayHealth" in body || "activeModel" in body || "loadedModels" in body;
  if (hasModelsStatusShape) {
    const gateway = typeof body.gatewayHealth === "string" ? body.gatewayHealth.toLowerCase() : "";
    const availableModels = typeof body.availableModels === "number" ? body.availableModels : null;
    const active = body.activeModel;
    const loaded = typeof body.loadedModels === "number" ? body.loadedModels : null;
    const runtime = typeof body.runtime === "string" ? body.runtime : null;
    const available = availableModels != null && availableModels > 0;
    const gatewayOk = gateway === "healthy" || gateway === "ok";

    if ((available || gatewayOk || body.available === true) && (active == null || active === "")) {
      return { state: "IDLE", detail: "NO MODEL LOADED" };
    }
    if (active != null && active !== "") {
      const state = gateway === "degraded" ? "DEGRADED" : gatewayOk || available ? "HEALTHY" : "HEALTHY";
      return { state, detail: String(active) };
    }
    if (gateway === "degraded") {
      return { state: "DEGRADED", detail: runtime || "gateway degraded" };
    }
    if (availableModels === 0 && (loaded === 0 || loaded == null)) {
      return { state: "IDLE", detail: "NO MODEL LOADED" };
    }
    if (gateway === "unknown" || gateway === "") {
      return { state: "UNMEASURED", detail: runtime || "model runtime unread" };
    }
    return { state: gateway.toUpperCase(), detail: runtime || gateway };
  }

  const ok = body.ok === true || body.reachable === true || body.status === "ok" || body.status === "healthy";
  const status = typeof body.status === "string" ? body.status : ok ? "HEALTHY" : null;
  if (ok) {
    const model = typeof body.model === "string" ? body.model : typeof body.detail === "string" ? body.detail : "HEALTHY";
    if (!body.model && !body.activeModel && (body.availableModels === 0 || body.loadedModels === 0)) {
      return { state: "IDLE", detail: "NO MODEL LOADED" };
    }
    return { state: "HEALTHY", detail: model };
  }
  if (status != null) {
    return { state: status.toUpperCase(), detail: typeof body.detail === "string" ? body.detail : status };
  }
  if (body.ok === false || body.reachable === false) {
    return { state: "UNAVAILABLE", detail: typeof body.detail === "string" ? body.detail : "model runtime unavailable" };
  }
  return { state: "UNMEASURED", detail: "model runtime unread" };
}

function mapModelCard(
  modelsStatus: ReadProjection<Record<string, unknown>>,
  health: ReadProjection<Record<string, unknown>>,
): ServiceCardModel {
  if (modelsStatus.state === "LIVE" || modelsStatus.data != null) {
    if (modelsStatus.data != null) {
      const mapped = modelStateFrom(modelsStatus.data);
      if (modelsStatus.state === "STALE" && mapped.state === "HEALTHY") {
        return card("model", "Model Runtime", "STALE", mapped.detail);
      }
      return card("model", "Model Runtime", mapped.state, mapped.detail);
    }
  }
  if (transportFailed(modelsStatus) && modelsStatus.data == null) {
    if (health.data != null) {
      const llm = health.data.llm;
      if (llm && typeof llm === "object") {
        const mapped = modelStateFrom({ llm: llm as Record<string, unknown> });
        return card("model", "Model Runtime", mapped.state, mapped.detail);
      }
      if (health.state === "LIVE") {
        return card("model", "Model Runtime", "UNMEASURED", "model runtime unread");
      }
    }
    return card("model", "Model Runtime", transportLabel(modelsStatus.state), modelsStatus.errorDetail || "model status unread");
  }
  if (health.data != null) {
    const llm = health.data.llm;
    if (llm && typeof llm === "object") {
      const mapped = modelStateFrom({ llm: llm as Record<string, unknown> });
      return card("model", "Model Runtime", mapped.state, mapped.detail);
    }
    if (health.state === "LIVE" || health.state === "STALE") {
      return card("model", "Model Runtime", "UNMEASURED", "model runtime unread");
    }
  }
  if (transportFailed(health)) {
    return card("model", "Model Runtime", transportLabel(health.state), health.errorDetail || "model runtime unread");
  }
  return card("model", "Model Runtime", "UNMEASURED", "model runtime unread");
}

function mapQueueCard(
  queueDepth: number | null,
  queueProjection: ReadProjection<unknown> | null,
): ServiceCardModel {
  if (typeof queueDepth === "number") {
    return card("queue", "Queue / Jobs", "HEALTHY", `${queueDepth} queued`);
  }
  if (queueProjection && transportFailed(queueProjection)) {
    return card("queue", "Queue / Jobs", transportLabel(queueProjection.state), queueProjection.errorDetail || "queue depth unread");
  }
  return card("queue", "Queue / Jobs", "UNMEASURED", "queue depth unread");
}

export function mapServices(input: {
  host: HostSnapshot;
  liveness?: ReadProjection<Record<string, unknown>> | Record<string, unknown> | null;
  health?: ReadProjection<Record<string, unknown>> | Record<string, unknown> | null;
  modelsStatus?: ReadProjection<Record<string, unknown>> | Record<string, unknown> | null;
  databases?: ReadProjection<Array<Record<string, unknown>>> | Array<Record<string, unknown>> | null;
  dashboard?: ReadProjection<Record<string, unknown>> | Record<string, unknown> | null;
  nativeStatus: string | null;
  nativeDetail: string | null;
  nativeProjection?: ReadProjection<unknown> | null;
  supervisor: string | null;
  queueDepth: number | null;
  queueProjection?: ReadProjection<unknown> | null;
  pythonVersion: string | null;
}): ServiceCardModel[] {
  const liveness = asProjection(input.liveness);
  const health = asProjection(input.health);
  const modelsStatus = asProjection(input.modelsStatus);
  const databases = asProjection(input.databases);
  const dashboard = asProjection(input.dashboard);

  const nativeProjection = input.nativeProjection ?? null;
  const native = (input.nativeStatus || "").toUpperCase();
  let nativeState: string;
  let nativeDetail: string;
  if (native) {
    nativeState = native === "AVAILABLE" ? "HEALTHY" : native === "BUILD_MISSING" ? "BUILD MISSING" : native;
    nativeDetail = input.nativeDetail || native;
  } else if (nativeProjection && transportFailed(nativeProjection)) {
    nativeState = transportLabel(nativeProjection.state);
    nativeDetail = nativeProjection.errorDetail || "native status unread";
  } else {
    nativeState = "UNMEASURED";
    nativeDetail = input.nativeDetail || "native status unread";
  }

  const pythonLive =
    input.host.state === "RUNNING" || input.host.state === "DEGRADED" || input.host.state === "ATTACHED_EXTERNAL";
  const pythonState = pythonLive ? (input.pythonVersion ? "HEALTHY" : "UNMEASURED") : "STOPPED";

  return [
    mapApiCard(input.host, liveness, health),
    mapWorkersCard({ host: input.host, supervisor: input.supervisor, dashboard }),
    card("native", "Native Data Plane", nativeState, nativeDetail),
    card("python", "Python Runtime", pythonState, input.pythonVersion || "version unread"),
    dbCard(databases, "CONTROL"),
    dbCard(databases, "KNOWLEDGE"),
    dbCard(databases, "MARKET"),
    mapModelCard(modelsStatus, health),
    mapQueueCard(input.queueDepth, input.queueProjection ?? health),
  ];
}

export function countHealthy(cards: ServiceCardModel[]): string {
  const known = cards.filter((card) => card.tone !== "muted");
  if (known.length === 0) return "UNMEASURED";
  const ok = cards.filter((card) => card.tone === "ok").length;
  return `${ok}/${cards.length}`;
}
