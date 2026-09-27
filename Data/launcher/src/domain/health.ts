import type { ServiceCardModel, ServiceTone } from "../types/backend";
import type { HostSnapshot } from "../types/host";

function card(id: string, name: string, state: string, detail: string): ServiceCardModel {
  return { id, name, state, detail, tone: toneFor(state) };
}

export function toneFor(state: string): ServiceTone {
  const token = state.toUpperCase().replace(/\s+/g, "_");
  if (["HEALTHY", "READY", "OK", "AVAILABLE", "RUNNING", "PASS"].includes(token)) return "ok";
  if (["DEGRADED", "BUSY", "STARTING", "PARTIAL", "DISABLED"].includes(token)) return "warn";
  if (["FAILED", "ERROR", "MISSING", "BUILD_MISSING", "UNAVAILABLE"].includes(token)) return "bad";
  return "muted";
}

function dbCard(rows: Array<Record<string, unknown>> | null, domain: string): ServiceCardModel {
  const row = rows?.find((item) => String(item.domain || "").toUpperCase() === domain);
  if (!row) return card(domain.toLowerCase(), `${domain} DB`, "UNMEASURED", "No database status");
  const health = String(row.health || "UNMEASURED");
  const tables = row.tableCount;
  const detail = typeof tables === "number" ? `${tables} tables` : health === "MISSING" ? "file missing" : String(tables ?? health);
  const state = health === "OK" ? "HEALTHY" : health === "MISSING" ? "NOT CONFIGURED" : health;
  return card(domain.toLowerCase(), `${domain} DB`, state, detail);
}

export function mapServices(input: {
  host: HostSnapshot;
  health: Record<string, unknown> | null;
  databases: Array<Record<string, unknown>> | null;
  nativeStatus: string | null;
  nativeDetail: string | null;
  supervisor: string | null;
  queueDepth: number | null;
  pythonVersion: string | null;
}): ServiceCardModel[] {
  const healthOk = input.health?.ok === true;
  const liveness = typeof input.health?.liveness === "string" ? input.health.liveness : null;
  const apiState = input.host.state === "STOPPED" ? "STOPPED" : healthOk ? "HEALTHY" : input.health ? "DEGRADED" : "UNMEASURED";
  const apiDetail = healthOk ? liveness || "liveness alive" : input.health ? "health did not report ok" : "waiting for /api/health";

  const supervisor = (input.supervisor || input.host.supervisorHealth || "").toUpperCase();
  let workersState = "UNMEASURED";
  let workersDetail = "Worker Fabric unread";
  if (input.host.safeModeActive) {
    workersState = "DISABLED";
    workersDetail = "Safe Mode does not start the supervisor";
  } else if (!input.host.workersExpected && input.host.state === "RUNNING") {
    workersState = "NOT CONFIGURED";
    workersDetail = "Supervisor disabled in settings";
  } else if (supervisor) {
    workersState = supervisor === "RUNNING" || supervisor === "READY" ? "HEALTHY" : supervisor;
    workersDetail = `supervisor ${supervisor}`;
  }

  const native = (input.nativeStatus || "UNMEASURED").toUpperCase();
  const nativeState = native === "AVAILABLE" ? "HEALTHY" : native === "BUILD_MISSING" ? "BUILD MISSING" : native;
  const llm = input.health?.llm;
  const modelState =
    input.health && llm && typeof llm === "object"
      ? modelStateFrom(llm as Record<string, unknown>)
      : { state: "UNMEASURED", detail: "model runtime unread" };
  const queueState = input.queueDepth == null ? "UNMEASURED" : "HEALTHY";
  const queueDetail = input.queueDepth == null ? "queue depth unread" : `${input.queueDepth} queued`;

  return [
    card("api", "API", apiState, apiDetail),
    card("workers", "Workers", workersState, workersDetail),
    card("native", "Native Data Plane", nativeState, input.nativeDetail || native),
    card(
      "python",
      "Python Runtime",
      input.host.state === "RUNNING" || input.host.state === "DEGRADED" || input.host.state === "ATTACHED_EXTERNAL"
        ? input.pythonVersion
          ? "HEALTHY"
          : "UNMEASURED"
        : "STOPPED",
      input.pythonVersion || "version unread",
    ),
    dbCard(input.databases, "CONTROL"),
    dbCard(input.databases, "KNOWLEDGE"),
    dbCard(input.databases, "MARKET"),
    card("model", "Model Runtime", modelState.state, modelState.detail),
    card("queue", "Queue / Jobs", queueState, queueDetail),
  ];
}

function modelStateFrom(llm: Record<string, unknown>): { state: string; detail: string } {
  const ok = llm.ok === true || llm.reachable === true || llm.status === "ok" || llm.status === "healthy";
  const status = typeof llm.status === "string" ? llm.status : ok ? "HEALTHY" : "UNAVAILABLE";
  const model = typeof llm.model === "string" ? llm.model : typeof llm.detail === "string" ? llm.detail : status;
  return { state: ok ? "HEALTHY" : status.toUpperCase(), detail: model };
}

export function countHealthy(cards: ServiceCardModel[]): string {
  const known = cards.filter((card) => card.tone !== "muted");
  if (known.length === 0) return "UNMEASURED";
  const ok = cards.filter((card) => card.tone === "ok").length;
  return `${ok}/${cards.length}`;
}
