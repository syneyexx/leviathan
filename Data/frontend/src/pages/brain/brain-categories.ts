/**
 * Presentation mapping: Brain backend node types → V2 semantic categories.
 * Does not rename backend types — classification is UI-only and testable.
 */

import type { LiveBrainNode } from "./brain-live";

export type BrainSemanticCategory =
  | "entity"
  | "concept"
  | "document"
  | "agent"
  | "unclassified";

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
  { id: "unclassified", label: "Ongeclassificeerd", token: "var(--lv2-viz-unclassified)" },
] as const;

/**
 * Hex fallbacks resolved from V2 tokens (`--lv2-viz-*`) for SVG/canvas paint
 * when CSS custom properties cannot be used as presentation attributes.
 * Prefer `categoryColor` / `resolveCategoryPaint` in DOM contexts.
 */
export const BRAIN_CATEGORY_HEX: Record<BrainSemanticCategory, string> = {
  entity: "#3b82f6", // --lv2-viz-entity
  concept: "#a855f7", // --lv2-viz-concept
  document: "#22d3ee", // --lv2-viz-document
  agent: "#f59e0b", // --lv2-viz-agent
  unclassified: "#94a3b8", // --lv2-viz-unclassified
};

export const BRAIN_FILTER_TABS: readonly { id: BrainCategoryFilter; label: string }[] = [
  { id: "all", label: "Alles" },
  { id: "entity", label: "Entiteiten" },
  { id: "concept", label: "Concepten" },
  { id: "document", label: "Documenten" },
  { id: "agent", label: "Agents" },
  { id: "unclassified", label: "Ongeclassificeerd" },
] as const;

function matchesKnown(type: string, exact: string): boolean {
  return type === exact || type.startsWith(`${exact}.`);
}

/**
 * Map a backend node type string to a Screen 1 semantic category.
 * Explicit known-type mapping only — unknown types stay unclassified.
 */
export function categoryForNodeType(type: string): BrainSemanticCategory {
  const t = type.toLowerCase().trim();
  if (!t) return "unclassified";

  if (matchesKnown(t, "agent") || matchesKnown(t, "module")) {
    return "agent";
  }

  if (
    t === "knowledge.document" ||
    matchesKnown(t, "document") ||
    matchesKnown(t, "dataset") ||
    matchesKnown(t, "evidence") ||
    matchesKnown(t, "atlas")
  ) {
    return "document";
  }

  if (
    matchesKnown(t, "concept") ||
    matchesKnown(t, "memory") ||
    matchesKnown(t, "capability") ||
    matchesKnown(t, "workflow") ||
    matchesKnown(t, "model") ||
    t.startsWith("mcp.")
  ) {
    return "concept";
  }

  if (
    t === "research.project" ||
    t.startsWith("research.") ||
    matchesKnown(t, "conversation") ||
    matchesKnown(t, "run") ||
    matchesKnown(t, "tool") ||
    matchesKnown(t, "project") ||
    matchesKnown(t, "code")
  ) {
    return "entity";
  }

  return "unclassified";
}

export function categoryForNode(node: Pick<LiveBrainNode, "type">): BrainSemanticCategory {
  return categoryForNodeType(node.type);
}

export function categoryColor(category: BrainSemanticCategory): string {
  const meta = BRAIN_CATEGORY_META.find((row) => row.id === category);
  return meta?.token ?? "var(--lv2-viz-unclassified)";
}

/** Resolve a paint color from V2 CSS vars when possible; fall back to documented hex. */
export function resolveCategoryPaint(
  category: BrainSemanticCategory,
  el?: Element | null,
): string {
  const token = categoryColor(category);
  const match = /^var\((--[^)]+)\)$/.exec(token);
  if (match && typeof window !== "undefined" && typeof window.getComputedStyle === "function") {
    const probe = el ?? document.querySelector(".lv-v2") ?? document.documentElement;
    const resolved = window.getComputedStyle(probe).getPropertyValue(match[1]).trim();
    if (resolved) return resolved;
  }
  return BRAIN_CATEGORY_HEX[category];
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
