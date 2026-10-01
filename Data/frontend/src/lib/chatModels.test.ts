import { describe, expect, it } from "vitest";
import {
  chatIneligibilityReason,
  isChatCapableModel,
  modelPickerWarning,
  partitionChatModels,
} from "../lib/chatModels";
import type { ModelCapabilities, ModelDescriptor } from "../types/api";

const BASE_CAPS: ModelCapabilities = {
  chat: "unknown",
  reasoning: "unknown",
  coding: "unknown",
  toolCalling: "unknown",
  parallelToolCalls: "unknown",
  structuredOutput: "unknown",
  jsonSchemaResponse: "unknown",
  reasoningEffort: "unknown",
  logprobs: "unknown",
  streamingToolDeltas: "unknown",
  multiCandidate: "unknown",
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

  it("fail-closes UNKNOWN / UNVERIFIED / UNMEASURED for hard chat requirement", () => {
    expect(isChatCapableModel(model({ id: "u", displayName: "U", capabilities: { chat: "unknown" } }))).toBe(
      false,
    );
    expect(
      isChatCapableModel(model({ id: "uv", displayName: "UV", capabilities: { chat: "unverified" } })),
    ).toBe(false);
    expect(
      isChatCapableModel(model({ id: "um", displayName: "UM", capabilities: { chat: "unmeasured" } })),
    ).toBe(false);
    expect(chatIneligibilityReason(model({ id: "u", displayName: "U", capabilities: { chat: "unknown" } }))).toMatch(
      /unknown/i,
    );
    expect(
      chatIneligibilityReason(model({ id: "uv", displayName: "UV", capabilities: { chat: "unverified" } })),
    ).toMatch(/unverified/i);
    expect(
      chatIneligibilityReason(model({ id: "um", displayName: "UM", capabilities: { chat: "unmeasured" } })),
    ).toMatch(/unmeasured/i);
  });

  it("picker warning only for embeddings / unsupported / offline — not unverified LM Studio models", () => {
    expect(
      modelPickerWarning(
        model({
          id: "qwen",
          displayName: "Qwen2.5 Instruct",
          capabilities: { chat: "unverified" },
        }),
      ),
    ).toBeNull();
    expect(
      modelPickerWarning(
        model({
          id: "embed",
          displayName: "text-embedding-nomic-embed-text-v1.5",
          capabilities: { chat: "unknown" },
        }),
      ),
    ).toMatch(/Embedding|rerank/i);
    expect(
      modelPickerWarning(
        model({
          id: "bad",
          displayName: "Broken",
          capabilities: { chat: "unsupported" },
        }),
      ),
    ).toMatch(/niet ondersteund/i);
  });

  it("Auto remains conceptually available even when no models", () => {
    const { eligible } = partitionChatModels([]);
    expect(eligible).toEqual([]);
  });
});
