/**
 * Phase 1 data accessors — return mock domain objects.
 * Phase 2 should replace these with real HADES API/hooks without rewriting pages wholesale.
 */
import {
  mockAcceptance,
  mockAgents,
  mockChatMessages,
  mockChatThreads,
  mockEvidenceItems,
  mockKnowledgeCollections,
  mockMemoryNodes,
  mockMissions,
  mockMcpServers,
  mockModels,
  mockPerformance,
  mockPlanSteps,
  mockSystemReadiness,
  mockTasks,
  mockTools,
} from "../mocks";

export function useFinalBetaMissionData() {
  return { missions: mockMissions, planSteps: mockPlanSteps, acceptance: mockAcceptance, readiness: mockSystemReadiness };
}

export function useFinalBetaAgentData() {
  return { agents: mockAgents };
}

export function useFinalBetaTaskData() {
  return { tasks: mockTasks };
}

/** @deprecated FINALBETA Chat uses `useChatLive` + hadesApi; mocks remain for unrelated stubs. */
export function useFinalBetaChatData() {
  return { threads: mockChatThreads, messages: mockChatMessages };
}

export function useFinalBetaModelData() {
  return { models: mockModels };
}

export function useFinalBetaToolData() {
  return { tools: mockTools };
}

export function useFinalBetaMcpData() {
  return { servers: mockMcpServers };
}

export function useFinalBetaKnowledgeData() {
  return { collections: mockKnowledgeCollections };
}

export function useFinalBetaEvidenceData() {
  return { items: mockEvidenceItems };
}

export function useFinalBetaMemoryData() {
  return { nodes: mockMemoryNodes };
}

export function useFinalBetaPerformanceData() {
  return { metrics: mockPerformance };
}
