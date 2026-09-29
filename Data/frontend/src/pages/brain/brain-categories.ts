/**
 * Presentation mapping: Brain backend node types → V2 semantic categories.
 * Does not rename backend types — classification is UI-only and testable.
 */

import type { LiveBrainNode } from "./brain-live";

export type BrainSemanticCategory = "entity" | "concept" | "document" | "agent";

export type BrainCategoryFilter = "all" | BrainSemanticCategory;

export type BrainCategoryMeta = {
  id: BrainSemanticCategory;
  label: string;
  /** CSS custom property token name under .lv-v2 */
  token: string;
};

export const BRAIN_CATEGORY_META: readonly BrainCategoryMeta[] = [
  { id: "entity", label: "Entiteit", token: "var(--lv2-viz-entity)" },
  { id: "concept", label: "Concept", token: "var(--lv2-viz-concept)" },
  { id: "document", label: "Document", token: "var(--lv2-viz-document)" },
  { id: "agent", label: "Agent", token: "var(--lv2-viz-agent)" },
] as const;

/** Resolved hex for SVG paint (CSS vars are unreliable in SVG presentation attrs). */
export const BRAIN_CATEGORY_HEX: Record<BrainSemanticCategory, string> = {
  entity: "#3b82f6",
  concept: "#a855f7",
  document: "#22d3ee",
  agent: "#f59e0b",
};

export const BRAIN_FILTER_TABS: readonly { id: BrainCategoryFilter; label: string }[] = [
  { id: "all", label: "Alles" },
  { id: "entity", label: "Entiteiten" },
  { id: "concept", label: "Concepten" },
  { id: "document", label: "Documenten" },
  { id: "agent", label: "Agents" },
] as const;

/**
 * Map a backend node type string to a Screen 1 semantic category.
 * Explicit and stable — do not invent new backend types.
 */
export function categoryForNodeType(type: string): BrainSemanticCategory {
  const t = type.toLowerCase();

  if (
    t === "agent" ||
    t.startsWith("agent.") ||
    t.includes("agent") ||
    t.includes("orchestrator") ||
    t === "module" ||
    t.includes("runtime.agent")
  ) {
    return "agent";
  }

  if (
    t === "knowledge.document" ||
    t === "document" ||
    t.includes("document") ||
    t === "dataset" ||
    t.startsWith("dataset.") ||
    t === "evidence" ||
    t.startsWith("evidence.") ||
    t.includes("source") ||
    t === "atlas"
  ) {
    return "document";
  }

  if (
    t === "concept" ||
    t.startsWith("concept.") ||
    t === "memory" ||
    t.startsWith("memory.") ||
    t.includes("hypothesis") ||
    t.includes("finding") ||
    t.includes("strategy") ||
    t.includes("model") ||
    t === "capability" ||
    t === "workflow" ||
    t.startsWith("mcp.")
  ) {
    return "concept";
  }

  // Default: entity (research projects, conversations, runs, tools, unknowns)
  return "entity";
}

export function categoryForNode(node: Pick<LiveBrainNode, "type">): BrainSemanticCategory {
  return categoryForNodeType(node.type);
}

export function categoryColor(category: BrainSemanticCategory): string {
  const meta = BRAIN_CATEGORY_META.find((row) => row.id === category);
  return meta?.token ?? "var(--lv2-cyan)";
}

export function categoryLabel(category: BrainSemanticCategory): string {
  return BRAIN_CATEGORY_META.find((row) => row.id === category)?.label ?? category;
}

export function filterNodesByCategory<T extends Pick<LiveBrainNode, "type">>(
  nodes: readonly T[],
  filter: BrainCategoryFilter,
): T[] {
  if (filter === "all") return [...nodes];
  return nodes.filter((node) => categoryForNode(node) === filter);
}
