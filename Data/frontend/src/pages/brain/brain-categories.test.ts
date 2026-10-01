import { describe, expect, it } from "vitest";
import {
  BRAIN_CATEGORY_HEX,
  categoryColor,
  categoryForNodeType,
  filterNodesByCategory,
} from "./brain-categories";
import type { LiveBrainNode } from "./brain-live";

function node(id: string, type: string): LiveBrainNode {
  return { id, type, label: id, created_at: "2025-01-01T00:00:00Z" };
}

describe("categoryForNodeType explicit mapping", () => {
  it("maps known backend types without renaming them", () => {
    expect(categoryForNodeType("agent")).toBe("agent");
    expect(categoryForNodeType("agent.runtime")).toBe("agent");
    expect(categoryForNodeType("module")).toBe("agent");
    expect(categoryForNodeType("knowledge.document")).toBe("document");
    expect(categoryForNodeType("evidence")).toBe("document");
    expect(categoryForNodeType("dataset.hf")).toBe("document");
    expect(categoryForNodeType("concept")).toBe("concept");
    expect(categoryForNodeType("memory")).toBe("concept");
    expect(categoryForNodeType("mcp.tool")).toBe("concept");
    expect(categoryForNodeType("research.project")).toBe("entity");
    expect(categoryForNodeType("conversation")).toBe("entity");
  });

  it("sends unknown and adversarial substring types to unclassified", () => {
    expect(categoryForNodeType("unknown.thing")).toBe("unclassified");
    expect(categoryForNodeType("myagenthelper")).toBe("unclassified");
    expect(categoryForNodeType("sourcedocumentation")).toBe("unclassified");
    expect(categoryForNodeType("orchestrator")).toBe("unclassified");
    expect(categoryForNodeType("hypothesis")).toBe("unclassified");
    expect(categoryForNodeType("")).toBe("unclassified");
  });

  it("exposes V2 CSS tokens and documents hex as SVG fallbacks", () => {
    expect(categoryColor("entity")).toBe("var(--lv2-viz-entity)");
    expect(categoryColor("unclassified")).toBe("var(--lv2-viz-unclassified)");
    expect(BRAIN_CATEGORY_HEX.entity).toBe("#3b82f6");
    expect(BRAIN_CATEGORY_HEX.unclassified).toBe("#94a3b8");
  });

  it("filters by category including unclassified", () => {
    const nodes = [
      node("a", "agent"),
      node("b", "weird.type"),
      node("c", "knowledge.document"),
    ];
    expect(filterNodesByCategory(nodes, "unclassified").map((n) => n.id)).toEqual(["b"]);
  });
});
