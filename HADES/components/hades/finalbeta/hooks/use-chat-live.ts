"use client";

/**
 * FINALBETA chat live hook — thin re-export of the shared HADES chat runtime.
 *
 * Today FINALBETA is the sole consumer of `useHadesChatRuntime`. Live tool /
 * event reconciliation (`mergeChatToolCalls`, `mergeLiveExecutionEvents`) lives
 * in that runtime so FINALBETA presentation stays truthful. Classic/Lux chat
 * keeps its own inline progress merge and is intentionally unchanged.
 */

export {
  conversationListTime,
  useHadesChatRuntime as useChatLive,
  type HadesChatRuntime as ChatLiveState,
  type HadesChatRuntime,
  type SendMessageOptions,
  type BranchCompareSide,
} from "@/components/hades/features/chat/hooks/useHadesChatRuntime";
