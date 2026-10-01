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

/**
 * Hard chat-requirement eligibility (fail-closed), aligned with backend
 * `capability_satisfies_request(..., requirement_mode="hard")`:
 * only explicit `supported` is eligible. UNKNOWN / UNVERIFIED / UNMEASURED
 * are rejected unless an explicit documented policy allows them (not used here).
 */
export function isChatCapableModel(model: ModelDescriptor): boolean {
  if (model.lifecycleState === "error" || model.lifecycleState === "offline") return false;
  if (isObviousNonChatModel(model)) return false;
  return model.capabilities?.chat === "supported";
}

export function chatIneligibilityReason(model: ModelDescriptor): string {
  const chat = model.capabilities?.chat;
  if (chat === "unsupported") return "Chat capability unsupported";
  if (isObviousNonChatModel(model)) return "Embedding/rerank model — not for chat";
  if (chat === "unmeasured") return "Chat capability unmeasured";
  if (chat === "unverified") return "Chat capability unverified";
  if (chat === "unknown" || chat == null) return "Chat capability unknown";
  if (model.lifecycleState === "error" || model.lifecycleState === "offline") {
    return `Model ${model.lifecycleState}`;
  }
  return "Not eligible for chat";
}

/**
 * Soft picker warning — only for models that will still fail even when the
 * operator explicitly selects them (embeddings / verified unsupported / offline).
 * Unverified LM Studio models are selectable and must not look "hidden".
 */
export function modelPickerWarning(model: ModelDescriptor): string | null {
  if (model.lifecycleState === "error" || model.lifecycleState === "offline") {
    return `Model ${model.lifecycleState}`;
  }
  if (isObviousNonChatModel(model)) return "Embedding/rerank — niet voor chat";
  if (model.capabilities?.chat === "unsupported") return "Chat niet ondersteund";
  return null;
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
