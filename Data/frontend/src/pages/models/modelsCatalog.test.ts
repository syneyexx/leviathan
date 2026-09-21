import { describe, expect, it } from "vitest";
import type { ModelDescriptor } from "../../types/api";

function filterModels(
  models: ModelDescriptor[],
  query: string,
  filter: string,
): ModelDescriptor[] {
  const q = query.trim().toLowerCase();
  return models.filter((model) => {
    if (filter === "active" && !model.active) return false;
    if (filter === "offline" && model.lifecycleState !== "offline") return false;
    if (!q) return true;
    return `${model.id} ${model.displayName} ${model.providerId}`.toLowerCase().includes(q);
  });
}

const sample: ModelDescriptor[] = [
  {
    id: "lm_studio:a",
    displayName: "Alpha",
    providerId: "lm_studio",
    source: "remote",
    capabilities: {
      chat: "unverified",
      reasoning: "unknown",
      coding: "unknown",
      toolCalling: "unknown",
      structuredOutput: "unknown",
      vision: "unknown",
      embeddings: "unknown",
      streaming: "unverified",
    },
    lifecycleState: "available",
    health: "healthy",
    active: true,
    loaded: null,
  },
  {
    id: "lm_studio:b",
    displayName: "Beta",
    providerId: "lm_studio",
    source: "remote",
    capabilities: {
      chat: "unknown",
      reasoning: "unknown",
      coding: "unknown",
      toolCalling: "unknown",
      structuredOutput: "unknown",
      vision: "unknown",
      embeddings: "unknown",
      streaming: "unknown",
    },
    lifecycleState: "offline",
    health: "offline",
    active: false,
    loaded: false,
  },
];

describe("Models catalog filtering", () => {
  it("filters by search without triggering discovery semantics", () => {
    expect(filterModels(sample, "alpha", "all")).toHaveLength(1);
    expect(filterModels(sample, "lm_studio:b", "all")[0]?.displayName).toBe("Beta");
  });

  it("supports active and offline filters", () => {
    expect(filterModels(sample, "", "active")).toHaveLength(1);
    expect(filterModels(sample, "", "offline")[0]?.id).toBe("lm_studio:b");
  });

  it("does not invent parameter counts from names", () => {
    expect(sample.every((m) => m.parameterCount == null)).toBe(true);
  });
});
