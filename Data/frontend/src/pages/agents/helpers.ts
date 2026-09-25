import type {
  AgentDefinition,
  AgentEvent,
  AgentMission,
  CapabilityListItem,
  OrchestratorConfig,
  SystemArchitectureEntry,
} from "../../types/api";
import { ApiError } from "../../api/client";
import { isActiveJobStatus } from "../../lib/jobStatus";

export function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export const AGENT_KINDS = [
  "generic",
  "coding",
  "research",
  "specialist",
  "orchestrator",
  "trading",
] as const;

export const ORCH_STRATEGIES = ["sequential", "parallel_bounded"] as const;
export const ORCH_FAILURE_STRATEGIES = ["fail_fast", "continue"] as const;
export const APPROVAL_MODES = ["inherit", "auto_low_risk", "manual", "hybrid"] as const;
export const DATASET_ACCESS_POLICIES = ["none", "read", "read_write", "controlled"] as const;
export const MEMORY_POLICIES = ["default", "session", "persistent", "none"] as const;

export type AgentEditorDraft = {
  name: string;
  kind: string;
  description: string;
  role: string;
  enabled: boolean;
  modelRef: string;
  systemPolicy: string;
  capabilities: string[];
  knowledgeSources: string[];
  memoryPolicy: string;
  datasetAccess: string;
  approvalMode: string;
  autonomy: number;
  maxConcurrency: number;
  timeoutS: string;
  maxRetries: number;
  tokenBudget: string;
  tags: string;
  memberAgentIds: string[];
  strategy: string;
  maxDelegationDepth: number;
  parallelismLimit: number;
  failureStrategy: string;
  verificationRequired: boolean;
  aggregationAgentId: string;
  defaultModelFallback: string;
  approvalEscalation: string;
};

export function emptyEditorDraft(partial?: Partial<AgentEditorDraft>): AgentEditorDraft {
  return {
    name: "",
    kind: "research",
    description: "",
    role: "",
    enabled: true,
    modelRef: "",
    systemPolicy: "",
    capabilities: [],
    knowledgeSources: [],
    memoryPolicy: "default",
    datasetAccess: "none",
    approvalMode: "inherit",
    autonomy: 50,
    maxConcurrency: 1,
    timeoutS: "",
    maxRetries: 0,
    tokenBudget: "",
    tags: "",
    memberAgentIds: [],
    strategy: "sequential",
    maxDelegationDepth: 3,
    parallelismLimit: 2,
    failureStrategy: "fail_fast",
    verificationRequired: false,
    aggregationAgentId: "",
    defaultModelFallback: "",
    approvalEscalation: "inherit",
    ...partial,
  };
}

export function draftFromAgent(agent: AgentDefinition): AgentEditorDraft {
  const orch = agent.orchestrator;
  return emptyEditorDraft({
    name: agent.name,
    kind: String(agent.kind),
    description: agent.description || "",
    role: agent.role || "",
    enabled: agent.enabled,
    modelRef: agent.modelRef || "",
    systemPolicy: agent.systemPolicy || "",
    capabilities: [...(agent.capabilities || [])],
    knowledgeSources: [...(agent.knowledgeSources || [])],
    memoryPolicy: agent.memoryPolicy || "default",
    datasetAccess: agent.datasetAccess || "none",
    approvalMode: agent.approvalMode || "inherit",
    autonomy: agent.autonomy ?? 50,
    maxConcurrency: agent.maxConcurrency ?? 1,
    timeoutS: agent.timeoutS != null ? String(agent.timeoutS) : "",
    maxRetries: agent.maxRetries ?? 0,
    tokenBudget: agent.tokenBudget != null ? String(agent.tokenBudget) : "",
    tags: (agent.tags || []).join(", "),
    memberAgentIds: orch?.memberAgentIds ? [...orch.memberAgentIds] : [],
    strategy: orch?.strategy || "sequential",
    maxDelegationDepth: orch?.maxDelegationDepth ?? 3,
    parallelismLimit: orch?.parallelismLimit ?? 2,
    failureStrategy: orch?.failureStrategy || "fail_fast",
    verificationRequired: Boolean(orch?.verificationRequired),
    aggregationAgentId: orch?.aggregationAgentId || "",
    defaultModelFallback: orch?.defaultModelFallback || "",
    approvalEscalation: orch?.approvalEscalation || "inherit",
  });
}

export function draftToCreatePayload(draft: AgentEditorDraft) {
  const tags = draft.tags
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const timeoutS = draft.timeoutS.trim() ? Number(draft.timeoutS) : null;
  const tokenBudget = draft.tokenBudget.trim() ? Number(draft.tokenBudget) : null;
  const payload: Record<string, unknown> = {
    name: draft.name.trim(),
    kind: draft.kind,
    description: draft.description.trim(),
    role: draft.role.trim(),
    enabled: draft.enabled,
    modelRef: draft.modelRef.trim() || null,
    systemPolicy: draft.systemPolicy.trim() || null,
    capabilities: draft.capabilities,
    knowledgeSources: draft.knowledgeSources,
    memoryPolicy: draft.memoryPolicy,
    datasetAccess: draft.datasetAccess,
    approvalMode: draft.approvalMode,
    autonomy: Math.max(0, Math.min(100, Number(draft.autonomy) || 0)),
    maxConcurrency: Math.max(1, Math.min(32, Number(draft.maxConcurrency) || 1)),
    timeoutS: Number.isFinite(timeoutS as number) ? timeoutS : null,
    maxRetries: Math.max(0, Math.min(10, Number(draft.maxRetries) || 0)),
    tokenBudget: Number.isFinite(tokenBudget as number) ? tokenBudget : null,
    tags,
  };
  if (draft.kind === "orchestrator") {
    payload.orchestrator = {
      memberAgentIds: draft.memberAgentIds,
      strategy: draft.strategy,
      maxDelegationDepth: draft.maxDelegationDepth,
      parallelismLimit: draft.parallelismLimit,
      failureStrategy: draft.failureStrategy,
      verificationRequired: draft.verificationRequired,
      aggregationAgentId: draft.aggregationAgentId.trim() || null,
      defaultModelFallback: draft.defaultModelFallback.trim() || null,
      approvalEscalation: draft.approvalEscalation,
    } satisfies Partial<OrchestratorConfig>;
  }
  return payload;
}

export function healthLabel(agent: AgentDefinition): string {
  const h = String(agent.health || "").toLowerCase();
  if (agent.archived || h === "archived") return "Archived";
  if (!agent.enabled || h === "disabled") return "Offline";
  if (h === "busy") return "Busy";
  if (h === "idle") return "Idle";
  if (h === "error") return "Error";
  if (h === "unknown") return "Unknown";
  return "Online";
}

export function statusTone(label: string): string {
  if (label === "Online" || label === "Idle") return "ok";
  if (label === "Busy") return "warn";
  if (label === "Error") return "warn";
  if (label === "Archived") return "muted";
  return "off";
}

export function agentIconKind(agent: AgentDefinition): string {
  const kind = String(agent.kind).toLowerCase();
  if (kind === "research") return "research";
  if (kind === "coding") return "coding";
  if (kind === "orchestrator") return "planner";
  if (agent.tags.includes("trading") || agent.name.toLowerCase().includes("trading")) return "trading";
  if (agent.tags.includes("media") || agent.name.toLowerCase().includes("media")) return "media";
  if (agent.tags.includes("memory") || agent.name.toLowerCase().includes("memory")) return "memory";
  if (agent.tags.includes("review") || agent.name.toLowerCase().includes("critic")) return "critic";
  if (
    agent.tags.includes("datasets") ||
    agent.tags.includes("learning") ||
    agent.name.toLowerCase().includes("dataset learning") ||
    String((agent.metadata as { systemKey?: string } | undefined)?.systemKey || "") ===
      "dataset_learning"
  ) {
    return "research";
  }
  return "execution";
}

export type RosterFilters = {
  query: string;
  roleFilter: string;
  statusFilter: string;
  kindFilter: string;
  showArchived: boolean;
  originFilter?: string;
  entityTypeFilter?: string;
};

export function agentOrigin(agent: AgentDefinition): "system" | "user" {
  if (agent.origin === "system" || agent.origin === "user") return agent.origin;
  const key = String(agent.systemKey || (agent.metadata as { systemKey?: string } | undefined)?.systemKey || "").trim();
  return key ? "system" : "user";
}

export function agentEntityType(agent: AgentDefinition): "agent" | "orchestrator" | "architecture" {
  if (agent.entityType === "agent" || agent.entityType === "orchestrator" || agent.entityType === "architecture") {
    return agent.entityType;
  }
  return String(agent.kind) === "orchestrator" ? "orchestrator" : "agent";
}

export function isArchitectureEntry(entry: {
  entityType?: string;
  agentId?: string;
}): boolean {
  return entry.entityType === "architecture" || String(entry.agentId || "").startsWith("system:architecture:");
}

export function rosterEntryId(entry: {
  id?: string;
  agentId?: string;
}): string {
  return String(entry.id || entry.agentId || "");
}

export function filterRoster(agents: AgentDefinition[], filters: RosterFilters): AgentDefinition[] {
  const q = filters.query.trim().toLowerCase();
  const originFilter = filters.originFilter || "ALL";
  const entityFilter = filters.entityTypeFilter || "ALL TYPES";
  return agents.filter((agent) => {
    if (!filters.showArchived && agent.archived) return false;
    if (filters.kindFilter === "__archived_only__" && !agent.archived) return false;
    if (
      filters.kindFilter &&
      filters.kindFilter !== "All Kinds" &&
      filters.kindFilter !== "__archived_only__" &&
      String(agent.kind) !== filters.kindFilter
    ) {
      return false;
    }
    const origin = agentOrigin(agent);
    if (originFilter === "SYSTEM" && origin !== "system") return false;
    if (originFilter === "USER" && origin !== "user") return false;
    const entity = agentEntityType(agent);
    if (entityFilter === "AGENTS" && entity !== "agent") return false;
    if (entityFilter === "ORCHESTRATORS" && entity !== "orchestrator") return false;
    if (entityFilter === "ARCHITECTURE" && entity !== "architecture") return false;
    if (q) {
      const hay = [
        agent.name,
        agent.role,
        agent.kind,
        agent.description,
        agent.systemKey || "",
        agent.tags.join(" "),
        origin,
        entity,
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    const label = healthLabel(agent);
    if (filters.statusFilter !== "All Status" && label !== filters.statusFilter) return false;
    if (filters.roleFilter !== "All Roles") {
      const role = (agent.role || "").toLowerCase();
      if (role !== filters.roleFilter.toLowerCase()) return false;
    }
    return true;
  });
}

export function deriveRoleOptions(agents: AgentDefinition[]): string[] {
  const roles = new Set<string>();
  for (const a of agents) {
    const role = (a.role || "").trim();
    if (role) roles.add(role);
  }
  return Array.from(roles).sort((a, b) => a.localeCompare(b));
}

export function deriveStatusOptions(agents: AgentDefinition[]): string[] {
  const labels = new Set(agents.map((a) => healthLabel(a)));
  return Array.from(labels).sort((a, b) => a.localeCompare(b));
}

export type MissionTab =
  | "All Tasks"
  | "Running"
  | "Queued"
  | "Completed"
  | "Failed"
  | "Cancelled"
  | "Interrupted";

export function filterMissions(missions: AgentMission[], tab: MissionTab): AgentMission[] {
  if (tab === "All Tasks") return missions;
  if (tab === "Completed") return missions.filter((m) => m.status === "completed");
  if (tab === "Queued") return missions.filter((m) => m.status === "queued");
  if (tab === "Failed") return missions.filter((m) => m.status === "failed" || m.status === "disabled");
  if (tab === "Cancelled") return missions.filter((m) => m.status === "cancelled" || m.status === "cancelling");
  if (tab === "Interrupted") return missions.filter((m) => m.status === "interrupted");
  return missions.filter((m) => isActiveJobStatus(m.status) && m.status !== "queued");
}

export function missionTabCount(missions: AgentMission[], tab: MissionTab): number {
  return filterMissions(missions, tab).length;
}

export type LogFilter = "All" | "System" | "Agents" | "Tasks" | "Warnings" | "Errors";

export function filterEvents(
  events: AgentEvent[],
  logFilter: LogFilter,
  opts?: { agentId?: string; missionId?: string },
): AgentEvent[] {
  let list = events;
  if (opts?.agentId) list = list.filter((e) => e.agentId === opts.agentId);
  if (opts?.missionId) list = list.filter((e) => e.missionId === opts.missionId);
  if (logFilter === "All") return list;
  const map: Record<string, string[]> = {
    System: ["system"],
    Agents: ["agents"],
    Tasks: ["tasks"],
    Warnings: ["warn", "warning"],
    Errors: ["errors", "error"],
  };
  const wanted = map[logFilter] ?? [];
  return list.filter((e) => wanted.includes(e.category) || wanted.includes(e.level));
}

/** Assigned capabilities only — never substitute the global registry. */
export function assignedCapabilityCards(
  agent: AgentDefinition | undefined,
  registry: CapabilityListItem[],
): Array<{ id: string; title: string; desc: string; available?: boolean }> {
  if (!agent || agent.capabilities.length === 0) return [];
  const byId = new Map(
    registry.map((c) => {
      const id = typeof c.id === "string" ? c.id : "";
      return [id, c] as const;
    }),
  );
  return agent.capabilities.map((id) => {
    const cap = byId.get(id);
    const title =
      cap && typeof cap.name === "string" && cap.name ? cap.name : id;
    const desc =
      cap && typeof cap.description === "string" && cap.description
        ? cap.description
        : "Assigned on agent definition — executed via ExecutionGateway";
    return {
      id,
      title,
      desc,
      available: cap?.available,
    };
  });
}

export function networkEdgesFromAgents(
  agents: AgentDefinition[],
): Array<{ from: string; to: string; active: boolean }> {
  const byId = Object.fromEntries(agents.map((a) => [a.agentId, a]));
  const edges: Array<{ from: string; to: string; active: boolean }> = [];
  for (const agent of agents) {
    if (agent.kind !== "orchestrator" || !agent.orchestrator) continue;
    for (const memberId of agent.orchestrator.memberAgentIds) {
      const member = byId[memberId];
      edges.push({
        from: agent.agentId,
        to: memberId,
        active: member ? healthLabel(member) === "Busy" : false,
      });
    }
  }
  return edges;
}

export type NetworkNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  hub: boolean;
};

/** Deterministic multi-orchestrator layout — does not invent edges. */
export function layoutNetworkNodes(
  agents: AgentDefinition[],
  edges: Array<{ from: string; to: string; active: boolean }>,
): NetworkNode[] {
  const visible = agents.filter((a) => !a.archived);
  const orchIds = new Set(
    visible.filter((a) => a.kind === "orchestrator").map((a) => a.agentId),
  );
  const connected = new Set<string>();
  for (const e of edges) {
    connected.add(e.from);
    connected.add(e.to);
  }
  const hubs = visible.filter((a) => orchIds.has(a.agentId));
  const workers = visible.filter((a) => !orchIds.has(a.agentId) && connected.has(a.agentId));
  const isolates = visible.filter(
    (a) => !orchIds.has(a.agentId) && !connected.has(a.agentId),
  );

  const nodes: NetworkNode[] = [];
  const width = 520;
  const hubY = 48;
  hubs.forEach((h, i) => {
    const x =
      hubs.length === 1 ? width / 2 : 60 + (i * (width - 120)) / Math.max(1, hubs.length - 1);
    nodes.push({ id: h.agentId, label: h.name, x, y: hubY, hub: true });
  });

  const memberRow = [...workers, ...isolates.slice(0, Math.max(0, 24 - workers.length))];
  const cols = Math.min(6, Math.max(1, memberRow.length));
  memberRow.forEach((m, i) => {
    const row = Math.floor(i / cols);
    const col = i % cols;
    const x = 50 + (col * (width - 100)) / Math.max(1, cols - 1 || 1);
    const y = 130 + row * 55;
    nodes.push({ id: m.agentId, label: m.name, x: cols === 1 ? width / 2 : x, y, hub: false });
  });
  return nodes;
}

export function activeMissionsForAgent(
  missions: AgentMission[],
  agentId: string,
): AgentMission[] {
  return missions.filter((m) => m.agentId === agentId && isActiveJobStatus(m.status));
}

export function childMissionsOf(
  missions: AgentMission[],
  parentId: string,
): AgentMission[] {
  return missions.filter((m) => m.parentMissionId === parentId);
}

export function canLaunchAgent(agent: AgentDefinition | undefined, agentsEnabled: boolean | undefined): {
  ok: boolean;
  reason?: string;
} {
  if (!agent) return { ok: false, reason: "Select an agent first" };
  if (isArchitectureEntry(agent)) {
    return { ok: false, reason: "Architecture components are not launchable missions" };
  }
  if (agent.executable === false) {
    return { ok: false, reason: "This SYSTEM component has no execution contract" };
  }
  if (agent.archived) return { ok: false, reason: "Cannot launch archived agent" };
  if (!agent.enabled) return { ok: false, reason: "Agent is disabled" };
  if (agentsEnabled === false) return { ok: false, reason: "Agents feature flag is OFF" };
  return { ok: true };
}

export function isSystemProtected(agent: AgentDefinition | undefined): boolean {
  if (!agent) return false;
  if (agent.mutable === false) return true;
  return agentOrigin(agent) === "system";
}

export function validateEditorDraft(
  draft: AgentEditorDraft,
  opts?: { editingId?: string },
): string | null {
  if (!draft.name.trim()) return "Agent name is required";
  if (!AGENT_KINDS.includes(draft.kind as (typeof AGENT_KINDS)[number])) {
    return `Unsupported kind: ${draft.kind}`;
  }
  if (draft.kind === "orchestrator") {
    if (!ORCH_STRATEGIES.includes(draft.strategy as (typeof ORCH_STRATEGIES)[number])) {
      return "Unsupported orchestrator strategy";
    }
    if (
      !ORCH_FAILURE_STRATEGIES.includes(
        draft.failureStrategy as (typeof ORCH_FAILURE_STRATEGIES)[number],
      )
    ) {
      return "Unsupported failure strategy";
    }
    if (opts?.editingId && draft.memberAgentIds.includes(opts.editingId)) {
      return "Orchestrator cannot include itself";
    }
    const seen = new Set<string>();
    for (const id of draft.memberAgentIds) {
      if (seen.has(id)) return `Duplicate member: ${id}`;
      seen.add(id);
    }
  }
  return null;
}

/* ---------- Agents dashboard (SCREEN 1) helpers ---------- */

export const TEAM_BUCKETS = [
  "Research",
  "Development",
  "Trading",
  "Planning",
  "Risk",
  "Memory",
  "Evaluation",
  "Vision",
  "Other",
] as const;

export type TeamBucket = (typeof TEAM_BUCKETS)[number];

/** Mirrors `team_bucket_for_agent` in Data/modules/agents/dashboard.py — keep in sync. */
export function teamBucketForAgent(agent: AgentDefinition): TeamBucket {
  const kind = String(agent.kind || "").toLowerCase();
  const role = String(agent.role || "").toLowerCase();
  const name = String(agent.name || "").toLowerCase();
  const tags = Array.from(new Set((agent.tags || []).map((t) => String(t).toLowerCase()))).sort();
  const systemKey = String(
    agent.systemKey || (agent.metadata as { systemKey?: string } | undefined)?.systemKey || "",
  ).toLowerCase();
  const blob = [kind, role, name, systemKey, tags.join(" ")].join(" ");

  if (kind === "research" || blob.includes("research") || systemKey === "research") return "Research";
  if (
    kind === "coding" ||
    blob.includes("coding") ||
    blob.includes("development") ||
    systemKey === "coding"
  ) {
    return "Development";
  }
  if (kind === "trading" || blob.includes("trading") || blob.includes("trade")) return "Trading";
  if (kind === "orchestrator" || blob.includes("plan") || systemKey === "planner") return "Planning";
  if (
    blob.includes("risk") ||
    blob.includes("critic") ||
    blob.includes("guard") ||
    systemKey === "critic"
  ) {
    return "Risk";
  }
  if (blob.includes("memory")) return "Memory";
  if (blob.includes("evaluat") || tags.includes("qa") || tags.includes("review")) return "Evaluation";
  if (blob.includes("vision") || blob.includes("media") || blob.includes("image")) return "Vision";
  return "Other";
}

/** Compact human duration; null/invalid → em dash (never a fabricated zero). */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h}h ${mm}m` : `${h}h`;
}

export function formatSyncAge(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.round((nowMs - t) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function formatPct(ratio: number | null | undefined, digits = 1): string {
  if (ratio == null || !Number.isFinite(ratio)) return "—";
  return `${(ratio * 100).toFixed(digits)}%`;
}

export type AgentMissionStats = {
  total: number;
  active: number;
  completed: number;
  failed: number;
  successRate: number | null;
  avgDurationMs: number | null;
};

export function agentMissionStats(missions: AgentMission[], agentId: string): AgentMissionStats {
  let total = 0;
  let active = 0;
  let completed = 0;
  let failed = 0;
  const durations: number[] = [];
  for (const m of missions) {
    if (m.agentId !== agentId) continue;
    total += 1;
    if (isActiveJobStatus(m.status)) active += 1;
    if (m.status === "completed") {
      completed += 1;
      if (m.startedAt && m.finishedAt) {
        const d = Date.parse(m.finishedAt) - Date.parse(m.startedAt);
        if (Number.isFinite(d) && d >= 0) durations.push(d);
      }
    } else if (m.status === "failed") {
      failed += 1;
    }
  }
  const elig = completed + failed;
  return {
    total,
    active,
    completed,
    failed,
    successRate: elig ? completed / elig : null,
    avgDurationMs: durations.length
      ? durations.reduce((a, b) => a + b, 0) / durations.length
      : null,
  };
}

/** Orchestrators (fleet) that list the agent as a member — from real memberAgentIds. */
export function orchestratorsForMember(
  agents: AgentDefinition[],
  agentId: string,
): AgentDefinition[] {
  return agents.filter(
    (a) =>
      !a.archived &&
      a.kind === "orchestrator" &&
      Boolean(a.orchestrator?.memberAgentIds.includes(agentId)),
  );
}

export type ArchitectureNode = {
  id: string;
  label: string;
  sublabel: string;
  status: string;
  source: "fleet" | "system";
  team: TeamBucket | null;
  memberIds: string[];
};

export type ArchitectureTiers = {
  orchestrators: ArchitectureNode[];
  specialists: ArchitectureNode[];
  hiddenOrchestrators: number;
  hiddenSpecialists: number;
};

/**
 * Hierarchy tiers for the architecture diagram. Orchestrators = fleet orchestrators
 * plus SystemInventory orchestrators; specialists = non-orchestrator fleet agents.
 * Membership edges come only from orchestrator.memberAgentIds.
 */
export function buildArchitectureTiers(
  agents: AgentDefinition[],
  systemEntries: SystemArchitectureEntry[],
  opts?: { maxOrchestrators?: number; maxSpecialists?: number },
): ArchitectureTiers {
  const maxO = opts?.maxOrchestrators ?? 4;
  const maxS = opts?.maxSpecialists ?? 8;
  const live = agents.filter((a) => !a.archived);
  const fleetOrch: ArchitectureNode[] = live
    .filter((a) => a.kind === "orchestrator")
    .map((a) => ({
      id: a.agentId,
      label: a.name,
      sublabel: a.role || "Orchestrator",
      status: healthLabel(a),
      source: "fleet" as const,
      team: teamBucketForAgent(a),
      memberIds: [...(a.orchestrator?.memberAgentIds ?? [])],
    }));
  const sysOrch: ArchitectureNode[] = systemEntries
    .filter((e) => e.entityType === "orchestrator")
    .map((e) => ({
      id: e.id,
      label: e.name,
      sublabel: e.runtimeKind || "system",
      status: e.status || "unknown",
      source: "system" as const,
      team: null,
      memberIds: [],
    }));
  const allOrch = [...fleetOrch, ...sysOrch];
  const teamOrder = new Map<string, number>(TEAM_BUCKETS.map((t, i) => [t, i]));
  const specialistsAll: ArchitectureNode[] = live
    .filter((a) => a.kind !== "orchestrator")
    .map((a) => ({
      id: a.agentId,
      label: a.name,
      sublabel: a.role || String(a.kind),
      status: healthLabel(a),
      source: "fleet" as const,
      team: teamBucketForAgent(a),
      memberIds: [],
    }))
    .sort(
      (x, y) =>
        (teamOrder.get(x.team ?? "Other") ?? 99) - (teamOrder.get(y.team ?? "Other") ?? 99) ||
        x.label.localeCompare(y.label),
    );
  return {
    orchestrators: allOrch.slice(0, maxO),
    specialists: specialistsAll.slice(0, maxS),
    hiddenOrchestrators: Math.max(0, allOrch.length - maxO),
    hiddenSpecialists: Math.max(0, specialistsAll.length - maxS),
  };
}

export function groupSystemEntriesByRuntime(
  entries: SystemArchitectureEntry[],
): Array<{ runtimeKind: string; entries: SystemArchitectureEntry[] }> {
  const map = new Map<string, SystemArchitectureEntry[]>();
  for (const e of entries) {
    const key = e.runtimeKind || e.entityType || "other";
    const list = map.get(key) ?? [];
    list.push(e);
    map.set(key, list);
  }
  return Array.from(map.entries())
    .map(([runtimeKind, list]) => ({ runtimeKind, entries: list }))
    .sort((a, b) => a.runtimeKind.localeCompare(b.runtimeKind));
}

export type DashboardFilters = {
  team: string;
  status: string;
  role: string;
  model: string;
  environment: string;
  query?: string;
};

export const ALL_TEAMS = "All Teams";
export const ALL_STATUS = "All Status";
export const ALL_ROLES = "All Roles";
export const ALL_MODELS = "All Models";
export const ALL_ENVIRONMENTS = "All Environments";
export const MODEL_UNSET = "(inherit / unset)";

export function emptyDashboardFilters(): DashboardFilters {
  return {
    team: ALL_TEAMS,
    status: ALL_STATUS,
    role: ALL_ROLES,
    model: ALL_MODELS,
    environment: ALL_ENVIRONMENTS,
    query: "",
  };
}

/** Environment = ownership plane: SYSTEM (backend-seeded) vs USER (operator-created). */
export function agentEnvironment(agent: AgentDefinition): "System" | "User" | "Architecture" {
  if (isArchitectureEntry(agent)) return "Architecture";
  return agentOrigin(agent) === "system" ? "System" : "User";
}

export function agentModelLabel(agent: AgentDefinition): string {
  return (agent.modelRef || "").trim() || MODEL_UNSET;
}

export function deriveTeamOptions(agents: AgentDefinition[]): string[] {
  const present = new Set(agents.map((a) => teamBucketForAgent(a)));
  return TEAM_BUCKETS.filter((t) => present.has(t));
}

export function deriveModelOptions(agents: AgentDefinition[]): string[] {
  return Array.from(new Set(agents.map(agentModelLabel))).sort((a, b) => a.localeCompare(b));
}

export function deriveEnvironmentOptions(agents: AgentDefinition[]): string[] {
  return Array.from(new Set(agents.map(agentEnvironment))).sort((a, b) => a.localeCompare(b));
}

export function filterDashboardAgents(
  agents: AgentDefinition[],
  filters: DashboardFilters,
): AgentDefinition[] {
  const q = (filters.query || "").trim().toLowerCase();
  return agents.filter((agent) => {
    if (filters.team !== ALL_TEAMS && teamBucketForAgent(agent) !== filters.team) return false;
    if (filters.status !== ALL_STATUS && healthLabel(agent) !== filters.status) return false;
    if (
      filters.role !== ALL_ROLES &&
      (agent.role || "").toLowerCase() !== filters.role.toLowerCase()
    ) {
      return false;
    }
    if (filters.model !== ALL_MODELS && agentModelLabel(agent) !== filters.model) return false;
    if (filters.environment !== ALL_ENVIRONMENTS && agentEnvironment(agent) !== filters.environment) {
      return false;
    }
    if (q) {
      const hay = [agent.name, agent.role, agent.kind, agent.description, agent.modelRef || "", agent.tags.join(" ")]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function isDefaultDashboardFilters(filters: DashboardFilters): boolean {
  return (
    filters.team === ALL_TEAMS &&
    filters.status === ALL_STATUS &&
    filters.role === ALL_ROLES &&
    filters.model === ALL_MODELS &&
    filters.environment === ALL_ENVIRONMENTS &&
    !(filters.query || "").trim()
  );
}

/** Workers whose current job belongs to one of the given missions (registry truth only). */
export function workersForMissions<T extends { current_job_id?: string | null }>(
  workers: T[],
  missions: AgentMission[],
): T[] {
  const jobIds = new Set(missions.flatMap((m) => m.jobIds || []));
  if (jobIds.size === 0) return [];
  return workers.filter((w) => Boolean(w.current_job_id && jobIds.has(w.current_job_id)));
}

export type DonutSegment = { label: string; value: number; start: number; end: number };

export function donutSegments(items: Array<{ label: string; value: number }>): DonutSegment[] {
  const total = items.reduce((a, b) => a + Math.max(0, b.value), 0);
  if (total <= 0) return [];
  let acc = 0;
  return items
    .filter((i) => i.value > 0)
    .map((i) => {
      const start = acc / total;
      acc += i.value;
      return { label: i.label, value: i.value, start, end: acc / total };
    });
}
