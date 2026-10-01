/**
 * useChatInspectorData — derived inspector fields from last turn + system telemetry.
 */
import { useMemo } from "react";
import type {
  AssistantTurnTelemetry,
  KnowledgeSource,
  SystemTelemetryResponse,
} from "../../../types/api";

export type ChatInspectorData = {
  tokenUsage: number | null;
  contextBudget: number | null;
  knowledgeSources: KnowledgeSource[];
  verification: string | null;
  lastTurnTelemetry: AssistantTurnTelemetry | null;
};

export type TurnMetaForInspector = {
  knowledgeSources?: KnowledgeSource[];
  verification?: string | null;
  telemetry?: AssistantTurnTelemetry | null;
};

export function useChatInspectorData(opts: {
  lastTurn: TurnMetaForInspector;
  contextWindow?: number | null;
  systemTelemetry?: SystemTelemetryResponse | null;
}): ChatInspectorData {
  const { lastTurn, contextWindow } = opts;

  return useMemo(() => {
    const tel = lastTurn.telemetry ?? null;
    return {
      tokenUsage: tel?.context_used ?? tel?.context_tokens ?? null,
      contextBudget: tel?.context_budget ?? contextWindow ?? null,
      knowledgeSources: lastTurn.knowledgeSources ?? [],
      verification: lastTurn.verification ?? null,
      lastTurnTelemetry: tel,
    };
  }, [lastTurn, contextWindow]);
}
