/**
 * useChatInspectorData — derived inspector fields from last turn + system telemetry.
 * Never invent preferences/project labels — only surface measured/backend values.
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
  /** Measured behavior profile label when available; null → UI shows unavailable. */
  preferencesLabel: string | null;
  /** Measured project/context label when available; null → UI shows none. */
  projectContext: string | null;
};

export type TurnMetaForInspector = {
  knowledgeSources?: KnowledgeSource[];
  verification?: string | null;
  telemetry?: AssistantTurnTelemetry | null;
  behaviorProfileId?: string | null;
  behaviorVersion?: string | null;
  projectContext?: string | null;
};

function behaviorLabel(tel: AssistantTurnTelemetry | null, meta: TurnMetaForInspector): string | null {
  const id =
    meta.behaviorProfileId ||
    tel?.behavior_profile_id ||
    null;
  const version =
    meta.behaviorVersion ||
    tel?.behavior_version ||
    null;
  const hash = tel?.behavior_hash || null;
  if (!id && !version && !hash) return null;
  const bits = [id, version ? `v${version}` : null, hash ? `hash:${String(hash).slice(0, 8)}` : null].filter(
    Boolean,
  );
  return bits.length ? bits.join(" · ") : null;
}

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
      preferencesLabel: behaviorLabel(tel, lastTurn),
      projectContext: lastTurn.projectContext?.trim() || null,
    };
  }, [lastTurn, contextWindow]);
}
