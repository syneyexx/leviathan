/** Chat model eligibility helpers — keep in sync with backend capability policy. */

import type { ModelDescriptor } from "../types/api";

const NON_CHAT_FAMILY =
  /embed(?:ding|dings)?|\bbge\b|\be5\b|\bgte\b|nomic[-_]?embed|text[-_]?embedding|rerank(?:er|ing)?|cross[-_]?encoder|sentence[-_]?transformers|minilm|\bclip\b|colbert/i;

export function modelIdentityText(model: ModelDescriptor): string {
  return [
    model.id,
    model.displayName,
    model.family ?? "",
    model.architecture ?? "",
    String(model.metadata?.provider_model_id ?? ""),
    ...(model.tags ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

export function isObviousNonChatModel(model: ModelDescriptor): boolean {
  return NON_CHAT_FAMILY.test(modelIdentityText(model));
}

export function isChatCapableModel(model: ModelDescriptor): boolean {
  if (model.lifecycleState === "error" || model.lifecycleState === "offline") return false;
  const chat = model.capabilities?.chat;
  if (chat === "unsupported") return false;
  if (isObviousNonChatModel(model)) return false;
  if (chat === "supported" || chat === "unverified") return true;
  // unknown: allow only when not an obvious non-chat family (already filtered)
  return chat !== "unmeasured";
}

export function chatIneligibilityReason(model: ModelDescriptor): string {
  const chat = model.capabilities?.chat;
  if (chat === "unsupported") return "Chat capability unsupported";
  if (isObviousNonChatModel(model)) return "Embedding/rerank model — not for chat";
  if (chat === "unmeasured") return "Chat capability unmeasured";
  if (model.lifecycleState === "error" || model.lifecycleState === "offline") {
    return `Model ${model.lifecycleState}`;
  }
  return "Not eligible for chat";
}

export function partitionChatModels(models: ModelDescriptor[]): {
  eligible: ModelDescriptor[];
  ineligible: ModelDescriptor[];
} {
  const eligible: ModelDescriptor[] = [];
  const ineligible: ModelDescriptor[] = [];
  for (const model of models) {
    if (isChatCapableModel(model)) eligible.push(model);
    else ineligible.push(model);
  }
  return { eligible, ineligible };
}
