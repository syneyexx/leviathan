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
  chatModels: ModelDescriptor[];
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

  const { eligible: chatModels, ineligible: nonChatModels } = useMemo(
    () => partitionChatModels(models),
    [models],
  );

  const setReasoningMode = (mode: ReasoningModeId | string) => {
    setReasoningModeRaw(parseReasoningMode(mode));
  };

  useEffect(() => {
    if (!selectedModelId) return;
    const stillEligible = chatModels.some((item) => item.id === selectedModelId);
    if (!stillEligible) {
      setSelectedModelId(null);
      opts?.onIneligibleModel?.(
        "Selected model is not chat-capable — switched to Auto",
      );
    }
  }, [chatModels, selectedModelId, opts]);

  const modelLabel = useMemo(() => {
    if (!selectedModelId) return "Auto";
    const match = chatModels.find((item) => item.id === selectedModelId);
    return match?.displayName || match?.id || selectedModelId;
  }, [chatModels, selectedModelId]);

  const contextWindow = useMemo(() => {
    if (!selectedModelId) return null;
    const match = chatModels.find((item) => item.id === selectedModelId);
    return match?.contextWindow ?? null;
  }, [chatModels, selectedModelId]);

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
