import { describe, expect, it } from "vitest";
import type { AgentDefinition, AgentMission, AgentSignal, CapabilityListItem } from "../types/api";
import {
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

import { matchesSignalFilter, formatSignalConfidence } from "./agents/signalHelpers";
import type { AgentSignal } from "../types/api";

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
