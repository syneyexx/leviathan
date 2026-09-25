import { describe, expect, it } from "vitest";
import type {
  AgentDefinition,
  AgentMission,
  AgentSignal,
  CapabilityListItem,
  SystemArchitectureEntry,
} from "../types/api";
import {
  ALL_ENVIRONMENTS,
  ALL_MODELS,
  ALL_ROLES,
  ALL_STATUS,
  ALL_TEAMS,
  MODEL_UNSET,
  agentEnvironment,
  agentMissionStats,
  buildArchitectureTiers,
  deriveModelOptions,
  deriveTeamOptions,
  donutSegments,
  emptyDashboardFilters,
  filterDashboardAgents,
  formatDurationMs,
  formatPct,
  formatSyncAge,
  groupSystemEntriesByRuntime,
  isDefaultDashboardFilters,
  orchestratorsForMember,
  teamBucketForAgent,
  workersForMissions,
  agentEntityType,
  agentOrigin,
  assignedCapabilityCards,
  canLaunchAgent,
  draftToCreatePayload,
  emptyEditorDraft,
  filterMissions,
  filterRoster,
  healthLabel,
  isArchitectureEntry,
  isSystemProtected,
  layoutNetworkNodes,
  networkEdgesFromAgents,
  validateEditorDraft,
} from "./agents/helpers";
import { formatSignalConfidence, matchesSignalFilter } from "./agents/signalHelpers";

function agent(partial: Partial<AgentDefinition> & Pick<AgentDefinition, "agentId" | "name">): AgentDefinition {
  return {
    kind: "research",
    description: "",
    role: "Analysis",
    enabled: true,
    archived: false,
    capabilities: [],
    knowledgeSources: [],
    memoryPolicy: "default",
    datasetAccess: "none",
    approvalMode: "inherit",
    autonomy: 50,
    maxConcurrency: 1,
    maxRetries: 0,
    tags: [],
    version: 1,
    health: "idle",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

describe("agents page helpers", () => {
  it("filters roster from real kind/role/status without hardcoded Analysis-only matching", () => {
    const agents = [
      agent({ agentId: "a1", name: "Alpha", role: "Goals & Decomposition", kind: "orchestrator" }),
      agent({ agentId: "a2", name: "Beta", role: "Research / Analysis", kind: "research", health: "busy" }),
      agent({ agentId: "a3", name: "Gamma", role: "Coding", kind: "coding", archived: true }),
    ];
    const roles = filterRoster(agents, {
      query: "",
      roleFilter: "Goals & Decomposition",
      statusFilter: "All Status",
      kindFilter: "All Kinds",
      showArchived: false,
    });
    expect(roles.map((a) => a.agentId)).toEqual(["a1"]);

    const orch = filterRoster(agents, {
      query: "",
      roleFilter: "All Roles",
      statusFilter: "All Status",
      kindFilter: "orchestrator",
      showArchived: false,
    });
    expect(orch).toHaveLength(1);
    expect(orch[0].kind).toBe("orchestrator");

    const archived = filterRoster(agents, {
      query: "",
      roleFilter: "All Roles",
      statusFilter: "All Status",
      kindFilter: "__archived_only__",
      showArchived: true,
    });
    expect(archived.map((a) => a.agentId)).toEqual(["a3"]);
  });

  it("never presents global capabilities as assigned when agent has none", () => {
    const registry: CapabilityListItem[] = [
      { id: "knowledge.search", name: "Search", description: "Search knowledge" },
      { id: "file.read", name: "Read", description: "Read file" },
    ];
    const empty = agent({ agentId: "x", name: "X", capabilities: [] });
    expect(assignedCapabilityCards(empty, registry)).toEqual([]);

    const assigned = agent({ agentId: "y", name: "Y", capabilities: ["file.read"] });
    const cards = assignedCapabilityCards(assigned, registry);
    expect(cards).toHaveLength(1);
    expect(cards[0].id).toBe("file.read");
    expect(cards[0].title).toBe("Read");
  });

  it("builds create payload for orchestrator with real member ids", () => {
    const draft = emptyEditorDraft({
      name: "Fleet Lead",
      kind: "orchestrator",
      memberAgentIds: ["agent_a", "agent_b"],
      strategy: "parallel_bounded",
      failureStrategy: "continue",
      maxDelegationDepth: 4,
      parallelismLimit: 3,
    });
    const payload = draftToCreatePayload(draft);
    expect(payload.name).toBe("Fleet Lead");
    expect(payload.kind).toBe("orchestrator");
    expect(payload.orchestrator).toMatchObject({
      memberAgentIds: ["agent_a", "agent_b"],
      strategy: "parallel_bounded",
      failureStrategy: "continue",
      maxDelegationDepth: 4,
      parallelismLimit: 3,
    });
  });

  it("rejects self-membership in editor validation", () => {
    const draft = emptyEditorDraft({
      name: "Bad",
      kind: "orchestrator",
      memberAgentIds: ["self"],
    });
    expect(validateEditorDraft(draft, { editingId: "self" })).toMatch(/itself/i);
  });

  it("mission tabs preserve failed/cancelled/interrupted separately", () => {
    const missions: AgentMission[] = [
      {
        missionId: "1",
        agentId: "a",
        title: "t",
        request: "r",
        status: "failed",
        priority: "med",
        progress: 0,
        jobIds: [],
        createdAt: "",
        updatedAt: "",
      },
      {
        missionId: "2",
        agentId: "a",
        title: "t",
        request: "r",
        status: "cancelled",
        priority: "med",
        progress: 0,
        jobIds: [],
        createdAt: "",
        updatedAt: "",
      },
      {
        missionId: "3",
        agentId: "a",
        title: "t",
        request: "r",
        status: "interrupted",
        priority: "med",
        progress: 0,
        jobIds: [],
        createdAt: "",
        updatedAt: "",
      },
      {
        missionId: "4",
        agentId: "a",
        title: "t",
        request: "r",
        status: "running",
        priority: "med",
        progress: 0.5,
        jobIds: [],
        createdAt: "",
        updatedAt: "",
      },
    ];
    expect(filterMissions(missions, "Failed").map((m) => m.missionId)).toEqual(["1"]);
    expect(filterMissions(missions, "Cancelled").map((m) => m.missionId)).toEqual(["2"]);
    expect(filterMissions(missions, "Interrupted").map((m) => m.missionId)).toEqual(["3"]);
    expect(filterMissions(missions, "Running").map((m) => m.missionId)).toEqual(["4"]);
  });

  it("network edges come only from orchestrator.memberAgentIds and support multiple hubs", () => {
    const agents = [
      agent({
        agentId: "o1",
        name: "Orch1",
        kind: "orchestrator",
        orchestrator: {
          memberAgentIds: ["w1"],
          strategy: "sequential",
          routingRules: [],
          maxDelegationDepth: 3,
          parallelismLimit: 2,
          fanOutPolicy: "ordered",
          retryPolicy: {},
          approvalEscalation: "inherit",
          failureStrategy: "fail_fast",
          verificationRequired: false,
        },
      }),
      agent({
        agentId: "o2",
        name: "Orch2",
        kind: "orchestrator",
        orchestrator: {
          memberAgentIds: ["w1", "w2"],
          strategy: "parallel_bounded",
          routingRules: [],
          maxDelegationDepth: 3,
          parallelismLimit: 2,
          fanOutPolicy: "ordered",
          retryPolicy: {},
          approvalEscalation: "inherit",
          failureStrategy: "continue",
          verificationRequired: false,
        },
      }),
      agent({ agentId: "w1", name: "Worker1", kind: "research", health: "busy" }),
      agent({ agentId: "w2", name: "Worker2", kind: "coding" }),
      agent({ agentId: "lonely", name: "Lonely", kind: "generic" }),
    ];
    const edges = networkEdgesFromAgents(agents);
    expect(edges).toEqual([
      { from: "o1", to: "w1", active: true },
      { from: "o2", to: "w1", active: true },
      { from: "o2", to: "w2", active: false },
    ]);
    const nodes = layoutNetworkNodes(agents, edges);
    expect(nodes.filter((n) => n.hub)).toHaveLength(2);
    expect(nodes.some((n) => n.id === "lonely")).toBe(true);
  });

  it("launch gate refuses disabled/archived/feature-off agents", () => {
    expect(canLaunchAgent(undefined, true).ok).toBe(false);
    expect(canLaunchAgent(agent({ agentId: "a", name: "A", enabled: false }), true).ok).toBe(false);
    expect(canLaunchAgent(agent({ agentId: "a", name: "A", archived: true }), true).ok).toBe(false);
    expect(canLaunchAgent(agent({ agentId: "a", name: "A" }), false).reason).toMatch(/feature flag/i);
    expect(canLaunchAgent(agent({ agentId: "a", name: "A" }), true).ok).toBe(true);
    expect(
      canLaunchAgent(
        agent({
          agentId: "system:architecture:execution_gateway",
          name: "Execution Gateway",
          entityType: "architecture",
          origin: "system",
          executable: false,
        }),
        true,
      ).ok,
    ).toBe(false);
  });

  it("classifies SYSTEM/USER and entity types from backend fields", () => {
    const systemAgent = agent({
      agentId: "a1",
      name: "Research",
      origin: "system",
      entityType: "agent",
      systemKey: "research",
      mutable: false,
    });
    const userAgent = agent({ agentId: "a2", name: "Custom", origin: "user", entityType: "agent" });
    const planner = agent({
      agentId: "a3",
      name: "Planner",
      kind: "orchestrator",
      origin: "system",
      entityType: "orchestrator",
      systemKey: "planner",
      mutable: false,
    });
    const arch = agent({
      agentId: "system:architecture:execution_gateway",
      name: "Execution Gateway",
      origin: "system",
      entityType: "architecture",
      systemKey: "execution_gateway",
      mutable: false,
    });
    expect(agentOrigin(systemAgent)).toBe("system");
    expect(agentOrigin(userAgent)).toBe("user");
    expect(agentEntityType(planner)).toBe("orchestrator");
    expect(agentEntityType(arch)).toBe("architecture");
    expect(isSystemProtected(systemAgent)).toBe(true);
    expect(isSystemProtected(userAgent)).toBe(false);
    expect(isArchitectureEntry(arch)).toBe(true);

    const filteredSystem = filterRoster([systemAgent, userAgent, planner, arch], {
      query: "",
      roleFilter: "All Roles",
      statusFilter: "All Status",
      kindFilter: "All Kinds",
      showArchived: false,
      originFilter: "SYSTEM",
      entityTypeFilter: "ALL TYPES",
    });
    expect(filteredSystem.map((a) => a.agentId).sort()).toEqual(
      ["a1", "a3", "system:architecture:execution_gateway"].sort(),
    );

    const filteredArch = filterRoster([systemAgent, userAgent, planner, arch], {
      query: "",
      roleFilter: "All Roles",
      statusFilter: "All Status",
      kindFilter: "All Kinds",
      showArchived: false,
      originFilter: "ALL",
      entityTypeFilter: "ARCHITECTURE",
    });
    expect(filteredArch).toHaveLength(1);
    expect(filteredArch[0].agentId).toBe("system:architecture:execution_gateway");
  });

  it("health labels stay honest for unknown/error/archived", () => {
    expect(healthLabel(agent({ agentId: "a", name: "A", health: "error" }))).toBe("Error");
    expect(healthLabel(agent({ agentId: "a", name: "A", archived: true }))).toBe("Archived");
    expect(healthLabel(agent({ agentId: "a", name: "A", health: "unknown" }))).toBe("Unknown");
  });
});

function signal(partial: Partial<AgentSignal> & Pick<AgentSignal, "signalId" | "signalType">): AgentSignal {
  return {
    senderType: "AGENT",
    senderId: "a1",
    recipientType: "AGENT",
    recipientId: "a2",
    priority: "NORMAL",
    subject: "s",
    payload: {},
    artifactRefs: [],
    evidenceRefs: [],
    requiresAck: false,
    hopCount: 0,
    maxHops: 8,
    status: "ROUTED",
    createdAt: "2026-01-01T12:00:00Z",
    updatedAt: "2026-01-01T12:00:00Z",
    ...partial,
  };
}

describe("signal helpers", () => {
  it("filters signal feed categories", () => {
    const handoff = signal({ signalId: "1", signalType: "TASK_HANDOFF" });
    const block = signal({ signalId: "2", signalType: "BLOCK" });
    const finding = signal({ signalId: "3", signalType: "FINDING" });
    expect(matchesSignalFilter(handoff, "ALL")).toBe(true);
    expect(matchesSignalFilter(handoff, "HANDOFFS")).toBe(true);
    expect(matchesSignalFilter(handoff, "BLOCKS")).toBe(false);
    expect(matchesSignalFilter(block, "BLOCKS")).toBe(true);
    expect(matchesSignalFilter(finding, "KNOWLEDGE")).toBe(true);
  });

  it("formats confidence honestly", () => {
    expect(formatSignalConfidence(0.94)).toBe("94%");
    expect(formatSignalConfidence(null)).toBeNull();
  });
});

function mission(partial: Partial<AgentMission> & Pick<AgentMission, "missionId" | "agentId" | "status">): AgentMission {
  return {
    title: "t",
    request: "r",
    priority: "med",
    progress: 0,
    jobIds: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

function sysEntry(partial: Partial<SystemArchitectureEntry> & Pick<SystemArchitectureEntry, "id" | "name">): SystemArchitectureEntry {
  return {
    origin: "system",
    entityType: "architecture",
    systemKey: partial.id,
    status: "unknown",
    mutable: false,
    ...partial,
  };
}

describe("agents dashboard helpers", () => {
  it("team buckets mirror backend team_bucket_for_agent precedence", () => {
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Scout", kind: "research" }))).toBe("Research");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Builder", kind: "coding", role: "" }))).toBe("Development");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Desk", kind: "trading", role: "" }))).toBe("Trading");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Lead", kind: "orchestrator", role: "" }))).toBe("Planning");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Guardian", kind: "generic", role: "Risk" }))).toBe("Risk");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Recall", kind: "generic", role: "memory keeper" }))).toBe("Memory");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Judge", kind: "generic", role: "", tags: ["QA"] }))).toBe("Evaluation");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Eye", kind: "generic", role: "vision" }))).toBe("Vision");
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Misc", kind: "generic", role: "" }))).toBe("Other");
    // research wins over trading when both match (same order as backend)
    expect(teamBucketForAgent(agent({ agentId: "a", name: "Trade research", kind: "generic", role: "" }))).toBe("Research");
    expect(
      teamBucketForAgent(agent({ agentId: "a", name: "Crit", kind: "generic", role: "", systemKey: "critic" })),
    ).toBe("Risk");
  });

  it("formats durations and sync age honestly", () => {
    expect(formatDurationMs(null)).toBe("—");
    expect(formatDurationMs(-5)).toBe("—");
    expect(formatDurationMs(420)).toBe("420ms");
    expect(formatDurationMs(1800)).toBe("1.8s");
    expect(formatDurationMs(42_000)).toBe("42s");
    expect(formatDurationMs(125_000)).toBe("2m 5s");
    expect(formatDurationMs(3_600_000)).toBe("1h");
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(formatSyncAge(null, now)).toBe("—");
    expect(formatSyncAge("garbage", now)).toBe("—");
    expect(formatSyncAge("2026-01-01T11:59:58Z", now)).toBe("just now");
    expect(formatSyncAge("2026-01-01T11:59:30Z", now)).toBe("30s ago");
    expect(formatSyncAge("2026-01-01T11:58:00Z", now)).toBe("2 min ago");
    expect(formatSyncAge("2026-01-01T09:00:00Z", now)).toBe("3h ago");
    expect(formatPct(null)).toBe("—");
    expect(formatPct(0.968)).toBe("96.8%");
  });

  it("per-agent mission stats exclude cancelled from success and return null without evidence", () => {
    const missions = [
      mission({ missionId: "1", agentId: "a", status: "completed", startedAt: "2026-01-01T00:00:00Z", finishedAt: "2026-01-01T00:00:02Z" }),
      mission({ missionId: "2", agentId: "a", status: "failed" }),
      mission({ missionId: "3", agentId: "a", status: "cancelled" }),
      mission({ missionId: "4", agentId: "a", status: "running" }),
      mission({ missionId: "5", agentId: "b", status: "completed" }),
    ];
    const st = agentMissionStats(missions, "a");
    expect(st).toMatchObject({ total: 4, active: 1, completed: 1, failed: 1, successRate: 0.5, avgDurationMs: 2000 });
    expect(agentMissionStats(missions, "none").successRate).toBeNull();
    expect(agentMissionStats(missions, "none").avgDurationMs).toBeNull();
  });

  it("architecture tiers use real orchestrators and cap visible nodes", () => {
    const orch = agent({
      agentId: "o1",
      name: "Chief",
      kind: "orchestrator",
      orchestrator: {
        memberAgentIds: ["s1"],
        strategy: "sequential",
        routingRules: [],
        maxDelegationDepth: 3,
        parallelismLimit: 2,
        fanOutPolicy: "ordered",
        retryPolicy: {},
        approvalEscalation: "inherit",
        failureStrategy: "fail_fast",
        verificationRequired: false,
      },
    });
    const specialists = Array.from({ length: 10 }, (_, i) =>
      agent({ agentId: `s${i}`, name: `Spec ${i}`, kind: i % 2 ? "coding" : "research" }),
    );
    const archived = agent({ agentId: "old", name: "Old", kind: "research", archived: true });
    const sys = [
      sysEntry({ id: "system:orchestrator:cog", name: "Cognitive Runtime", entityType: "orchestrator", runtimeKind: "cognition" }),
      sysEntry({ id: "system:architecture:gw", name: "Gateway", runtimeKind: "execution" }),
    ];
    const tiers = buildArchitectureTiers([orch, ...specialists, archived], sys, { maxOrchestrators: 4, maxSpecialists: 8 });
    expect(tiers.orchestrators.map((o) => o.id)).toEqual(["o1", "system:orchestrator:cog"]);
    expect(tiers.orchestrators[0].memberIds).toEqual(["s1"]);
    expect(tiers.orchestrators[1].source).toBe("system");
    expect(tiers.specialists).toHaveLength(8);
    expect(tiers.hiddenSpecialists).toBe(2);
    expect(tiers.specialists.some((s) => s.id === "old")).toBe(false);
    // research before development in bucket order
    expect(tiers.specialists[0].team).toBe("Research");
    expect(orchestratorsForMember([orch, ...specialists], "s1").map((o) => o.agentId)).toEqual(["o1"]);
    expect(orchestratorsForMember([orch, ...specialists], "s2")).toEqual([]);

    const groups = groupSystemEntriesByRuntime(sys);
    expect(groups.map((g) => g.runtimeKind)).toEqual(["cognition", "execution"]);
  });

  it("dashboard filters apply team/status/role/model/environment together", () => {
    const agents = [
      agent({ agentId: "r", name: "Research", kind: "research", role: "Analysis", modelRef: "llama3", origin: "system", systemKey: "research" }),
      agent({ agentId: "c", name: "Coder", kind: "coding", role: "Development", health: "busy", origin: "user" }),
      agent({ agentId: "t", name: "Trader", kind: "trading", role: "Markets", enabled: false, origin: "user" }),
    ];
    const f = emptyDashboardFilters();
    expect(isDefaultDashboardFilters(f)).toBe(true);
    expect(filterDashboardAgents(agents, f)).toHaveLength(3);
    expect(filterDashboardAgents(agents, { ...f, team: "Development" }).map((a) => a.agentId)).toEqual(["c"]);
    expect(filterDashboardAgents(agents, { ...f, status: "Offline" }).map((a) => a.agentId)).toEqual(["t"]);
    expect(filterDashboardAgents(agents, { ...f, role: "analysis" }).map((a) => a.agentId)).toEqual(["r"]);
    expect(filterDashboardAgents(agents, { ...f, model: MODEL_UNSET }).map((a) => a.agentId)).toEqual(["c", "t"]);
    expect(filterDashboardAgents(agents, { ...f, environment: "System" }).map((a) => a.agentId)).toEqual(["r"]);
    expect(filterDashboardAgents(agents, { ...f, query: "trad" }).map((a) => a.agentId)).toEqual(["t"]);
    expect(
      filterDashboardAgents(agents, {
        team: ALL_TEAMS,
        status: ALL_STATUS,
        role: ALL_ROLES,
        model: ALL_MODELS,
        environment: ALL_ENVIRONMENTS,
      }),
    ).toHaveLength(3);
    expect(deriveTeamOptions(agents)).toEqual(["Research", "Development", "Trading"]);
    expect(deriveModelOptions(agents)).toEqual([MODEL_UNSET, "llama3"]);
    expect(
      agentEnvironment(agent({ agentId: "system:architecture:x", name: "X", entityType: "architecture" })),
    ).toBe("Architecture");
  });

  it("workers match missions only through registry current_job_id", () => {
    const workers = [
      { worker_id: "w1", current_job_id: "job-1" },
      { worker_id: "w2", current_job_id: null },
      { worker_id: "w3", current_job_id: "job-9" },
    ];
    const ms = [mission({ missionId: "m", agentId: "a", status: "running", jobIds: ["job-1", "job-2"] })];
    expect(workersForMissions(workers, ms).map((w) => w.worker_id)).toEqual(["w1"]);
    expect(workersForMissions(workers, [])).toEqual([]);
  });

  it("donut segments are proportional and skip empty teams", () => {
    expect(donutSegments([])).toEqual([]);
    expect(donutSegments([{ label: "A", value: 0 }])).toEqual([]);
    const segs = donutSegments([
      { label: "A", value: 3 },
      { label: "B", value: 0 },
      { label: "C", value: 1 },
    ]);
    expect(segs.map((s) => s.label)).toEqual(["A", "C"]);
    expect(segs[0]).toMatchObject({ start: 0, end: 0.75 });
    expect(segs[1]).toMatchObject({ start: 0.75, end: 1 });
  });
});
