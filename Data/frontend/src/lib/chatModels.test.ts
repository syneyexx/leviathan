import { describe, expect, it } from "vitest";
import {
  chatIneligibilityReason,
  isChatCapableModel,
  partitionChatModels,
} from "../lib/chatModels";
import type { ModelCapabilities, ModelDescriptor } from "../types/api";

const BASE_CAPS: ModelCapabilities = {
  chat: "unknown",
  reasoning: "unknown",
  coding: "unknown",
  toolCalling: "unknown",
  structuredOutput: "unknown",
  vision: "unknown",
  embeddings: "unknown",
  streaming: "unknown",
};

function model(
  partial: Omit<Partial<ModelDescriptor>, "capabilities"> &
    Pick<ModelDescriptor, "id" | "displayName"> & {
      capabilities?: Partial<ModelCapabilities>;
    },
): ModelDescriptor {
  const { capabilities, ...rest } = partial;
  return {
    providerId: "test",
    source: "local",
    lifecycleState: "available",
    health: "healthy",
    active: false,
    loaded: null,
    ...rest,
    capabilities: { ...BASE_CAPS, ...(capabilities || {}) },
  };
}

describe("chatModels picker eligibility", () => {
  it("keeps chat models selectable and excludes embedding/rerank", () => {
    const models = [
      model({
        id: "llama",
        displayName: "Llama 3.1 8B",
        capabilities: { chat: "supported", reasoning: "supported", streaming: "unverified" },
      }),
      model({
        id: "embed",
        displayName: "text-embedding-nomic-embed-text-v1.5",
        capabilities: { chat: "unknown", embeddings: "supported", streaming: "unsupported" },
      }),
      model({
        id: "rerank",
        displayName: "bge-reranker-base",
        capabilities: {
          chat: "unsupported",
          reasoning: "unsupported",
          coding: "unsupported",
          embeddings: "supported",
          streaming: "unsupported",
        },
      }),
      model({
        id: "offline-chat",
        displayName: "Offline Chat",
        lifecycleState: "offline",
        capabilities: { chat: "supported", streaming: "unverified" },
      }),
    ];
    const { eligible, ineligible } = partitionChatModels(models);
    expect(eligible.map((m) => m.id)).toEqual(["llama"]);
    expect(ineligible.map((m) => m.id).sort()).toEqual(["embed", "offline-chat", "rerank"]);
    expect(isChatCapableModel(models[1])).toBe(false);
    expect(chatIneligibilityReason(models[1])).toMatch(/Embedding|rerank|not for chat/i);
  });

  it("Auto remains conceptually available even when no models", () => {
    const { eligible } = partitionChatModels([]);
    expect(eligible).toEqual([]);
  });
});
