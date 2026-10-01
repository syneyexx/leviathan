/**
 * useChatConfiguration — model, reasoning (incl. standard), collaboration, tool policy.
 */
import { useEffect, useMemo, useState } from "react";
import { partitionChatModels } from "../../../lib/chatModels";
import {
  DEFAULT_REASONING_MODE,
  parseReasoningMode,
  type ReasoningModeId,
} from "../../../lib/chat/reasoningModes";
import type { ModelDescriptor } from "../../../types/api";

export type CollaborationStrategy = "direct" | "team";

export type ChatConfigurationState = {
  selectedModelId: string | null;
  setSelectedModelId: (id: string | null) => void;
  reasoningMode: ReasoningModeId;
  setReasoningMode: (mode: ReasoningModeId) => void;
  collaborationStrategy: CollaborationStrategy;
  setCollaborationStrategy: (value: CollaborationStrategy) => void;
  toolPolicy: Record<string, unknown> | null;
  setToolPolicy: (policy: Record<string, unknown> | null) => void;
  /** All selectable registry models (chat picker shows every model). */
  chatModels: ModelDescriptor[];
  /** Models that fail hard chat eligibility — still listed, with UI warning. */
  nonChatModels: ModelDescriptor[];
  modelLabel: string;
  contextWindow: number | null;
};

export function useChatConfiguration(
  models: ModelDescriptor[],
  opts?: {
    onIneligibleModel?: (message: string) => void;
  },
): ChatConfigurationState {
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [reasoningMode, setReasoningModeRaw] = useState<ReasoningModeId>(
    DEFAULT_REASONING_MODE,
  );
  const [collaborationStrategy, setCollaborationStrategy] =
    useState<CollaborationStrategy>("direct");
  const [toolPolicy, setToolPolicy] = useState<Record<string, unknown> | null>(null);

  // Picker shows every discovered model; partition only for warning labels.
  const { ineligible: nonChatModels } = useMemo(() => partitionChatModels(models), [models]);
  const chatModels = models;

  const setReasoningMode = (mode: ReasoningModeId | string) => {
    setReasoningModeRaw(parseReasoningMode(mode));
  };

  useEffect(() => {
    if (!selectedModelId) return;
    const match = models.find((item) => item.id === selectedModelId);
    if (!match) {
      setSelectedModelId(null);
      opts?.onIneligibleModel?.("Selected model is no longer available — switched to Auto");
      return;
    }
    if (match.lifecycleState === "error" || match.lifecycleState === "offline") {
      setSelectedModelId(null);
      opts?.onIneligibleModel?.(
        `Selected model is ${match.lifecycleState} — switched to Auto`,
      );
    }
  }, [models, selectedModelId, opts]);

  const modelLabel = useMemo(() => {
    if (!selectedModelId) return "Auto";
    const match = models.find((item) => item.id === selectedModelId);
    return match?.displayName || match?.id || selectedModelId;
  }, [models, selectedModelId]);

  const contextWindow = useMemo(() => {
    if (!selectedModelId) return null;
    const match = models.find((item) => item.id === selectedModelId);
    return match?.contextWindow ?? null;
  }, [models, selectedModelId]);

  return {
    selectedModelId,
    setSelectedModelId,
    reasoningMode,
    setReasoningMode,
    collaborationStrategy,
    setCollaborationStrategy,
    toolPolicy,
    setToolPolicy,
    chatModels,
    nonChatModels,
    modelLabel,
    contextWindow,
  };
}
