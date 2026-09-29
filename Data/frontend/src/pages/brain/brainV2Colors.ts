/** Screen 1 Brain legend color mapping — entity / concept / document / agent. */

export type BrainLegendCategory = "entity" | "concept" | "document" | "agent" | "other";

const COLORS = {
  entity: "#22d3ee",
  concept: "#a855f7",
  document: "#2dd4bf",
  agent: "#f59e0b",
  other: "#94a3b8",
} as const;

/**
 * Map Brain node type strings onto Screen 1 legend categories.
 * Heuristics cover dotted types (knowledge.document) and aliases (evidence, memory).
 */
export function brainLegendCategory(type: string): BrainLegendCategory {
  const t = type.trim().toLowerCase();
  if (!t) return "other";

  if (
    t === "agent" ||
    t.startsWith("agent.") ||
    t.includes("agent") ||
    t === "model" ||
    t.startsWith("model.") ||
    t.includes("llm") ||
    t === "capability" ||
    t.startsWith("mcp.")
  ) {
    return "agent";
  }

  if (
    t === "knowledge.document" ||
    t.endsWith(".document") ||
    t === "document" ||
    t.includes("document") ||
    t === "dataset" ||
    t.startsWith("dataset.") ||
    t === "atlas" ||
    t.includes("knowledge")
  ) {
    return "document";
  }

  if (
    t === "concept" ||
    t.startsWith("concept.") ||
    t.includes("concept") ||
    t === "research.project" ||
    t.includes("hypothesis") ||
    t.includes("finding")
  ) {
    return "concept";
  }

  if (
    t === "evidence" ||
    t.startsWith("evidence.") ||
    t === "memory" ||
    t.startsWith("memory.") ||
    t === "entity" ||
    t.startsWith("entity.") ||
    t.includes("entity") ||
    t === "conversation" ||
    t === "run" ||
    t === "project" ||
    t === "module" ||
    t === "workflow" ||
    t === "tool" ||
    t === "code"
  ) {
    return "entity";
  }

  return "other";
}

export function v2ColorForBrainType(type: string): string {
  return COLORS[brainLegendCategory(type)];
}
