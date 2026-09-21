export { mockAgents } from "./agents";
export { mockChatMessages, mockChatThreads } from "./chat";
export * from "./media-channels";
export * from "./media-analytics";
export * from "./media-calendar";
export * from "./trading";
export * from "./model-training";
export { mockAcceptance, mockMissions, mockPlanSteps, mockSystemReadiness } from "./missions";
export { mockTasks } from "./tasks";

export const mockModels = [
  { id: "qwen3-14b-instruct", provider: "LM Studio", type: "Chat", context: "32k", status: "Geladen" },
  { id: "qwen2.5-coder-14b", provider: "LM Studio", type: "Coding", context: "32k", status: "Beschikbaar" },
  { id: "bge-m3", provider: "Lokaal", type: "Embeddings", context: "8k", status: "Actief" },
];

export const mockTools = [
  { id: "fs", name: "Filesystem", category: "Core", service: "lokaal", health: "ok" },
  { id: "terminal", name: "Terminal", category: "Core", service: "lokaal", health: "ok" },
  { id: "web", name: "Web research", category: "Research", service: "opt-in", health: "idle" },
];

export const mockMcpServers = [
  { id: "mcp-1", name: "filesystem", type: "stdio", status: "connected" },
  { id: "mcp-2", name: "memory", type: "stdio", status: "draft" },
];

export const mockKnowledgeCollections = [
  { id: "k1", name: "Project docs", count: 42 },
  { id: "k2", name: "Research notes", count: 18 },
  { id: "k3", name: "Kiwix mirrors", count: 3 },
];

export const mockEvidenceItems = [
  { id: "e1", title: "Navigatie snapshot", when: "Vandaag 10:24", verified: true },
  { id: "e2", title: "Plugin install log", when: "Gisteren", verified: false },
];

export const mockMemoryNodes = [
  { id: "n1", title: "HADES BETA", kind: "Project", relations: 12 },
  { id: "n2", title: "Voorkeuren", kind: "Preference", relations: 4 },
];

export const mockPerformance = {
  cpu: 28,
  ram: 61,
  gpu: 44,
  tokensPerSec: 38,
};
