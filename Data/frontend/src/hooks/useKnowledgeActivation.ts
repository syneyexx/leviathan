/**
 * Subscribe to live runtime events and project brain.knowledge_activation.
 */

import { useCallback, useMemo, useState } from "react";
import { useLiveEvents } from "./useLiveEvents";
import {
  EMPTY_KNOWLEDGE_ACTIVATION,
  reduceKnowledgeActivation,
  type KnowledgeActivationState,
} from "../pages/brain/brain-activation";

export function useKnowledgeActivation(opts?: {
  enabled?: boolean;
  preferredConversationId?: string | null;
}) {
  const enabled = opts?.enabled ?? true;
  const preferredConversationId = opts?.preferredConversationId ?? null;
  const { events, connection, error, refresh } = useLiveEvents({
    enabled,
    bufferSize: 300,
    pollMs: 2000,
  });

  const [followedRequestId, setFollowedRequestId] = useState<string | null>(null);

  const activationBase = useMemo(
    () =>
      reduceKnowledgeActivation(EMPTY_KNOWLEDGE_ACTIVATION, events, {
        followedRequestId,
        preferredConversationId,
      }),
    [events, followedRequestId, preferredConversationId],
  );

  const followRequest = useCallback((requestId: string) => {
    setFollowedRequestId(requestId || null);
  }, []);

  const connectionNote = useMemo(() => {
    if (connection === "error") return error ?? "Eventstream error";
    if (connection === "reconnecting") return "Herverbindt met eventstream…";
    if (connection === "connecting") return "Eventstream verbinden…";
    return null;
  }, [connection, error]);

  const activation: KnowledgeActivationState = {
    ...activationBase,
    connectionNote,
  };

  return {
    activation,
    connection,
    followRequest,
    refresh,
  };
}
